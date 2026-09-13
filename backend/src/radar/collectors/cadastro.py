"""Coletor generico de cadastros de leiloeiros (secao 4.2 e parte da 4.1).

JUCEAL, JUCESE, JUCEPE e os bancos de leiloeiros das corregedorias do TJAL e do
TJSE publicam a mesma coisa em layouts diferentes: uma lista de pessoas com
nome, matricula, situacao e contato. Um unico parser semantico atende todas --
tabela quando existe, cards quando nao existe.
"""

from __future__ import annotations

import logging
import re

from radar.collectors.base import Conector, MetadadosFonte
from radar.collectors.dto import LeiloeiroBruto, ResultadoConector
from radar.collectors.html import (
    blocos_repetidos,
    href_por_rotulo,
    linhas_como_dicts,
    primeiro_email,
    primeiro_site,
    primeiro_telefone,
    sopa,
    tabelas_com_colunas,
    texto,
    valor_por_rotulo,
)
from radar.collectors.http import EstruturaInesperada, Fetcher
from radar.enums import JuntaComercial, StatusLeiloeiro
from radar.normalizacao import limpar_espacos, normalizar_texto, remover_acentos

logger = logging.getLogger(__name__)

_COLUNAS_ESPERADAS = ("nome", "leiloeiro", "matricula", "registro", "situacao", "comarca")

_MAPA_STATUS = (
    (("suspens",), StatusLeiloeiro.SUSPENSO),
    (("cancel", "baixad", "inativ", "destitu", "exonerad"), StatusLeiloeiro.INATIVO),
    (("ativ", "em exercicio", "em atividade", "regular", "habilitad"), StatusLeiloeiro.ATIVO),
)

_RE_MATRICULA = re.compile(r"\b(?:n[o°º.]?\s*)?(\d{2,6}(?:[/-]\d{2,4})?)\b")


def interpretar_status(valor: str | None) -> StatusLeiloeiro:
    alvo = normalizar_texto(valor)
    if not alvo:
        return StatusLeiloeiro.DESCONHECIDO
    for termos, status in _MAPA_STATUS:
        if any(t in alvo for t in termos):
            return status
    return StatusLeiloeiro.DESCONHECIDO


def _partir_comarcas(valor: str | None) -> list[str]:
    if not valor:
        return []
    partes = re.split(r"[;,/]| e ", valor)
    return [p for p in (limpar_espacos(x) for x in partes) if p and len(p) > 2]


