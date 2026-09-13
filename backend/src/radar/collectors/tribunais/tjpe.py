"""TJPE -- Leiloes judiciais da Corregedoria Geral (secao 4.1).

O TJPE organiza a publicacao por circunscricao judiciaria, entao esta e a unica
fonte de tribunal que precisa de paginacao.
"""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.editais import ColetorEditaisTribunal
from radar.enums import TipoFonte

META = MetadadosFonte(
    slug="tjpe-leiloes-judiciais",
    nome="TJPE/CGJ - Leiloes Judiciais",
    tipo=TipoFonte.TRIBUNAL,
    uf="PE",
    url_alvo="https://portal.tjpe.jus.br/web/corregedoria/leiloes-judiciais/leiloes",
    periodicidade_horas=24,
    descricao=(
        "Leiloes judiciais publicados por circunscricao judiciaria, com editais em PDF."
    ),
)

CONECTOR = registrar(
    ColetorEditaisTribunal(
        meta=META,
        urls=[META.url_alvo],
        tribunal_sigla="TJPE",
        uf="PE",
        paginacao="?p_r_p_pagina={n}",
        max_paginas=8,
    )
)
