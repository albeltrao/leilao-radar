"""Construtor de consultas de lote, compartilhado pela API e pelos alertas.

Uma implementacao so de filtro. Se a busca da tela e o casamento do alerta
usassem regras diferentes, o usuario salvaria um filtro vendo 10 resultados e
receberia e-mail de outros 10 -- e nao teria como saber qual dos dois mente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import selectinload

from radar.enums import StatusLote, TipoBem
from radar.models import EventoCalendario, Leilao, Lote, ScoreOportunidade
from radar.normalizacao import normalizar_texto

ORDENACOES = {
    "score": (ScoreOportunidade.total, True),
    "desconto": (ScoreOportunidade.desconto_destaque, True),
    "praca": (None, False),  # tratada a parte (vem de evento)
    "valor": (Lote.valor_minimo_segunda, False),
    "recente": (Lote.coletado_em, True),
}


@dataclass(slots=True)
class FiltroLotes:
    uf: list[str] = field(default_factory=list)
    cidades: list[str] = field(default_factory=list)
    bairros: list[str] = field(default_factory=list)
    tipo_bem: list[TipoBem] = field(default_factory=list)
    status: list[StatusLote] = field(default_factory=lambda: [StatusLote.ABERTO])
    valor_minimo: Decimal | None = None
    valor_maximo: Decimal | None = None
    desconto_minimo: float | None = None
    score_minimo: float | None = None
    dias_ate_praca_max: int | None = None
    leiloeiro_ids: list[int] = field(default_factory=list)
    somente_desocupados: bool = False
    sem_onus: bool = False
    texto: str | None = None
    ordenar: str = "score"
    pagina: int = 1
    tamanho: int = 24

    @classmethod
    def de_criterios(cls, criterios: dict[str, Any]) -> FiltroLotes:
        """Converte o JSON salvo em Alerta.criterios. Ignora chave desconhecida."""
        dados = dict(criterios or {})

        def lista(chave: str) -> list:
            valor = dados.get(chave)
            if valor is None:
                return []
            return list(valor) if isinstance(valor, list | tuple) else [valor]

        return cls(
            uf=[str(u).upper() for u in lista("uf")],
            cidades=[str(c) for c in lista("cidades")],
            bairros=[str(b) for b in lista("bairros")],
            tipo_bem=[TipoBem(t) for t in lista("tipo_bem") if t in set(TipoBem)],
            status=[StatusLote(s) for s in lista("status") if s in set(StatusLote)]
            or [StatusLote.ABERTO],
            valor_minimo=_decimal(dados.get("valor_minimo")),
            valor_maximo=_decimal(dados.get("valor_maximo")),
            desconto_minimo=_float(dados.get("desconto_minimo")),
            score_minimo=_float(dados.get("score_minimo")),
            dias_ate_praca_max=_int(dados.get("dias_ate_praca_max")),
            leiloeiro_ids=[int(i) for i in lista("leiloeiro_ids")],
            somente_desocupados=bool(dados.get("somente_desocupados", False)),
            sem_onus=bool(dados.get("sem_onus", False)),
            texto=dados.get("texto") or None,
        )


def _decimal(valor) -> Decimal | None:
    return None if valor in (None, "") else Decimal(str(valor))


def _float(valor) -> float | None:
    return None if valor in (None, "") else float(valor)


def _int(valor) -> int | None:
    return None if valor in (None, "") else int(valor)


def construir(filtro: FiltroLotes, agora: datetime | None = None) -> Select:
    agora = agora or datetime.now(UTC)
    consulta = (
        select(Lote)
        .outerjoin(ScoreOportunidade, ScoreOportunidade.lote_id == Lote.id)
        .options(
            selectinload(Lote.score),
            selectinload(Lote.analises),
            selectinload(Lote.eventos),
            selectinload(Lote.leilao).selectinload(Leilao.leiloeiro),
            selectinload(Lote.leilao).selectinload(Leilao.pracas),
        )
    )

    if filtro.status:
        consulta = consulta.where(Lote.status.in_(filtro.status))
    if filtro.uf:
        consulta = consulta.where(Lote.uf.in_(filtro.uf))
    if filtro.tipo_bem:
        consulta = consulta.where(Lote.tipo_bem.in_(filtro.tipo_bem))
    if filtro.valor_minimo is not None:
        consulta = consulta.where(
            or_(
                Lote.valor_minimo_segunda >= filtro.valor_minimo,
                and_(
                    Lote.valor_minimo_segunda.is_(None),
                    Lote.valor_minimo_primeira >= filtro.valor_minimo,
                ),
            )
        )
    if filtro.valor_maximo is not None:
        consulta = consulta.where(
            or_(
                Lote.valor_minimo_segunda <= filtro.valor_maximo,
                and_(
                    Lote.valor_minimo_segunda.is_(None),
                    Lote.valor_minimo_primeira <= filtro.valor_maximo,
                ),
            )
        )
    if filtro.desconto_minimo is not None:
        consulta = consulta.where(
            ScoreOportunidade.desconto_destaque >= filtro.desconto_minimo
        )
    if filtro.score_minimo is not None:
        consulta = consulta.where(ScoreOportunidade.total >= filtro.score_minimo)
    if filtro.leiloeiro_ids:
        consulta = consulta.where(
            Lote.leilao.has(Leilao.leiloeiro_id.in_(filtro.leiloeiro_ids))
        )
    if filtro.somente_desocupados:
        consulta = consulta.where(Lote.ocupado.is_(False))
    if filtro.dias_ate_praca_max is not None:
        limite = agora + timedelta(days=filtro.dias_ate_praca_max)
        consulta = consulta.where(
            Lote.eventos.any(
                and_(
                    EventoCalendario.data_hora >= agora,
                    EventoCalendario.data_hora <= limite,
                )
            )
        )

    # Cidade, bairro, texto e "sem onus" comparam sem acento -- o usuario digita
    # "macejo"/"maceio" e o banco tem "Maceió". Feito em Python porque SQLite nao
    # tem unaccent; em Postgres isso vira um indice funcional (ver docs).
    return consulta


def filtrar_em_memoria(lotes: list[Lote], filtro: FiltroLotes) -> list[Lote]:
    """Aplica os criterios que dependem de normalizacao de texto."""
    resultado = lotes
    if filtro.cidades:
        alvos = {normalizar_texto(c) for c in filtro.cidades}
        resultado = [lo for lo in resultado if normalizar_texto(lo.cidade) in alvos]
    if filtro.bairros:
        alvos = {normalizar_texto(b) for b in filtro.bairros}
        resultado = [lo for lo in resultado if normalizar_texto(lo.bairro) in alvos]
    if filtro.sem_onus:
        resultado = [lo for lo in resultado if not (lo.onus or [])]
    if filtro.texto:
        termos = [t for t in normalizar_texto(filtro.texto).split() if t]
        def casa(lote: Lote) -> bool:
            corpo = normalizar_texto(
                " ".join(
                    p or ""
                    for p in (
                        lote.titulo, lote.descricao, lote.cidade, lote.bairro,
                        lote.endereco, lote.marca, lote.modelo, lote.numero_processo,
                    )
                )
            )
            return all(t in corpo for t in termos)

        resultado = [lo for lo in resultado if casa(lo)]
    return resultado


def ordenar(lotes: list[Lote], chave: str, agora: datetime | None = None) -> list[Lote]:
    agora = agora or datetime.now(UTC)

    def score_de(lote: Lote) -> float:
        return lote.score.total if lote.score else -1.0

    def desconto_de(lote: Lote) -> float:
        return (lote.score.desconto_destaque if lote.score else None) or -1.0

    def proxima_praca(lote: Lote) -> datetime:
        futuros = [e.data_hora for e in lote.eventos if e.data_hora and e.data_hora >= agora]
        return min(futuros) if futuros else datetime.max.replace(tzinfo=UTC)

    def valor_de(lote: Lote) -> Decimal:
        return lote.valor_minimo_segunda or lote.valor_minimo_primeira or Decimal(10**12)

    match chave:
        case "desconto":
            return sorted(lotes, key=desconto_de, reverse=True)
        case "praca":
            return sorted(lotes, key=proxima_praca)
        case "valor":
            return sorted(lotes, key=valor_de)
        case "recente":
            return sorted(lotes, key=lambda lo: lo.coletado_em, reverse=True)
        case _:
            return sorted(lotes, key=score_de, reverse=True)


def buscar(sessao, filtro: FiltroLotes, agora: datetime | None = None) -> tuple[list[Lote], int]:
    """Devolve (pagina de lotes, total encontrado)."""
    lotes = list(sessao.scalars(construir(filtro, agora)).unique())
    lotes = filtrar_em_memoria(lotes, filtro)
    total = len(lotes)
    lotes = ordenar(lotes, filtro.ordenar, agora)
    inicio = max(0, (filtro.pagina - 1) * filtro.tamanho)
    return lotes[inicio : inicio + filtro.tamanho], total