class ColetorCadastroLeiloeiros(Conector):
    def __init__(
        self,
        meta: MetadadosFonte,
        urls: list[str],
        junta: JuntaComercial | None,
        uf: str,
        status_padrao: StatusLeiloeiro = StatusLeiloeiro.DESCONHECIDO,
    ) -> None:
        self.meta = meta
        self.urls = urls
        self.junta = junta
        self.uf = uf
        self.status_padrao = status_padrao

    def coletar(self, fetcher: Fetcher) -> ResultadoConector:
        resultado = ResultadoConector()
        for url in self.urls:
            resposta = fetcher.get(url, fonte_slug=self.meta.slug)
            if not resposta.ok:
                resultado.avisos.append(f"{url} devolveu HTTP {resposta.status}")
                continue
            resultado.paginas_visitadas += 1
            encontrados = self.parse(resposta.texto, url)
            if not encontrados:
                resultado.avisos.append(f"nenhum leiloeiro extraido de {url}")
            resultado.leiloeiros.extend(encontrados)

        if not resultado.leiloeiros:
            raise EstruturaInesperada(
                f"{self.meta.slug}: nenhuma linha de leiloeiro reconhecida em "
                f"{len(self.urls)} pagina(s) -- provavel mudanca de layout"
            )
        return resultado

    # -- parsing -----------------------------------------------------------

    def parse(self, html: str, url: str) -> list[LeiloeiroBruto]:
        doc = sopa(html)
        registros: list[LeiloeiroBruto] = []

        for tabela in tabelas_com_colunas(doc, _COLUNAS_ESPERADAS, minimo=1):
            for linha in linhas_como_dicts(tabela):
                item = self._de_linha(linha, url)
                if item is not None:
                    registros.append(item)

        if not registros:
            for bloco in blocos_repetidos(doc):
                item = self._de_bloco(bloco, url)
                if item is not None:
                    registros.append(item)

        return self._deduplicar(registros)

    def _de_linha(self, linha: dict[str, str], url: str) -> LeiloeiroBruto | None:
        nome = valor_por_rotulo(linha, "nome", "leiloeiro", "razao social")
        if not nome:
            # Tabela de uma coluna so: usa a primeira celula com texto longo.
            candidatos = [
                v for k, v in linha.items() if not k.endswith("__href") and len(v) > 6
            ]
            nome = candidatos[0] if candidatos else None
        nome = limpar_espacos(nome)
        if not nome or len(nome) < 5 or normalizar_texto(nome).startswith("total"):
            return None

        bruto_matricula = valor_por_rotulo(linha, "matricula", "registro", "numero", "jucep")
        matricula = None
        if bruto_matricula:
            m = _RE_MATRICULA.search(bruto_matricula)
            matricula = m.group(1) if m else limpar_espacos(bruto_matricula)

        contato = " ".join(v for k, v in linha.items() if not k.endswith("__href"))
        site = href_por_rotulo(linha, "site", "endereco eletronico", "pagina", "url")
        if site and not site.startswith("http"):
            site = None

        return LeiloeiroBruto(
            nome=nome,
            matricula=matricula,
            junta=self.junta,
            uf=self.uf,
            status=interpretar_status(
                valor_por_rotulo(linha, "situacao", "status", "condicao")
            )
            or self.status_padrao,
            site_url=site,
            email=primeiro_email(contato),
            telefone=primeiro_telefone(contato),
            comarcas=_partir_comarcas(
                valor_por_rotulo(linha, "comarca", "municipio", "atuacao", "sede")
            ),
            fonte_slug=self.meta.slug,
            fonte_url=url,
        )

    def _de_bloco(self, bloco, url: str) -> LeiloeiroBruto | None:
        conteudo = texto(bloco, separador=" | ")
        if len(conteudo) < 10:
            return None
        titulo = bloco.find(["h1", "h2", "h3", "h4", "strong", "b"])
        nome = limpar_espacos(texto(titulo)) or conteudo.split("|")[0].strip()
        if not nome or len(nome) < 5:
            return None
        # Busca no texto sem acento: no HTML real vem "Matricula", "Matr\u00edcula"
        # e "MATR\u00cdCULA" na mesma pagina.
        m = re.search(
            r"(?:matricula|registro|jucea?l?|jucese|jucepe)\s*:?\s*(?:n[o\u00b0\u00ba.]?\s*)?([\w/-]+)",
            remover_acentos(conteudo),
            re.IGNORECASE,
        )
        return LeiloeiroBruto(
            nome=nome,
            matricula=m.group(1) if m else None,
            junta=self.junta,
            uf=self.uf,
            status=interpretar_status(conteudo) or self.status_padrao,
            site_url=primeiro_site(bloco),
            email=primeiro_email(conteudo),
            telefone=primeiro_telefone(conteudo),
            comarcas=[],
            fonte_slug=self.meta.slug,
            fonte_url=url,
        )

    @staticmethod
    def _deduplicar(itens: list[LeiloeiroBruto]) -> list[LeiloeiroBruto]:
        vistos: dict[tuple[str, str | None], LeiloeiroBruto] = {}
        for item in itens:
            chave = (normalizar_texto(item.nome), item.matricula)
            atual = vistos.get(chave)
            if atual is None:
                vistos[chave] = item
                continue
            # Mantem o registro mais completo.
            preenchidos = sum(
                1 for v in (item.site_url, item.email, item.telefone) if v
            )
            atuais = sum(1 for v in (atual.site_url, atual.email, atual.telefone) if v)
            if preenchidos > atuais:
                vistos[chave] = item
        return list(vistos.values())
