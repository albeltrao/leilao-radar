"""JUCEB -- Leiloeiros publicos oficiais da Bahia (secao 4.2).

ATENCAO -- URL candidata. Diferente de JUCEAL, JUCESE e JUCEPE, cuja pagina de
leiloeiros foi indicada na especificacao do produto, o caminho exato da listagem
da JUCEB NAO foi confirmado. As URLs abaixo sao candidatas: o coletor tenta cada
uma e a validacao (`radar fontes validar --fonte juceb-leiloeiros`) e o momento
de descobrir qual responde -- ou de trocar pela correta.

Enquanto `validado_ao_vivo` for False a fonte fica fora da coleta automatica.
"""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.enums import JuntaComercial, TipoFonte

META = MetadadosFonte(
    slug="juceb-leiloeiros",
    nome="JUCEB - Leiloeiros",
    tipo=TipoFonte.JUNTA_COMERCIAL,
    uf="BA",
    url_alvo="https://www.juceb.ba.gov.br/leiloeiros",
    periodicidade_horas=24,
    descricao=(
        "Cadastro mestre de leiloeiros publicos oficiais registrados na Bahia. "
        "URL CANDIDATA: confirmar o caminho da listagem na validacao."
    ),
)

CONECTOR = registrar(
    ColetorCadastroLeiloeiros(
        meta=META,
        urls=[
            "https://www.juceb.ba.gov.br/leiloeiros",
            "https://www.juceb.ba.gov.br/servicos/leiloeiros",
        ],
        junta=JuntaComercial.JUCEB,
        uf="BA",
    )
)
