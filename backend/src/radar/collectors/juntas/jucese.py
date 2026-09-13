"""JUCESE -- Leiloeiros publicos oficiais de Sergipe (secao 4.2).

A JUCESE publica tambem a escala de leiloeiros oficiais; ela e coletada da mesma
pagina porque aparece na mesma listagem.
"""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.enums import JuntaComercial, TipoFonte

META = MetadadosFonte(
    slug="jucese-leiloeiros",
    nome="JUCESE - Leiloeiros",
    tipo=TipoFonte.JUNTA_COMERCIAL,
    uf="SE",
    url_alvo="https://jucese.se.gov.br/leiloeiros/",
    periodicidade_horas=24,
    descricao="Cadastro mestre de leiloeiros publicos oficiais registrados em Sergipe.",
)

CONECTOR = registrar(
    ColetorCadastroLeiloeiros(
        meta=META,
        urls=[META.url_alvo],
        junta=JuntaComercial.JUCESE,
        uf="SE",
    )
)
