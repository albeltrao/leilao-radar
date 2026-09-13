"""Autenticacao simples (secao 2: "interface web com autenticacao simples").

Senha com scrypt da biblioteca padrao -- sem dependencia extra e com parametros
explicitos, em vez de um default escondido. Sessao por token opaco guardado como
hash: vazar o banco nao entrega token utilizavel.

Nao e um sistema de identidade completo: nao ha 2FA, recuperacao de senha nem
politica de bloqueio. Para producao com dado sensivel, troque por um provedor
(a fronteira e a funcao ``usuario_da_requisicao``).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.config import Settings, get_settings
from radar.models import Sessao, Usuario

# Parametros scrypt: ~16 MB de memoria por verificacao. Custo alto o bastante
# para forca bruta e baixo o bastante para uma API sincrona.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
TAMANHO_SAL = 16
TAMANHO_CHAVE = 32


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(TAMANHO_SAL)
    derivada = hashlib.scrypt(
        senha.encode("utf-8"), salt=sal, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=TAMANHO_CHAVE,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${sal.hex()}${derivada.hex()}"


def conferir_senha(senha: str, armazenado: str) -> bool:
    try:
        algoritmo, n, r, p, sal_hex, esperado_hex = armazenado.split("$")
        if algoritmo != "scrypt":
            return False
        derivada = hashlib.scrypt(
            senha.encode("utf-8"), salt=bytes.fromhex(sal_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(esperado_hex)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derivada.hex(), esperado_hex)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def criar_sessao(
    sessao: Session, usuario: Usuario, settings: Settings | None = None
) -> str:
    """Cria a sessao e devolve o token em claro (unica vez que ele existe)."""
    settings = settings or get_settings()
    token = secrets.token_urlsafe(32)
    sessao.add(
        Sessao(
            usuario_id=usuario.id,
            token_hash=_hash_token(token),
            expira_em=datetime.now(UTC) + timedelta(hours=settings.sessao_duracao_horas),
        )
    )
    sessao.flush()
    return token


def usuario_do_token(sessao: Session, token: str | None) -> Usuario | None:
    if not token:
        return None
    registro = sessao.scalar(
        select(Sessao).where(Sessao.token_hash == _hash_token(token))
    )
    if registro is None:
        return None
    expira = registro.expira_em
    if expira.tzinfo is None:
        expira = expira.replace(tzinfo=UTC)
    if expira < datetime.now(UTC):
        sessao.delete(registro)
        return None
    return registro.usuario if registro.usuario.ativo else None


def encerrar_sessao(sessao: Session, token: str) -> bool:
    registro = sessao.scalar(select(Sessao).where(Sessao.token_hash == _hash_token(token)))
    if registro is None:
        return False
    sessao.delete(registro)
    return True


def registrar_usuario(
    sessao: Session, email: str, senha: str, nome: str | None = None
) -> Usuario:
    usuario = Usuario(
        email=email.strip().lower(), nome=nome, senha_hash=hash_senha(senha)
    )
    sessao.add(usuario)
    sessao.flush()
    return usuario


def autenticar(sessao: Session, email: str, senha: str) -> Usuario | None:
    usuario = sessao.scalar(select(Usuario).where(Usuario.email == email.strip().lower()))
    if usuario is None:
        # Gasta o mesmo tempo de um usuario existente, para nao vazar por timing
        # quais e-mails estao cadastrados.
        hash_senha(senha)
        return None
    if not conferir_senha(senha, usuario.senha_hash):
        return None
    return usuario if usuario.ativo else None
