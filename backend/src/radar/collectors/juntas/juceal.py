"""JUCEAL -- Leiloeiros publicos oficiais de Alagoas (secao 4.2)."""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.enums import JuntaComercial, TipoFonte

META = MetadadosFonte(
    slug="juceal-leiloeiros",
    nome="JUCEAL - Leiloeiros",
    tipo=TipoFonte.JUNTA_COMERCIAL,
    uf="AL",
    url_alvo="https://www.juceal.al.gov.br/servicos/leiloeiros",
    periodicidade_horas=24,
    descricao="Cadastro mestre de leiloeiros publicos oficiais registrados em Alagoas.",
)

CONECTOR = registrar(
    ColetorCadastroLeiloeiros(
        meta=META,
        urls=[META.url_alvo],
        junta=JuntaComercial.JUCEAL,
        uf="AL",
    )
)
