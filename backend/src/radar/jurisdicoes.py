"""Tabela canônica das jurisdições cobertas pelo Radar.

Antes de existir, o par tribunal<->UF estava duplicado em três lugares
(`normalizacao.tribunal_do_cnj`, `normalizador.UF_POR_TRIBUNAL` e
`datajud.INDICES`), e o enum `UF` não era usado por ninguém. Acrescentar a
Bahia obrigaria a lembrar dos três — e esquecer um deles daria erro silencioso:
lote da Bahia entrando sem tribunal, ou entrando e não aparecendo no filtro.

Agora acrescentar um estado é acrescentar UMA linha aqui.

O código TR é o par de dígitos do número CNJ que identifica o tribunal dentro do
segmento 8 (justiça estadual), conforme a Resolução CNJ nº 65/2008.
"""

from __future__ import annotations

from dataclasses import dataclass

from radar.enums import UF


@dataclass(frozen=True, slots=True)
class Jurisdicao:
    sigla: str
    nome: str
    uf: UF
    codigo_tr: str
    indice_datajud: str
    url_portal: str
    url_leiloes: str | None = None


JURISDICOES: tuple[Jurisdicao, ...] = (
    Jurisdicao(
        sigla="TJAL",
        nome="Tribunal de Justiça de Alagoas",
        uf=UF.AL,
        codigo_tr="02",
        indice_datajud="api_publica_tjal",
        url_portal="https://www.tjal.jus.br",
    ),
    Jurisdicao(
        sigla="TJBA",
        nome="Tribunal de Justiça da Bahia",
        uf=UF.BA,
        codigo_tr="05",
        indice_datajud="api_publica_tjba",
        url_portal="https://www.tjba.jus.br",
    ),
    Jurisdicao(
        sigla="TJPE",
        nome="Tribunal de Justiça de Pernambuco",
        uf=UF.PE,
        codigo_tr="17",
        indice_datajud="api_publica_tjpe",
        url_portal="https://portal.tjpe.jus.br",
        url_leiloes="https://portal.tjpe.jus.br/web/corregedoria/leiloes-judiciais/leiloes",
    ),
    Jurisdicao(
        sigla="TJSE",
        nome="Tribunal de Justiça de Sergipe",
        uf=UF.SE,
        codigo_tr="25",
        indice_datajud="api_publica_tjse",
        url_portal="https://www.tjse.jus.br",
        url_leiloes="https://www.tjse.jus.br/portal/servicos/judiciais/leilao-judicial",
    ),
)

POR_SIGLA: dict[str, Jurisdicao] = {j.sigla: j for j in JURISDICOES}
POR_UF: dict[str, Jurisdicao] = {str(j.uf): j for j in JURISDICOES}
POR_CODIGO_TR: dict[str, Jurisdicao] = {j.codigo_tr: j for j in JURISDICOES}

SIGLAS: tuple[str, ...] = tuple(j.sigla for j in JURISDICOES)
UFS: tuple[str, ...] = tuple(str(j.uf) for j in JURISDICOES)
UF_POR_TRIBUNAL: dict[str, str] = {j.sigla: str(j.uf) for j in JURISDICOES}
TRIBUNAL_POR_UF: dict[str, str] = {str(j.uf): j.sigla for j in JURISDICOES}
INDICES_DATAJUD: dict[str, str] = {j.sigla: j.indice_datajud for j in JURISDICOES}


def tribunal_por_codigo_tr(codigo: str) -> str | None:
    jurisdicao = POR_CODIGO_TR.get(codigo)
    return jurisdicao.sigla if jurisdicao else None


def uf_valida(uf: str | None) -> bool:
    return bool(uf) and uf.upper() in UFS
