"""Fabrica da aplicacao FastAPI."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from radar import __version__
from radar.api.rotas import conta, publico
from radar.collectors.base import carregar_todos
from radar.config import Settings, get_settings
from radar.db import criar_schema

logger = logging.getLogger(__name__)

DESCRICAO = """
API do **Radar Leilão** — leilões judiciais de Alagoas, Sergipe e Pernambuco.

O sistema organiza e enriquece informação pública. Ele **não** presta assessoria
jurídica nem recomendação de investimento.

Toda resposta que contém valor derivado traz junto a sua procedência:

* campos extraídos de edital levam `confianca`, `metodo` e `evidencia`
  (o trecho literal do documento);
* análises de mercado levam `metodologia`, `data_referencia_fonte` e `avisos`;
* o score traz a lista de `componentes`, cada um com a sua explicação.
"""


def criar_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    carregar_todos()

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
        settings.garantir_diretorios()
        criar_schema(settings)
        yield

    app = FastAPI(
        title=settings.api_titulo,
        version=__version__,
        description=DESCRICAO,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=ciclo_de_vida,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origens),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(publico)
    app.include_router(conta)

    _montar_frontend(app, settings)
    return app


def _montar_frontend(app: FastAPI, settings: Settings) -> None:
    """Serve o build do frontend, quando existir.

    Em desenvolvimento o Vite roda em outra porta e isto simplesmente nao monta.
    """
    dist = settings.diretorio_frontend
    if not dist.exists():
        logger.info("frontend nao compilado em %s; servindo apenas a API", dist)
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{caminho:path}", include_in_schema=False)
    def spa(caminho: str) -> FileResponse:
        # Rota de SPA: qualquer caminho que nao seja da API devolve o index, para
        # que o roteador do React resolva no cliente.
        alvo = dist / caminho
        if caminho and alvo.is_file():
            return FileResponse(alvo)
        return FileResponse(dist / "index.html")


app = criar_app()
