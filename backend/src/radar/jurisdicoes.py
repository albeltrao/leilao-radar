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

from radar.enums import UF, EsferaJustica


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

@dataclass(frozen=True, slots=True)
class JurisdicaoFederal:
    """Um Tribunal Regional Federal.

    Diferente do TJ em um ponto que importa: a região cobre vários estados, então
    o código TR **não** determina a UF. Um processo do TRF5 pode ser de Alagoas,
    de Pernambuco ou de Sergipe — quem diz é a seção judiciária citada no texto.
    Por isso `ufs` aqui é a região inteira e existe `uf_por_secao_judiciaria`.
    """

    sigla: str
    nome: str
    codigo_tr: str
    ufs: tuple[str, ...]
    url_portal: str

    @property
    def ufs_cobertas(self) -> tuple[str, ...]:
        """Interseção da região com os estados que o Radar acompanha."""
        return tuple(uf for uf in self.ufs if uf in UFS)


# Só as regiões que alcançam os estados do Radar. TRF1 responde pela Bahia;
# TRF5 responde por Alagoas, Pernambuco e Sergipe.
JURISDICOES_FEDERAIS: tuple[JurisdicaoFederal, ...] = (
    JurisdicaoFederal(
        sigla="TRF1",
        nome="Tribunal Regional Federal da 1ª Região",
        codigo_tr="01",
        ufs=("AC", "AM", "AP", "BA", "DF", "GO", "MA", "MT", "PA", "PI", "RO", "RR", "TO"),
        url_portal="https://www.trf1.jus.br",
    ),
    JurisdicaoFederal(
        sigla="TRF5",
        nome="Tribunal Regional Federal da 5ª Região",
        codigo_tr="05",
        ufs=("AL", "CE", "PB", "PE", "RN", "SE"),
        url_portal="https://www.trf5.jus.br",
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

FEDERAIS_POR_SIGLA: dict[str, JurisdicaoFederal] = {
    j.sigla: j for j in JURISDICOES_FEDERAIS
}
FEDERAIS_POR_CODIGO_TR: dict[str, JurisdicaoFederal] = {
    j.codigo_tr: j for j in JURISDICOES_FEDERAIS
}
SIGLAS_FEDERAIS: tuple[str, ...] = tuple(j.sigla for j in JURISDICOES_FEDERAIS)
# Qual TRF responde por cada estado do Radar.
TRF_POR_UF: dict[str, str] = {
    uf: j.sigla for j in JURISDICOES_FEDERAIS for uf in j.ufs_cobertas
}

# Nome por extenso -> UF, para ler "Seção Judiciária de Alagoas" no diário.
NOME_POR_UF: dict[str, str] = {
    "AL": "Alagoas",
    "BA": "Bahia",
    "PE": "Pernambuco",
    "SE": "Sergipe",
}


def tribunal_por_codigo_tr(codigo: str, segmento: str = "8") -> str | None:
    """Sigla do tribunal a partir do par TR do número CNJ.

    O par TR só é único **dentro** do segmento: 05 é TJBA no segmento 8 e TRF5
    no segmento 4. Ignorar o segmento faria um processo federal de Pernambuco
    entrar como processo estadual da Bahia — erro silencioso, porque o número
    continua válido no dígito verificador.
    """
    if segmento == "4":
        federal = FEDERAIS_POR_CODIGO_TR.get(codigo)
        return federal.sigla if federal else None
    if segmento != "8":
        return None
    jurisdicao = POR_CODIGO_TR.get(codigo)
    return jurisdicao.sigla if jurisdicao else None


def esfera_do_tribunal(sigla: str | None) -> EsferaJustica:
    if not sigla:
        return EsferaJustica.DESCONHECIDA
    if sigla in FEDERAIS_POR_SIGLA:
        return EsferaJustica.FEDERAL
    if sigla in POR_SIGLA:
        return EsferaJustica.ESTADUAL
    return EsferaJustica.DESCONHECIDA


def ufs_do_tribunal(sigla: str | None) -> tuple[str, ...]:
    """UFs do Radar que o tribunal atende. Uma para TJ, várias para TRF."""
    if not sigla:
        return ()
    if sigla in POR_SIGLA:
        return (str(POR_SIGLA[sigla].uf),)
    federal = FEDERAIS_POR_SIGLA.get(sigla)
    return federal.ufs_cobertas if federal else ()


def uf_valida(uf: str | None) -> bool:
    return bool(uf) and uf.upper() in UFS
