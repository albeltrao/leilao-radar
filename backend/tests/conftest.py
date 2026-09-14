"""Fixtures compartilhadas. Todos os testes rodam offline."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def carregar_html(nome: str) -> str:
    return (FIXTURES / "html" / nome).read_text(encoding="utf-8")


@pytest.fixture(scope="session", autouse=True)
def _ambiente_isolado(tmp_path_factory):
    """Isola banco e diretorios de dados dos testes do ambiente real."""
    raiz = tmp_path_factory.mktemp("radar")
    os.environ["RADAR_DATABASE_URL"] = f"sqlite:///{raiz / 'teste.db'}"
    os.environ["RADAR_DIRETORIO_RAW"] = str(raiz / "raw")
    os.environ["RADAR_DIRETORIO_DOCUMENTOS"] = str(raiz / "docs")
    os.environ["RADAR_DELAY_MINIMO_POR_HOST_S"] = "0"
    os.environ["RADAR_EMAIL_BACKEND"] = "memoria"
    from radar.config import get_settings

    get_settings.cache_clear()
    yield raiz


@pytest.fixture
def settings(_ambiente_isolado):
    from radar.config import get_settings

    return get_settings()


@pytest.fixture
def sessao_db(settings, tmp_path, monkeypatch):
    """Banco limpo por teste."""
    from radar import db as db_mod

    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'caso.db'}")
    db_mod.resetar_estado_global()
    db_mod.criar_schema(settings)
    with db_mod.sessao() as s:
        yield s
    db_mod.resetar_estado_global()


@pytest.fixture
def cliente_api(sessao_db, settings):
    """API apontando para o banco do teste, SEM dados de demonstracao.

    Diferente do `cliente` de test_api.py, que popula o seed: aqui o teste
    monta o cenario que quer medir, sem os 10 lotes ficticios no meio.
    """
    from fastapi.testclient import TestClient

    from radar.api.app import criar_app

    with TestClient(criar_app(settings)) as cliente:
        yield cliente
