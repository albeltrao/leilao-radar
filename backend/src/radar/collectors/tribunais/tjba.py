"""TJBA -- Bahia (secao 4.1, estendida para o quarto estado).

ATENCAO -- URLs candidatas. A especificacao original cobria AL, SE e PE e trazia
os caminhos exatos de cada portal. Para a Bahia os caminhos abaixo sao palpites
informados a partir do dominio do tribunal, NAO endereços confirmados.

O que fazer antes de ligar em producao:

    radar fontes validar --fonte tjba-leiloeiros-credenciados
    radar fontes validar --fonte tjba-leiloes-judiciais

Se a URL nao responder, corrija aqui e revalide. Enquanto `validado_ao_vivo`
for False, as duas fontes ficam fora da coleta automatica -- o sistema nao vai
fingir que cobre a Bahia antes de alguem conferir.
"""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.collectors.editais import ColetorEditaisTribunal
from radar.enums import TipoFonte

META_LEILOEIROS = MetadadosFonte(
    slug="tjba-leiloeiros-credenciados",
    nome="TJBA/CGJ - Leiloeiros Credenciados",
    tipo=TipoFonte.TRIBUNAL,
    uf="BA",
    url_alvo="https://www.tjba.jus.br/corregedoria/leiloeiros",
    periodicidade_horas=24,
    descricao=(
        "Leiloeiros credenciados pela Corregedoria da Bahia. "
        "URL CANDIDATA: confirmar o caminho na validacao."
    ),
)

META_LEILOES = MetadadosFonte(
    slug="tjba-leiloes-judiciais",
    nome="TJBA - Leiloes Judiciais",
    tipo=TipoFonte.TRIBUNAL,
    uf="BA",
    url_alvo="https://www.tjba.jus.br/portal/leiloes-judiciais",
    periodicidade_horas=24,
    descricao=(
        "Editais de leilao judicial publicados pelo TJBA. "
        "URL CANDIDATA: confirmar o caminho na validacao."
    ),
)

CONECTOR_LEILOEIROS = registrar(
    ColetorCadastroLeiloeiros(
        meta=META_LEILOEIROS,
        urls=[
            META_LEILOEIROS.url_alvo,
            "https://www.tjba.jus.br/corregedoria/leiloeiros-credenciados",
        ],
        junta=None,
        uf="BA",
    )
)

CONECTOR_LEILOES = registrar(
    ColetorEditaisTribunal(
        meta=META_LEILOES,
        urls=[META_LEILOES.url_alvo],
        tribunal_sigla="TJBA",
        uf="BA",
    )
)
