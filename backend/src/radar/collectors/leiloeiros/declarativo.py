"""Motor declarativo de conectores de site de leiloeiro (secao 4.3).

Cada site de leiloeiro tem HTML proprio, mas o *trabalho* e sempre o mesmo:
achar os blocos de lote numa listagem, puxar meia duzia de campos de dentro de
cada bloco e, as vezes, abrir a pagina de detalhe. Escrever isso em Python 12
vezes produz 12 scrapers para manter; aqui a logica mora num lugar so e cada
site vira um perfil de dados em ``data/perfis_leiloeiros.yaml``.

Ganhos praticos:
* adicionar um leiloeiro e editar YAML, nao escrever codigo;
* quando um site muda de layout, o conserto e um seletor, e o teste de
  regressao correspondente (uma fixture por perfil) aponta exatamente onde;
* a engine e testada uma vez e vale para todos.

Perfis que precisam de logica impossivel de declarar (JSON embutido, API
interna) devem virar uma subclasse de ``Conector`` propria -- ver
``leiloeiros/exemplo_regional.py``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import yaml
from bs4 import Tag

from radar.collectors.base import Conector, MetadadosFonte, registrar
from radar.collectors.dto import DocumentoBruto, LoteBruto, PracaBruta, ResultadoConector
from radar.collectors.html import blocos_repetidos, sopa, texto
from radar.collectors.http import EstruturaInesperada, Fetcher
from radar.enums import ModalidadeLeilao, StatusLote, TipoBem, TipoDocumento, TipoFonte
from radar.normalizacao import (
    extrair_numero_cnj,
    hash_conteudo,
    limpar_espacos,
    normalizar_texto,
    parse_area,
    parse_data_hora,
    parse_moeda,
    parse_percentual,
)

logger = logging.getLogger(__name__)

ARQUIVO_PERFIS = Path(__file__).resolve().parents[1].parent / "data" / "perfis_leiloeiros.yaml"

_PALAVRAS_IMOVEL = (
    "imovel", "apartamento", "casa", "terreno", "lote de terreno", "sala comercial",
    "galpao", "fazenda", "sitio", "chacara", "predio", "loja", "kitnet", "flat",
    "area rural", "gleba", "vaga de garagem",
)
_PALAVRAS_VEICULO = (
    "veiculo", "automovel", "carro", "moto", "motocicleta", "caminhao", "onibus",
    "reboque", "trator", "camionete", "utilitario", "van", "pick-up", "picape",
)
_MAPA_STATUS_LOTE = (
    (("arremat", "vendido", "adjudicad"), StatusLote.ARREMATADO),
    (("suspens", "sobrestad"), StatusLote.SUSPENSO),
    (("deserto", "sem lance", "negativo"), StatusLote.DESERTO),
    (("cancelad", "revogad", "anulad"), StatusLote.CANCELADO),
    (("encerrad", "finalizad"), StatusLote.ENCERRADO),
    (("aberto", "em andamento", "aceitando lance", "disponivel"), StatusLote.ABERTO),
)


def inferir_tipo_bem(*trechos: str | None) -> TipoBem:
    alvo = normalizar_texto(" ".join(t for t in trechos if t))
    if not alvo:
        return TipoBem.OUTRO
    pontos_imovel = sum(1 for p in _PALAVRAS_IMOVEL if p in alvo)
    pontos_veiculo = sum(1 for p in _PALAVRAS_VEICULO if p in alvo)
    if pontos_veiculo > pontos_imovel:
        return TipoBem.VEICULO
    if pontos_imovel > 0:
        return TipoBem.IMOVEL
    return TipoBem.OUTRO


def inferir_status(*trechos: str | None) -> StatusLote:
    alvo = normalizar_texto(" ".join(t for t in trechos if t))
    for termos, status in _MAPA_STATUS_LOTE:
        if any(t in alvo for t in termos):
            return status
    return StatusLote.ABERTO


# ---------------------------------------------------------------------------
# Especificacao de campo
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class EspecCampo:
    """Como achar um campo dentro de um bloco de lote."""

    seletor: str | None = None
    atributo: str | None = None
    regex: str | None = None
    grupo: int = 1
    tipo: str = "texto"
    multiplo: bool = False
    padrao: Any = None

    @classmethod
    def de_dict(cls, dados: Any) -> EspecCampo:
        if isinstance(dados, str):
            return cls(seletor=dados)
        return cls(**dados)


def _converter(valor: str | None, tipo: str) -> Any:
    if valor is None:
        return None
    match tipo:
        case "texto":
            return limpar_espacos(valor)
        case "moeda":
            return parse_moeda(valor)
        case "percentual":
            return parse_percentual(valor)
        case "data_hora":
            return parse_data_hora(valor)
        case "area":
            return parse_area(valor)
        case "inteiro":
            m = re.search(r"\d{1,6}", valor.replace(".", ""))
            return int(m.group(0)) if m else None
        case "ano":
            m = re.search(r"\b(19|20)\d{2}\b", valor)
            return int(m.group(0)) if m else None
        case "processo":
            return extrair_numero_cnj(valor)
        case "url":
            return limpar_espacos(valor)
        case _:
            return limpar_espacos(valor)


def extrair_campo(bloco: Tag, espec: EspecCampo, base_url: str) -> Any:
    """Aplica a especificacao. Seletor primeiro; regex sobre o texto como apoio."""
    brutos: list[str] = []

    if espec.seletor:
        nodes = bloco.select(espec.seletor)
        for node in nodes:
            if espec.atributo:
                valor = node.get(espec.atributo)
                if isinstance(valor, list):
                    valor = " ".join(valor)
            else:
                valor = texto(node)
            if valor:
                brutos.append(str(valor))
            if not espec.multiplo and brutos:
                break

    if not brutos and espec.regex:
        alvo = texto(bloco, separador=" ")
        regex = re.compile(espec.regex, re.IGNORECASE | re.DOTALL)
        if espec.multiplo:
            brutos = [m.group(espec.grupo) for m in regex.finditer(alvo)]
        else:
            m = regex.search(alvo)
            if m:
                brutos = [m.group(espec.grupo)]
    elif brutos and espec.regex:
        # Seletor achou o container; regex refina o valor dentro dele.
        regex = re.compile(espec.regex, re.IGNORECASE | re.DOTALL)
        refinados = []
        for bruto in brutos:
            m = regex.search(bruto)
            refinados.append(m.group(espec.grupo) if m else bruto)
        brutos = refinados

    if not brutos:
        return espec.padrao

    if espec.tipo == "url":
        brutos = [urljoin(base_url, b.strip()) for b in brutos if b and b.strip()]

    if espec.multiplo:
        convertidos = [_converter(b, espec.tipo) for b in brutos]
        return [c for c in convertidos if c is not None]
    return _converter(brutos[0], espec.tipo)


# ---------------------------------------------------------------------------
# Perfil de site
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PerfilSite:
    slug: str
    nome: str
    uf: str
    base_url: str
    urls: list[str]
    campos: dict[str, EspecCampo]
    leiloeiro_nome: str | None = None
    leiloeiro_matricula: str | None = None
    seletor_item: str | None = None
    paginacao: str | None = None
    max_paginas: int = 5
    campos_detalhe: dict[str, EspecCampo] = field(default_factory=dict)
    seguir_detalhe: bool = False
    modalidade: str = "ELETRONICO"
    periodicidade_horas: int = 6
    validado_ao_vivo: bool = False
    observacao: str = ""

    @classmethod
    def de_dict(cls, dados: dict) -> PerfilSite:
        dados = dict(dados)
        dados["campos"] = {
            k: EspecCampo.de_dict(v) for k, v in (dados.get("campos") or {}).items()
        }
        dados["campos_detalhe"] = {
            k: EspecCampo.de_dict(v) for k, v in (dados.get("campos_detalhe") or {}).items()
        }
        return cls(**dados)


class ConectorDeclarativo(Conector):
    def __init__(self, perfil: PerfilSite) -> None:
        self.perfil = perfil
        self.meta = MetadadosFonte(
            slug=perfil.slug,
            nome=perfil.nome,
            tipo=TipoFonte.LEILOEIRO,
            uf=perfil.uf,
            url_alvo=perfil.urls[0] if perfil.urls else perfil.base_url,
            periodicidade_horas=perfil.periodicidade_horas,
            descricao=perfil.observacao or f"Lotes publicados por {perfil.nome}.",
            validado_ao_vivo=perfil.validado_ao_vivo,
        )

    # -- coleta ------------------------------------------------------------

    def coletar(self, fetcher: Fetcher) -> ResultadoConector:
        resultado = ResultadoConector()
        for url in self._urls():
            resposta = fetcher.get(url, fonte_slug=self.slug)
            if not resposta.ok:
                resultado.avisos.append(f"{url} devolveu HTTP {resposta.status}")
                continue
            resultado.paginas_visitadas += 1
            lotes = self.parse(resposta.texto, url)
            if not lotes:
                if self.perfil.paginacao:
                    break
                resultado.avisos.append(f"nenhum lote extraido de {url}")
            resultado.lotes.extend(lotes)

        if self.perfil.seguir_detalhe and self.perfil.campos_detalhe:
            for lote in resultado.lotes:
                self._enriquecer_detalhe(lote, fetcher, resultado)

        if not resultado.lotes:
            raise EstruturaInesperada(
                f"{self.slug}: nenhum lote reconhecido. Se o site mudou, ajuste o perfil "
                f"em data/perfis_leiloeiros.yaml e atualize a fixture do teste."
            )
        return resultado

    def _urls(self):
        for url in self.perfil.urls:
            if not self.perfil.paginacao:
                yield url
                continue
            for n in range(1, self.perfil.max_paginas + 1):
                yield url + self.perfil.paginacao.format(n=n)

    def _enriquecer_detalhe(
        self, lote: LoteBruto, fetcher: Fetcher, resultado: ResultadoConector
    ) -> None:
        if not lote.fonte_url:
            return
        try:
            resposta = fetcher.get(lote.fonte_url, fonte_slug=self.slug)
        except Exception as exc:  # detalhe e opcional: nao derruba a coleta
            resultado.avisos.append(f"detalhe de {lote.fonte_url} falhou: {exc}")
            return
        if not resposta.ok:
            return
        resultado.paginas_visitadas += 1
        doc = sopa(resposta.texto)
        valores = {
            nome: extrair_campo(doc, espec, lote.fonte_url)
            for nome, espec in self.perfil.campos_detalhe.items()
        }
        self._aplicar(lote, valores, sobrescrever=False)

    # -- parsing -----------------------------------------------------------

    def parse(self, html: str, url: str) -> list[LoteBruto]:
        doc = sopa(html)
        if self.perfil.seletor_item:
            blocos = doc.select(self.perfil.seletor_item)
        else:
            blocos = blocos_repetidos(doc)

        lotes: list[LoteBruto] = []
        for bloco in blocos:
            lote = self._de_bloco(bloco, url)
            if lote is not None:
                lotes.append(lote)
        return lotes

    def _de_bloco(self, bloco: Tag, url: str) -> LoteBruto | None:
        valores = {
            nome: extrair_campo(bloco, espec, url)
            for nome, espec in self.perfil.campos.items()
        }
        conteudo = texto(bloco, separador=" ")
        titulo = valores.get("titulo") or limpar_espacos(conteudo[:160])
        if not titulo or len(titulo) < 4:
            return None

        # Um bloco sem nenhum sinal financeiro nem link quase sempre e ruido de
        # layout (menu, rodape) capturado pela heuristica de blocos repetidos.
        sinais = [
            valores.get("valor_avaliacao"),
            valores.get("valor_minimo_primeira"),
            valores.get("valor_minimo_segunda"),
            valores.get("url_detalhe"),
            valores.get("numero_processo"),
            valores.get("data_primeira_praca"),
        ]
        if not any(s is not None for s in sinais):
            return None

        lote = LoteBruto(
            fonte_slug=self.slug,
            fonte_url=valores.get("url_detalhe") or url,
            titulo=str(titulo)[:300],
            leiloeiro_nome=self.perfil.leiloeiro_nome,
            leiloeiro_matricula=self.perfil.leiloeiro_matricula,
            uf=self.perfil.uf,
            modalidade=ModalidadeLeilao(self.perfil.modalidade),
            extras={"chave_fallback": hash_conteudo(self.slug, titulo, conteudo[:400])},
        )
        self._aplicar(lote, valores, sobrescrever=True)
        lote.descricao = lote.descricao or limpar_espacos(conteudo)[:4000]
        lote.tipo_bem = (
            TipoBem(valores["tipo_bem"])
            if valores.get("tipo_bem") in set(TipoBem)
            else inferir_tipo_bem(lote.titulo, lote.descricao)
        )
        lote.status = inferir_status(valores.get("status"), conteudo)
        return lote

    def _aplicar(self, lote: LoteBruto, valores: dict, *, sobrescrever: bool) -> None:
        simples = (
            "descricao", "numero_lote", "endereco", "bairro", "cidade", "cep",
            "matricula_imovel", "cartorio", "marca", "modelo", "combustivel",
            "comarca", "vara", "leilao_titulo",
        )
        for nome in simples:
            valor = valores.get(nome)
            if valor and (sobrescrever or getattr(lote, nome) is None):
                setattr(lote, nome, valor)

        for nome in ("valor_avaliacao", "comissao_percentual", "area_total_m2"):
            valor = valores.get(nome)
            if isinstance(valor, Decimal) and (sobrescrever or getattr(lote, nome) is None):
                setattr(lote, nome, valor)

        for nome in ("ano_fabricacao", "ano_modelo"):
            valor = valores.get(nome)
            if isinstance(valor, int) and (sobrescrever or getattr(lote, nome) is None):
                setattr(lote, nome, valor)

        if valores.get("numero_processo"):
            lote.numero_processo = lote.numero_processo or valores["numero_processo"]
        elif not lote.numero_processo:
            lote.numero_processo = extrair_numero_cnj(lote.descricao or lote.titulo)

        if valores.get("placa"):
            lote.placa = valores["placa"]

        if valores.get("uf"):
            lote.uf = valores["uf"]

        fotos = valores.get("fotos")
        if isinstance(fotos, list) and fotos:
            lote.fotos = fotos
        elif isinstance(fotos, str):
            lote.fotos = [fotos]

        edital = valores.get("url_edital")
        if edital:
            urls_existentes = {d.url for d in lote.documentos}
            if edital not in urls_existentes:
                lote.documentos.append(
                    DocumentoBruto(url=edital, tipo=TipoDocumento.EDITAL, titulo="Edital")
                )

        self._aplicar_pracas(lote, valores)

    @staticmethod
    def _aplicar_pracas(lote: LoteBruto, valores: dict) -> None:
        por_ordem = {p.ordem: p for p in lote.pracas}
        pares = (
            (1, "data_primeira_praca", "valor_minimo_primeira", "percentual_primeira"),
            (2, "data_segunda_praca", "valor_minimo_segunda", "percentual_segunda"),
        )
        for ordem, chave_data, chave_valor, chave_pct in pares:
            data = valores.get(chave_data)
            valor = valores.get(chave_valor)
            pct = valores.get(chave_pct)
            if data is None and valor is None and pct is None:
                continue
            praca = por_ordem.get(ordem) or PracaBruta(ordem=ordem)
            praca.data_hora = praca.data_hora or data
            praca.valor_minimo = praca.valor_minimo or valor
            praca.percentual_minimo = praca.percentual_minimo or pct
            por_ordem[ordem] = praca
        lote.pracas = [por_ordem[k] for k in sorted(por_ordem)]


# ---------------------------------------------------------------------------
# Carregamento dos perfis
# ---------------------------------------------------------------------------


def carregar_perfis(caminho: Path | None = None) -> list[PerfilSite]:
    arquivo = caminho or ARQUIVO_PERFIS
    if not arquivo.exists():
        logger.warning("arquivo de perfis nao encontrado: %s", arquivo)
        return []
    dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
    return [PerfilSite.de_dict(p) for p in dados.get("perfis", [])]


def registrar_perfis(caminho: Path | None = None) -> list[ConectorDeclarativo]:
    conectores = []
    for perfil in carregar_perfis(caminho):
        conector = ConectorDeclarativo(perfil)
        try:
            registrar(conector)
        except ValueError:
            continue  # ja registrado (recarregamento em testes)
        conectores.append(conector)
    return conectores
