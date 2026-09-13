"""TJSE -- Leilao judicial e leiloeiros credenciados (secao 4.1)."""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.collectors.editais import ColetorEditaisTribunal
from radar.enums import TipoFonte

META_LEILOEIROS = MetadadosFonte(
    slug="tjse-leiloeiros-credenciados",
    nome="TJSE - Leiloeiros Credenciados",
    tipo=TipoFonte.TRIBUNAL,
    uf="SE",
    url_alvo="https://www.tjse.jus.br/portal/servicos/judiciais/leiloeiros-credenciados",
    periodicidade_horas=24,
    descricao="Leiloeiros credenciados pelo Tribunal de Justica de Sergipe.",
)

META_LEILOES = MetadadosFonte(
    slug="tjse-leilao-judicial",
    nome="TJSE - Leilao Judicial",
    tipo=TipoFonte.TRIBUNAL,
    uf="SE",
    url_alvo="https://www.tjse.jus.br/portal/servicos/judiciais/leilao-judicial",
    periodicidade_horas=24,
    descricao="Editais de leilao judicial publicados pelo TJSE, com anexos em PDF.",
)

CONECTOR_LEILOEIROS = registrar(
    ColetorCadastroLeiloeiros(
        meta=META_LEILOEIROS, urls=[META_LEILOEIROS.url_alvo], junta=None, uf="SE"
    )
)

CONECTOR_LEILOES = registrar(
    ColetorEditaisTribunal(
        meta=META_LEILOES, urls=[META_LEILOES.url_alvo], tribunal_sigla="TJSE", uf="SE"
    )
)
