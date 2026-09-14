"""Deduplicacao: o mesmo lote anunciado em duas fontes (secao 5).

Cenario tipico: o TJPE publica o edital do processo X e o site do leiloeiro
publica o mesmo lote com foto e valor. Sao dois registros da mesma coisa e o
usuario nao pode ver duplicado.

Estrategia: uma escada de chaves de identidade, da mais forte para a mais fraca.
So a primeira que casar vale -- nao vale somar evidencias fracas, porque dois
apartamentos do mesmo predio leiloados no mesmo processo sao lotes diferentes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.enums import EsferaJustica, NaturezaBem, TipoBem, ZonaImovel
from radar.ingest.normalizador import LoteNormalizado
from radar.models import Lote
from radar.normalizacao import normalizar_texto

logger = logging.getLogger(__name__)

# Fontes de tribunal sao autoridade sobre processo/comarca/vara; sites de
# leiloeiro sao autoridade sobre o bem (foto, descricao, valor, praca).
CAMPOS_DO_TRIBUNAL = frozenset({"numero_processo", "comarca", "vara", "tribunal_sigla"})


@dataclass(frozen=True, slots=True)
class ChaveIdentidade:
    tipo: str
    valor: str
    forca: int  # maior = mais confiavel


def chaves_identidade(norm: LoteNormalizado) -> list[ChaveIdentidade]:
    bruto = norm.bruto
    chaves: list[ChaveIdentidade] = []

    if norm.processo_valido and norm.numero_processo:
        lote = normalizar_texto(bruto.numero_lote or "") or "unico"
        chaves.append(
            ChaveIdentidade("processo_lote", f"{norm.numero_processo}#{lote}", 100)
        )

    if bruto.tipo_bem is TipoBem.IMOVEL and bruto.matricula_imovel and norm.uf:
        matricula = normalizar_texto(bruto.matricula_imovel)
        if len(matricula) >= 3:
            chaves.append(ChaveIdentidade("matricula", f"{norm.uf}#{matricula}", 90))

    if bruto.tipo_bem is TipoBem.VEICULO and norm.placa_parcial:
        chaves.append(
            ChaveIdentidade("placa", f"{norm.placa_parcial}#{bruto.ano_modelo or ''}", 80)
        )

    chaves.append(ChaveIdentidade("chave_natural", norm.chave_natural, 10))
    return sorted(chaves, key=lambda c: c.forca, reverse=True)


def localizar_existente(sessao: Session, norm: LoteNormalizado) -> Lote | None:
    """Procura um lote ja gravado que seja o mesmo bem."""
    for chave in chaves_identidade(norm):
        match chave.tipo:
            case "processo_lote":
                processo, numero = chave.valor.split("#", 1)
                consulta = select(Lote).where(Lote.numero_processo == processo)
                for candidato in sessao.scalars(consulta):
                    atual = normalizar_texto(candidato.numero_lote or "") or "unico"
                    if atual == numero:
                        return candidato
            case "matricula":
                uf, matricula = chave.valor.split("#", 1)
                consulta = select(Lote).where(Lote.uf == uf, Lote.matricula.isnot(None))
                for candidato in sessao.scalars(consulta):
                    if normalizar_texto(candidato.matricula) == matricula:
                        return candidato
            case "placa":
                placa, ano = chave.valor.split("#", 1)
                consulta = select(Lote).where(Lote.placa_parcial == placa)
                for candidato in sessao.scalars(consulta):
                    if not ano or str(candidato.ano_modelo or "") == ano:
                        return candidato
            case "chave_natural":
                achado = sessao.scalar(
                    select(Lote).where(Lote.chave_natural == chave.valor)
                )
                if achado is not None:
                    return achado
    return None


def mesclar(destino: Lote, norm: LoteNormalizado, prioridade_fonte: int) -> list[str]:
    """Aplica os dados novos sobre o lote existente. Devolve os campos mudados.

    Politica: campo vazio sempre e preenchido; campo preenchido so e substituido
    quando a fonte nova tem mais autoridade sobre aquele campo especifico.
    """
    bruto = norm.bruto
    alteracoes: list[str] = []

    def aplicar(campo: str, valor, *, autoridade: bool = False) -> None:
        if valor is None or valor == "" or valor == []:
            return
        atual = getattr(destino, campo)
        if atual == valor:
            return
        if atual is None or atual == "" or atual == [] or autoridade:
            setattr(destino, campo, valor)
            alteracoes.append(campo)

    tribunal_manda = prioridade_fonte >= 3
    aplicar("numero_processo", norm.numero_processo, autoridade=tribunal_manda)
    aplicar("titulo", bruto.titulo)
    aplicar("descricao", norm.descricao)
    aplicar("numero_lote", bruto.numero_lote)
    aplicar("valor_avaliacao", bruto.valor_avaliacao)
    aplicar("valor_minimo_primeira", norm.valor_minimo_primeira)
    aplicar("valor_minimo_segunda", norm.valor_minimo_segunda)
    aplicar("comissao_leiloeiro_percentual", bruto.comissao_percentual)
    aplicar("endereco", norm.endereco)
    aplicar("bairro", norm.bairro)
    aplicar("cidade", norm.cidade)
    aplicar("uf", norm.uf)
    aplicar("cep", bruto.cep)
    aplicar("matricula", bruto.matricula_imovel)
    aplicar("cartorio", bruto.cartorio)
    aplicar("area_total_m2", bruto.area_total_m2)
    aplicar("placa_parcial", norm.placa_parcial)
    aplicar("marca", bruto.marca)
    aplicar("modelo", bruto.modelo)
    aplicar("ano_fabricacao", bruto.ano_fabricacao)
    aplicar("ano_modelo", bruto.ano_modelo)
    aplicar("combustivel", bruto.combustivel)
    aplicar("latitude", norm.latitude)
    aplicar("longitude", norm.longitude)
    aplicar("geocodificacao_precisao", norm.geocodificacao_precisao)
    if bruto.ocupado is not None and destino.ocupado is None:
        destino.ocupado = bruto.ocupado
        alteracoes.append("ocupado")

    if bruto.tipo_bem is not TipoBem.OUTRO and destino.tipo_bem is TipoBem.OUTRO:
        destino.tipo_bem = bruto.tipo_bem
        alteracoes.append("tipo_bem")

    # Classificacao so preenche buraco: a fonte que ja tinha dito "imovel rural"
    # com evidencia nao e rebaixada por outra fonte que so viu "imovel". A
    # confianca e a evidencia de cada uma ficam em campo_extraido.
    if (
        norm.classificacao.natureza is not NaturezaBem.INDEFINIDA
        and destino.natureza_bem is NaturezaBem.INDEFINIDA
    ):
        destino.natureza_bem = norm.classificacao.natureza
        alteracoes.append("natureza_bem")
    if (
        norm.classificacao.zona is not ZonaImovel.INDEFINIDA
        and destino.zona_imovel is ZonaImovel.INDEFINIDA
    ):
        destino.zona_imovel = norm.classificacao.zona
        alteracoes.append("zona_imovel")
    if (
        norm.esfera is not EsferaJustica.DESCONHECIDA
        and destino.esfera is EsferaJustica.DESCONHECIDA
    ):
        destino.esfera = norm.esfera
        alteracoes.append("esfera")

    if bruto.fotos and not destino.fotos:
        destino.fotos = list(bruto.fotos)
        alteracoes.append("fotos")

    for lista, campo in ((bruto.onus, "onus"), (bruto.debitos, "debitos")):
        if lista:
            atual = list(getattr(destino, campo) or [])
            novos = [i for i in lista if i not in atual]
            if novos:
                setattr(destino, campo, atual + novos)
                alteracoes.append(campo)

    # Registra que o lote tambem aparece nesta outra fonte.
    if bruto.fonte_url and bruto.fonte_url != destino.fonte_url:
        secundarias = list(destino.fontes_secundarias or [])
        registro = {"fonte": bruto.fonte_slug, "url": bruto.fonte_url}
        if registro not in secundarias:
            secundarias.append(registro)
            destino.fontes_secundarias = secundarias
            alteracoes.append("fontes_secundarias")

    return alteracoes
