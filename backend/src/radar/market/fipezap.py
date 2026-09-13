"""Referencia de valor de imovel via indice FipeZap (secao 4.5).

Nao existe "tabela FIPE de imovel". O FipeZap e um indice de valor de ANUNCIO
por m2 de area util, publicado em boletim mensal em PDF -- nao e API, nao e
preco de venda fechado e nao cobre todo municipio.

Consequencias que o codigo respeita:
* a busca degrada de bairro para cidade, e a precisao viaja junto;
* a defasagem (mes do boletim) vai junto do numero ate a tela;
* a metodologia e devolvida em texto, para caber no tooltip da UI;
* preferimos area privativa a area total, porque e sobre area util que o
  indice e calculado -- usar area total infla o valor de referencia.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.models import IndiceFipeZap
from radar.normalizacao import normalizar_texto

logger = logging.getLogger(__name__)

ARQUIVO_INDICE = Path(__file__).resolve().parents[1] / "data" / "fipezap_demo.csv"
FONTE_URL = "https://downloads.fipe.org.br/indices/fipezap/"


@dataclass(frozen=True, slots=True)
class ValorM2:
    valor_m2: Decimal
    uf: str
    cidade: str
    bairro: str | None
    mes_referencia: str
    precisao: str  # BAIRRO | CIDADE
    demonstracao: bool = False

    @property
    def data_referencia(self) -> datetime | None:
        try:
            ano, mes = self.mes_referencia.split("-")
            return datetime(int(ano), int(mes), 1, tzinfo=UTC)
        except (ValueError, AttributeError):
            return None

    @property
    def rotulo(self) -> str:
        onde = f"{self.bairro}, {self.cidade}" if self.bairro else self.cidade
        return f"{onde}/{self.uf} — índice de {self.mes_referencia}"


def consultar(
    sessao: Session, uf: str | None, cidade: str | None, bairro: str | None = None
) -> ValorM2 | None:
    """Valor do m2, preferindo o bairro e caindo para a cidade."""
    if not uf or not cidade:
        return None
    cidade_alvo = normalizar_texto(cidade)
    candidatos = [
        indice
        for indice in sessao.scalars(select(IndiceFipeZap).where(IndiceFipeZap.uf == uf.upper()))
        if normalizar_texto(indice.cidade) == cidade_alvo
    ]
    if not candidatos:
        return None

    mais_recente = max(c.mes_referencia for c in candidatos)
    candidatos = [c for c in candidatos if c.mes_referencia == mais_recente]

    escolhido = None
    if bairro:
        bairro_alvo = normalizar_texto(bairro)
        escolhido = next(
            (c for c in candidatos if c.bairro and normalizar_texto(c.bairro) == bairro_alvo),
            None,
        )
    if escolhido is None:
        escolhido = next((c for c in candidatos if not c.bairro), None)
    if escolhido is None:
        return None

    return ValorM2(
        valor_m2=escolhido.valor_m2_venda,
        uf=escolhido.uf,
        cidade=escolhido.cidade,
        bairro=escolhido.bairro,
        mes_referencia=escolhido.mes_referencia,
        precisao="BAIRRO" if escolhido.bairro else "CIDADE",
        demonstracao=bool(escolhido.observacao and "demonstra" in escolhido.observacao.lower()),
    )


def carregar_indice(sessao: Session, caminho: Path | None = None) -> int:
    """Importa um CSV de indice. Idempotente por (uf, cidade, bairro, mes)."""
    arquivo = caminho or ARQUIVO_INDICE
    if not arquivo.exists():
        logger.warning("indice FipeZap nao encontrado: %s", arquivo)
        return 0
    importados = 0
    with arquivo.open(encoding="utf-8") as fh:
        linhas = (linha for linha in fh if not linha.startswith("#"))
        for registro in csv.DictReader(linhas):
            bairro = (registro.get("bairro") or "").strip() or None
            existente = sessao.scalar(
                select(IndiceFipeZap).where(
                    IndiceFipeZap.uf == registro["uf"].upper(),
                    IndiceFipeZap.cidade == registro["cidade"],
                    IndiceFipeZap.bairro.is_(bairro) if bairro is None
                    else IndiceFipeZap.bairro == bairro,
                    IndiceFipeZap.mes_referencia == registro["mes_referencia"],
                )
            )
            if existente is not None:
                existente.valor_m2_venda = Decimal(registro["valor_m2_venda"])
                continue
            sessao.add(
                IndiceFipeZap(
                    uf=registro["uf"].upper(),
                    cidade=registro["cidade"],
                    bairro=bairro,
                    valor_m2_venda=Decimal(registro["valor_m2_venda"]),
                    mes_referencia=registro["mes_referencia"],
                    fonte_url=FONTE_URL,
                    observacao=registro.get("observacao"),
                )
            )
            importados += 1
    sessao.flush()
    return importados
