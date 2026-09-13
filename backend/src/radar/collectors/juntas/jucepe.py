"""JUCEPE -- Leiloeiros publicos oficiais de Pernambuco (secao 4.2)."""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.enums import JuntaComercial, TipoFonte

META = MetadadosFonte(
    slug="jucepe-leiloeiros",
    nome="JUCEPE - Leiloeiros",
    tipo=TipoFonte.JUNTA_COMERCIAL,
    uf="PE",
    url_alvo="https://portal.jucepe.pe.gov.br/leiloeiros",
    periodicidade_horas=24,
    descricao="Cadastro mestre de leiloeiros publicos oficiais registrados em Pernambuco.",
)

CONECTOR = registrar(
    ColetorCadastroLeiloeiros(
        meta=META,
        urls=[META.url_alvo],
        junta=JuntaComercial.JUCEPE,
        uf="PE",
    )
)
