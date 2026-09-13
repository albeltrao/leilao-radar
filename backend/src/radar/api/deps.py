"""Dependencias da API: sessao de banco e usuario autenticado."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from radar.api.auth import usuario_do_token
from radar.config import Settings, get_settings
from radar.db import get_sessionmaker
from radar.models import Usuario


def obter_sessao() -> Iterator[Session]:
    sessao = get_sessionmaker()()
    try:
        yield sessao
        sessao.commit()
    except Exception:
        sessao.rollback()
        raise
    finally:
        sessao.close()


def obter_settings() -> Settings:
    return get_settings()


SessaoDep = Annotated[Session, Depends(obter_sessao)]
SettingsDep = Annotated[Settings, Depends(obter_settings)]


def _token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    partes = authorization.split(None, 1)
    if len(partes) != 2 or partes[0].lower() != "bearer":
        return None
    return partes[1].strip()


def usuario_opcional(
    sessao: SessaoDep, authorization: Annotated[str | None, Header()] = None
) -> Usuario | None:
    return usuario_do_token(sessao, _token(authorization))


def usuario_obrigatorio(
    sessao: SessaoDep, authorization: Annotated[str | None, Header()] = None
) -> Usuario:
    usuario = usuario_do_token(sessao, _token(authorization))
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="autenticação necessária",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return usuario


UsuarioDep = Annotated[Usuario, Depends(usuario_obrigatorio)]
UsuarioOpcionalDep = Annotated[Usuario | None, Depends(usuario_opcional)]
