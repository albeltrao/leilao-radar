"""Casamento de alertas e disparo (secao 14: alertas por filtro salvo)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.alerts.email import BackendEmail, Mensagem, criar_backend
from radar.alerts.render import montar_html, montar_texto
from radar.config import Settings, get_settings
from radar.consultas import FiltroLotes, buscar
from radar.models import Alerta, AlertaEnvio, Lote

logger = logging.getLogger(__name__)

MAX_LOTES_POR_EMAIL = 20


@dataclass(slots=True)
class ResumoAlertas:
    alertas_avaliados: int = 0
    alertas_disparados: int = 0
    lotes_notificados: int = 0
    erros: list[str] = field(default_factory=list)


def lotes_novos(
    sessao: Session, alerta: Alerta, agora: datetime | None = None
) -> list[Lote]:
    """Lotes que casam com o filtro e que este alerta ainda nao notificou."""
    filtro = FiltroLotes.de_criterios(alerta.criterios)
    filtro.tamanho = 500
    filtro.pagina = 1
    candidatos, _ = buscar(sessao, filtro, agora)

    ja_enviados = set(
        sessao.scalars(
            select(AlertaEnvio.lote_id).where(AlertaEnvio.alerta_id == alerta.id)
        )
    )
    return [lote for lote in candidatos if lote.id not in ja_enviados]


def processar(
    sessao: Session,
    *,
    settings: Settings | None = None,
    backend: BackendEmail | None = None,
    agora: datetime | None = None,
    simular: bool = False,
) -> ResumoAlertas:
    settings = settings or get_settings()
    backend = backend or criar_backend(settings)
    agora = agora or datetime.now(UTC)
    base_url = settings.cors_origens[0] if settings.cors_origens else ""
    resumo = ResumoAlertas()

    for alerta in sessao.scalars(select(Alerta).where(Alerta.ativo.is_(True))):
        resumo.alertas_avaliados += 1
        try:
            novos = lotes_novos(sessao, alerta, agora)
        except Exception as exc:
            resumo.erros.append(f"alerta {alerta.id}: {exc}")
            logger.exception("falha ao avaliar alerta %s", alerta.id)
            continue
        if not novos:
            continue

        recorte = novos[:MAX_LOTES_POR_EMAIL]
        mensagem = Mensagem(
            para=alerta.usuario.email,
            assunto=_assunto(alerta, novos),
            texto=montar_texto(alerta, recorte, base_url),
            html=montar_html(alerta, recorte, base_url),
        )
        if simular:
            resumo.alertas_disparados += 1
            resumo.lotes_notificados += len(recorte)
            continue

        try:
            backend.enviar(mensagem)
        except Exception as exc:
            resumo.erros.append(f"envio do alerta {alerta.id}: {exc}")
            logger.exception("falha ao enviar alerta %s", alerta.id)
            continue

        # So marca como enviado depois que o envio deu certo -- se o SMTP cair,
        # o lote entra no proximo ciclo em vez de sumir para sempre.
        for lote in recorte:
            sessao.add(AlertaEnvio(alerta_id=alerta.id, lote_id=lote.id, enviado_em=agora))
        alerta.ultimo_envio_em = agora
        resumo.alertas_disparados += 1
        resumo.lotes_notificados += len(recorte)

    sessao.flush()
    return resumo


def _assunto(alerta: Alerta, lotes: list[Lote]) -> str:
    if len(lotes) == 1:
        return f"Radar Leilão · 1 novo lote em “{alerta.nome}”"
    return f"Radar Leilão · {len(lotes)} novos lotes em “{alerta.nome}”"
