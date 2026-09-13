"""TJAL -- Corregedoria Geral da Justica de Alagoas (secao 4.1).

O TJAL nao expoe um portal proprio de hasta publica eletronica: o que ha e o
Banco de Leiloeiros e Corretores Publicos da CGJ, que diz *quem* pode leiloar.
O *que* esta sendo leiloado vem dos sites dos leiloeiros (secao 4.3).

Se a Corregedoria passar a publicar um portal de leiloes, registre-o como um
``ColetorEditaisTribunal`` aqui -- o pipeline ja esta preparado.
"""

from __future__ import annotations

from radar.collectors.base import MetadadosFonte, registrar
from radar.collectors.cadastro import ColetorCadastroLeiloeiros
from radar.enums import TipoFonte

META_LEILOEIROS = MetadadosFonte(
    slug="tjal-banco-leiloeiros",
    nome="TJAL/CGJ - Banco de Leiloeiros e Corretores Publicos",
    tipo=TipoFonte.TRIBUNAL,
    uf="AL",
    url_alvo="https://cgj.tjal.jus.br/?pag=bancosPeritos/bancosLeiloeiros",
    periodicidade_horas=24,
    descricao=(
        "Leiloeiros credenciados pela Corregedoria de Alagoas. Cruzado com a JUCEAL "
        "para montar o cadastro mestre e a lista de sites a monitorar."
    ),
)

CONECTOR_LEILOEIROS = registrar(
    ColetorCadastroLeiloeiros(
        meta=META_LEILOEIROS,
        urls=[META_LEILOEIROS.url_alvo],
        junta=None,  # credenciamento do tribunal, nao registro de junta
        uf="AL",
    )
)
