"""Geracao e sincronizacao de eventos de calendario (secao 9).

O ponto delicado: remarcacao e suspensao sao EVENTOS, nao sobrescritas. Quando a
data de uma praca muda, gravamos o historico antes de mudar o registro, de modo
que o sistema consegue dizer "essa praca foi adiada de 10/11 para 24/11" -- que e
exatamente o que o usuario com lembrete marcado precisa ouvir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.orm import Session

from radar.config import Settings, get_settings
from radar.enums import StatusEvento, StatusLote, TipoEvento
from radar.models import EventoCalendario, EventoHistorico, Lote, Praca

logger = logging.getLogger(__name__)

TIPO_POR_ORDEM = {1: TipoEvento.PRACA_PRIMEIRA, 2: TipoEvento.PRACA_SEGUNDA}
ROTULO_POR_TIPO = {
    TipoEvento.PRACA_PRIMEIRA: "1ª praça",
    TipoEvento.PRACA_SEGUNDA: "2ª praça",
    TipoEvento.PRACA_UNICA: "Praça única",
    TipoEvento.PRAZO_HABILITACAO: "Prazo de habilitação",
    TipoEvento.PRAZO_CAUCAO: "Prazo de caução",
    TipoEvento.PRAZO_IMPUGNACAO: "Prazo de impugnação",
    TipoEvento.VISITACAO: "Visitação",
}

_STATUS_LOTE_PARA_EVENTO = {
    StatusLote.SUSPENSO: StatusEvento.SUSPENSO,
    StatusLote.CANCELADO: StatusEvento.CANCELADO,
    StatusLote.ARREMATADO: StatusEvento.REALIZADO,
    StatusLote.DESERTO: StatusEvento.REALIZADO,
    StatusLote.ENCERRADO: StatusEvento.REALIZADO,
}


@dataclass(slots=True)
class MudancaEvento:
    tipo: TipoEvento
    motivo: str
    data_anterior: str | None = None
    data_nova: str | None = None


def sincronizar_eventos(
    sessao: Session, lote: Lote, settings: Settings | None = None
) -> list[MudancaEvento]:
    """(Re)gera os eventos do lote, preservando historico. Idempotente."""
    settings = settings or get_settings()
    existentes = {e.tipo: e for e in lote.eventos}
    mudancas: list[MudancaEvento] = []
    desejados: dict[TipoEvento, tuple[object, Praca | None, bool]] = {}

    pracas = sorted(lote.leilao.pracas, key=lambda p: p.ordem) if lote.leilao else []
    com_data = [p for p in pracas if p.data_hora is not None]

    for praca in com_data:
        if len(com_data) == 1 and praca.ordem == 1 and len(pracas) == 1:
            tipo = TipoEvento.PRACA_UNICA
        else:
            tipo = TIPO_POR_ORDEM.get(praca.ordem)
        if tipo is None:
            continue
        desejados[tipo] = (praca.data_hora, praca, False)

    # Prazo de habilitacao: se o edital nao disser, estimamos e marcamos como tal.
    primeira = next((p for p in com_data if p.ordem == min(x.ordem for x in com_data)), None)
    if primeira is not None:
        limite = primeira.data_hora - timedelta(days=settings.prazo_habilitacao_dias_antes)
        desejados[TipoEvento.PRAZO_HABILITACAO] = (limite, primeira, True)

    status_alvo = _STATUS_LOTE_PARA_EVENTO.get(lote.status, StatusEvento.CONFIRMADO)

    for tipo, (data, praca, estimado) in desejados.items():
        evento = existentes.pop(tipo, None)
        rotulo = ROTULO_POR_TIPO[tipo]
        titulo = f"{rotulo} — {lote.titulo}"[:300]

        if evento is None:
            sessao.add(
                EventoCalendario(
                    lote_id=lote.id,
                    lote=lote,
                    praca_id=praca.id if praca else None,
                    tipo=tipo,
                    titulo=titulo,
                    data_hora=data,
                    status=status_alvo,
                    estimado=estimado,
                    lembretes_horas=list(settings.lembretes_padrao_horas),
                )
            )
            mudancas.append(
                MudancaEvento(tipo=tipo, motivo="evento criado", data_nova=str(data))
            )
            continue

        if evento.data_hora != data:
            sessao.add(
                EventoHistorico(
                    evento=evento,
                    data_hora_anterior=evento.data_hora,
                    data_hora_nova=data,
                    status_anterior=str(evento.status),
                    status_novo=str(StatusEvento.REMARCADO),
                    motivo="nova data detectada na coleta",
                )
            )
            mudancas.append(
                MudancaEvento(
                    tipo=tipo,
                    motivo="remarcado",
                    data_anterior=str(evento.data_hora),
                    data_nova=str(data),
                )
            )
            evento.data_hora = data
            evento.status = StatusEvento.REMARCADO
        elif evento.status != status_alvo and status_alvo != StatusEvento.CONFIRMADO:
            sessao.add(
                EventoHistorico(
                    evento=evento,
                    data_hora_anterior=evento.data_hora,
                    data_hora_nova=evento.data_hora,
                    status_anterior=str(evento.status),
                    status_novo=str(status_alvo),
                    motivo=f"lote passou a {lote.status}",
                )
            )
            mudancas.append(
                MudancaEvento(tipo=tipo, motivo=f"status -> {status_alvo}")
            )
            evento.status = status_alvo

        evento.titulo = titulo
        evento.estimado = estimado

    # Eventos que nao sao mais desejados (praca removida do edital): cancelamos
    # em vez de apagar, para nao sumir do historico de quem tinha lembrete.
    for tipo, evento in existentes.items():
        if evento.status is StatusEvento.CANCELADO:
            continue
        sessao.add(
            EventoHistorico(
                evento=evento,
                data_hora_anterior=evento.data_hora,
                data_hora_nova=evento.data_hora,
                status_anterior=str(evento.status),
                status_novo=str(StatusEvento.CANCELADO),
                motivo="praça deixou de constar na fonte",
            )
        )
        evento.status = StatusEvento.CANCELADO
        mudancas.append(MudancaEvento(tipo=tipo, motivo="cancelado"))

    return mudancas
