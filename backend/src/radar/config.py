"""Configuracao da aplicacao, carregada de variaveis de ambiente / arquivo .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RADAR_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Banco ---------------------------------------------------------------
    database_url: str = Field(
        default=f"sqlite:///{REPO_ROOT / 'radar.db'}",
        description="SQLite por padrao; em producao use postgresql+psycopg://...",
    )
    sql_echo: bool = False

    # --- Coleta --------------------------------------------------------------
    user_agent: str = Field(
        default=(
            "RadarLeilaoBot/0.1 (+https://github.com/albeltrao/leilao-radar; "
            "contato: radar-leilao@example.org)"
        ),
        description=(
            "Secao 4.3 do spec: o coletor precisa se identificar. Troque o contato "
            "por um endereco real antes de rodar contra sites de terceiros."
        ),
    )
    respeitar_robots: bool = Field(
        default=True,
        description="Nunca desligue em producao. Existe apenas para testes offline.",
    )
    delay_minimo_por_host_s: float = 1.5
    timeout_http_s: float = 30.0
    max_tentativas_http: int = 3
    max_paginas_por_coleta: int = 50

    # --- Arquivamento de HTML bruto (secao 5: auditoria / depuracao) ---------
    diretorio_raw: Path = Field(default=REPO_ROOT / "data" / "raw")
    retencao_raw_dias: int = 30
    diretorio_documentos: Path = Field(default=REPO_ROOT / "data" / "docs")

    # --- Fila de ingestao ----------------------------------------------------
    fila_backend: str = Field(default="memoria", description="memoria | redis")
    redis_url: str = "redis://localhost:6379/0"

    # --- Extracao documental -------------------------------------------------
    ocr_habilitado: bool = False
    ocr_idioma: str = "por"
    ocr_minimo_caracteres_pagina: int = Field(
        default=120,
        description="Abaixo disso a pagina e tratada como digitalizada e vai para OCR.",
    )
    llm_habilitado: bool = False
    llm_modelo: str = "claude-sonnet-5"
    llm_api_key: str | None = None
    llm_max_caracteres: int = 120_000

    # --- Mercado -------------------------------------------------------------
    fipe_provider: str = Field(default="espelho", description="espelho | fipe_api_br")
    fipe_api_base: str = "https://fipe.api.br/api/v1"
    fipe_cache_dias: int = 30

    # --- Calendario / alertas ------------------------------------------------
    lembretes_padrao_horas: tuple[int, ...] = (72, 24, 1)
    prazo_habilitacao_dias_antes: int = Field(
        default=3,
        description=(
            "Fallback quando o edital nao declara o prazo. E uma estimativa e a API "
            "marca o evento como 'estimado'."
        ),
    )
    email_backend: str = Field(default="console", description="console | arquivo | smtp")
    email_remetente: str = "radar-leilao@example.org"
    smtp_host: str = "localhost"
    smtp_porta: int = 25
    smtp_usuario: str | None = None
    smtp_senha: str | None = None
    smtp_tls: bool = True

    # --- API -----------------------------------------------------------------
    api_titulo: str = "Radar Leilao API"
    cors_origens: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    diretorio_frontend: Path = Field(default=REPO_ROOT / "frontend" / "dist")
    sessao_duracao_horas: int = 24 * 14

    # --- DataJud (CNJ) -------------------------------------------------------
    datajud_api_key: str | None = Field(
        default=None,
        description=(
            "Chave publica do DataJud. Sem ela o enriquecimento processual e pulado "
            "(o resto do pipeline continua funcionando)."
        ),
    )
    datajud_base_url: str = "https://api-publica.datajud.cnj.jus.br"

    def garantir_diretorios(self) -> None:
        self.diretorio_raw.mkdir(parents=True, exist_ok=True)
        self.diretorio_documentos.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
