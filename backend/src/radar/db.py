"""Engine, sessao e criacao de schema.

Usamos ``metadata.create_all`` em vez de migracoes versionadas nesta fase: o
schema ainda muda a cada conector novo. Ver docs/adr/0002-sem-alembic-na-v0.md
para quando isso deve virar Alembic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from radar.config import Settings, get_settings
from radar.models import Base

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _criar_engine(settings: Settings) -> Engine:
    url = settings.database_url
    kwargs: dict = {"echo": settings.sql_echo, "future": True}
    if url.startswith("sqlite"):
        # check_same_thread=False porque o worker de ingestao e a API podem
        # compartilhar o arquivo; o pool default do SQLite ja serializa escritas.
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

    return engine


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine
    if _engine is None:
        _engine = _criar_engine(settings or get_settings())
    return _engine


def get_sessionmaker(settings: Settings | None = None) -> sessionmaker[Session]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(
            bind=get_engine(settings), expire_on_commit=False, future=True
        )
    return _sessionmaker


@contextmanager
def sessao() -> Iterator[Session]:
    """Sessao transacional: commit no sucesso, rollback em qualquer excecao."""
    s = get_sessionmaker()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


class SchemaDesatualizado(RuntimeError):
    """O banco existe, mas nao tem as colunas que o codigo atual espera."""


def criar_schema(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    _conferir_colunas(engine)


def _conferir_colunas(engine: Engine) -> None:
    """Detecta banco antigo depois de um campo novo no modelo.

    ``create_all`` cria tabela que falta, mas NAO acrescenta coluna a tabela que
    ja existe. Sem esta checagem, um banco criado por uma versao anterior falha
    la na frente com "no such column: lote.natureza_bem", no meio de uma consulta
    da API -- longe da causa e sem dizer o que fazer. Enquanto nao houver Alembic
    (ver docs/adr/0002), o conserto e recriar o banco, e a mensagem diz isso.
    """
    inspetor = inspect(engine)
    faltando: list[str] = []
    for tabela in Base.metadata.sorted_tables:
        if not inspetor.has_table(tabela.name):
            continue
        existentes = {c["name"] for c in inspetor.get_columns(tabela.name)}
        faltando += [
            f"{tabela.name}.{coluna.name}"
            for coluna in tabela.columns
            if coluna.name not in existentes
        ]
    if faltando:
        raise SchemaDesatualizado(
            "o banco foi criado por uma versao anterior e nao tem estas colunas: "
            + ", ".join(sorted(faltando))
            + ". Ainda nao ha migracao versionada neste projeto: apague o banco "
            "(`make limpar`) e recrie com `radar criar-schema` -- ou, se os dados "
            "importam, exporte antes."
        )


def resetar_estado_global() -> None:
    """Descarta engine/sessionmaker em cache. Usado pelos testes e pela CLI."""
    global _engine, _sessionmaker
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _sessionmaker = None
