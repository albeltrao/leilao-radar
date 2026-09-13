"""Envio de e-mail com backends trocaveis.

console (padrao em dev), memoria (testes), arquivo (inspecao manual do HTML) e
smtp (producao). Nenhum teste da suite manda e-mail de verdade.
"""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

from radar.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Mensagem:
    para: str
    assunto: str
    texto: str
    html: str | None = None
    criada_em: datetime = field(default_factory=lambda: datetime.now(UTC))

    def para_email(self, remetente: str) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = remetente
        msg["To"] = self.para
        msg["Subject"] = self.assunto
        msg.set_content(self.texto)
        if self.html:
            msg.add_alternative(self.html, subtype="html")
        return msg


class BackendEmail(ABC):
    @abstractmethod
    def enviar(self, mensagem: Mensagem) -> None: ...


class BackendConsole(BackendEmail):
    def enviar(self, mensagem: Mensagem) -> None:
        logger.info(
            "[e-mail simulado] para=%s assunto=%s\n%s",
            mensagem.para, mensagem.assunto, mensagem.texto,
        )


class BackendMemoria(BackendEmail):
    """Guarda o que seria enviado. Usado pelos testes."""

    def __init__(self) -> None:
        self.enviadas: list[Mensagem] = []

    def enviar(self, mensagem: Mensagem) -> None:
        self.enviadas.append(mensagem)


class BackendArquivo(BackendEmail):
    def __init__(self, diretorio: Path) -> None:
        self.diretorio = diretorio
        diretorio.mkdir(parents=True, exist_ok=True)

    def enviar(self, mensagem: Mensagem) -> None:
        carimbo = mensagem.criada_em.strftime("%Y%m%d-%H%M%S-%f")
        destino = self.diretorio / f"{carimbo}.html"
        destino.write_text(mensagem.html or mensagem.texto, encoding="utf-8")
        logger.info("e-mail gravado em %s", destino)


class BackendSMTP(BackendEmail):  # pragma: no cover - exige servidor
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def enviar(self, mensagem: Mensagem) -> None:
        s = self.settings
        with smtplib.SMTP(s.smtp_host, s.smtp_porta, timeout=30) as servidor:
            if s.smtp_tls:
                servidor.starttls()
            if s.smtp_usuario:
                servidor.login(s.smtp_usuario, s.smtp_senha or "")
            servidor.send_message(mensagem.para_email(s.email_remetente))


def criar_backend(settings: Settings | None = None) -> BackendEmail:
    settings = settings or get_settings()
    match settings.email_backend:
        case "memoria":
            return BackendMemoria()
        case "arquivo":
            return BackendArquivo(settings.diretorio_documentos.parent / "emails")
        case "smtp":  # pragma: no cover
            return BackendSMTP(settings)
        case _:
            return BackendConsole()
