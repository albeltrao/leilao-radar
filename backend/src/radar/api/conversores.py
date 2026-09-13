"""Conversao ORM -> schema, com os campos derivados que a UI precisa."""

from __future__ import annotations

from datetime import UTC, datetime

from radar.api import schemas
from radar.enums import TipoEvento
from radar.models import Lote

TIPOS_PRACA = {
    TipoEvento.PRACA_PRIMEIRA: 1,
    TipoEvento.PRACA_SEGUNDA: 2,
    TipoEvento.PRACA_UNICA: 1,
}


def proxima_praca(lote: Lote, agora: datetime | None = None):
    """Data e ordem da proxima praca. Prazo de habilitacao nao conta como praca."""
    agora = agora or datetime.now(UTC)
    candidatos = [
        (e.data_hora, TIPOS_PRACA[e.tipo])
        for e in lote.eventos
        if e.data_hora and e.tipo in TIPOS_PRACA
    ]
    futuros = [c for c in candidatos if c[0] >= agora]
    if futuros:
        return min(futuros, key=lambda c: c[0])
    if candidatos:
        return max(candidatos, key=lambda c: c[0])
    return (None, None)


def _valor_campo(campo):
    for atributo in ("valor_numerico", "valor_data", "valor_booleano", "valor_texto"):
        valor = getattr(campo, atributo)
        if valor is not None:
            return valor
    return None


def para_resumo(lote: Lote, agora: datetime | None = None) -> schemas.LoteResumo:
    data, ordem = proxima_praca(lote, agora)
    leiloeiro = lote.leilao.leiloeiro if lote.leilao else None
    return schemas.LoteResumo(
        **{
            campo: getattr(lote, campo)
            for campo in schemas.LoteResumo.model_fields
            if campo not in {"score", "proxima_praca", "proxima_praca_ordem", "leiloeiro"}
        },
        score=schemas.ScoreResposta.model_validate(lote.score) if lote.score else None,
        proxima_praca=data,
        proxima_praca_ordem=ordem,
        leiloeiro=(
            schemas.LeiloeiroResumo.model_validate(leiloeiro) if leiloeiro else None
        ),
    )


def para_detalhe(lote: Lote, agora: datetime | None = None) -> schemas.LoteDetalhe:
    resumo = para_resumo(lote, agora)
    campos = [
        schemas.CampoResposta(
            nome=c.nome,
            valor=_valor_campo(c),
            confianca=c.confianca,
            metodo=str(c.metodo),
            evidencia=c.evidencia,
            revisao_necessaria=c.revisao_necessaria,
        )
        for c in sorted(lote.campos, key=lambda c: c.nome)
    ]
    return schemas.LoteDetalhe(
        **resumo.model_dump(),
        descricao=lote.descricao,
        endereco=lote.endereco,
        cep=lote.cep,
        matricula=lote.matricula,
        cartorio=lote.cartorio,
        area_total_m2=lote.area_total_m2,
        area_privativa_m2=lote.area_privativa_m2,
        quartos=lote.quartos,
        vagas=lote.vagas,
        marca=lote.marca,
        modelo=lote.modelo,
        ano_fabricacao=lote.ano_fabricacao,
        ano_modelo=lote.ano_modelo,
        combustivel=lote.combustivel,
        placa_parcial=lote.placa_parcial,
        comissao_leiloeiro_percentual=lote.comissao_leiloeiro_percentual,
        formas_pagamento=lote.formas_pagamento,
        debitos=lote.debitos,
        fontes_secundarias=lote.fontes_secundarias,
        coletado_em=lote.coletado_em,
        visto_por_ultimo_em=lote.visto_por_ultimo_em,
        pracas=[
            schemas.PracaResposta.model_validate(p)
            for p in (lote.leilao.pracas if lote.leilao else [])
        ],
        eventos=[schemas.EventoResposta.model_validate(e) for e in lote.eventos],
        documentos=[schemas.DocumentoResposta.model_validate(d) for d in lote.documentos],
        campos=campos,
        analises=[schemas.AnaliseResposta.model_validate(a) for a in lote.analises],
    )
