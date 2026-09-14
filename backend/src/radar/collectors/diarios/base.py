"""Coletor do Diário de Justiça Eletrônico Nacional (DJEN / API Comunica).

Por que o DJEN e não o diário de cada tribunal: a seção 11 manda preferir API
oficial a raspagem, sempre que existir. Desde a Resolução CNJ nº 455/2022 os
tribunais publicam no DJEN, e o CNJ expõe a API Comunica -- JSON, pública, sem
login. Ela cobre as duas esferas que se pediu: os TJs (estadual) e os TRFs
(federal). Raspar o PDF do caderno de cada tribunal seria mais frágil, mais
pesado para o servidor deles e desnecessário.

**Filtro de texto no servidor, decisão local.** Puxar o diário inteiro de quatro
estados todo dia seriam dezenas de milhares de publicações para descartar quase
todas. Então a busca vai ao servidor já com os termos de leilão -- menos tráfego
para os dois lados. Mas o filtro do servidor é só uma peneira grossa: quem
decide se a publicação é leilão é ``radar.diarios.detectar_leilao``, aqui no
nosso lado, com evidência e confiança auditáveis. Se o CNJ mudar a semântica da
busca, mudamos a peneira, não o critério.

ATENÇÃO -- contrato não validado ao vivo. Os nomes de campo abaixo vêm da
documentação da API, não de uma resposta observada nesta máquina (o ambiente de
desenvolvimento não tem rede liberada para o CNJ). Por isso todo conector daqui
nasce com ``validado_ao_vivo=False`` e fica fora da coleta automática até
alguém rodar, com rede:

    radar fontes validar --fonte djen-tjal

O parser aceita mais de uma grafia por campo justamente porque o contrato não
foi conferido: é tolerância deliberada, não desleixo.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode

from radar.collectors.base import Conector, MetadadosFonte
from radar.collectors.dto import PublicacaoBruta, ResultadoConector
from radar.collectors.http import EstruturaInesperada, Fetcher
from radar.enums import EsferaJustica, TipoFonte
from radar.jurisdicoes import ufs_do_tribunal
from radar.normalizacao import extrair_numero_cnj, limpar_espacos, parse_data_hora

logger = logging.getLogger(__name__)

BASE_COMUNICA = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"

# Termos passados ao filtro do servidor. Peneira grossa de propósito: perder uma
# publicação por vocabulário incomum é pior que trazer ruído, porque o ruído o
# detector descarta e a perda ninguém vê.
TERMOS_BUSCA: tuple[str, ...] = (
    "leilão",
    "hasta pública",
    "praça",
    "alienação judicial",
)

# Nomes alternativos aceitos por campo, na ordem de preferência.
_CAMPOS = {
    "identificador": ("id", "numeroComunicacao", "numero_comunicacao", "hash"),
    "texto": ("texto", "textoComunicacao", "conteudo"),
    "data_publicacao": (
        "data_disponibilizacao",
        "datadisponibilizacao",
        "dataDisponibilizacao",
        "dataPublicacao",
    ),
    "data_divulgacao": ("datadivulgacao", "dataDivulgacao", "data_divulgacao"),
    "numero_processo": (
        "numeroprocessocommascara",
        "numero_processo",
        "numeroProcesso",
        "numeroProcessoComMascara",
    ),
    "orgao": ("nomeOrgao", "nome_orgao", "orgao", "siglaOrgao"),
    "tribunal": ("siglaTribunal", "sigla_tribunal", "tribunal"),
    "link": ("link", "url", "linkPublicacao"),
    "caderno": ("tipoComunicacao", "tipo_comunicacao", "nomeClasse", "caderno"),
    "edicao": ("numeroEdicao", "numero_edicao", "edicao"),
    "municipio": ("municipio", "nomeMunicipio", "comarca"),
}


def _primeiro_campo(item: dict, chave: str) -> str | None:
    for nome in _CAMPOS[chave]:
        valor = item.get(nome)
        if valor not in (None, "", []):
            return str(valor)
    return None


@dataclass(slots=True)
class PaginaPublicacoes:
    """Publicacoes aproveitadas + quantos itens a pagina trouxe de verdade.

    A diferenca importa na paginacao: uma pagina cheia de itens que o parser
    descartou (sem texto, sem identificador) nao e o fim da lista, e tratar as
    duas como iguais faria a coleta parar no primeiro item malformado.
    """

    publicacoes: list[PublicacaoBruta]
    itens_brutos: int


class ColetorDiarioEletronico(Conector):
    """Lê as publicações de um tribunal no DJEN, dentro de uma janela de dias."""

    def __init__(
        self,
        meta: MetadadosFonte,
        tribunal_sigla: str,
        esfera: EsferaJustica,
        *,
        base_url: str = BASE_COMUNICA,
        uf: str | None = None,
        termos: tuple[str, ...] = TERMOS_BUSCA,
        dias_retroativos: int = 3,
        itens_por_pagina: int = 100,
        max_paginas: int = 10,
    ) -> None:
        self.meta = meta
        self.tribunal_sigla = tribunal_sigla
        self.esfera = esfera
        self.base_url = base_url
        self.uf = uf
        self.termos = termos
        # Janela retroativa em vez de "só hoje": o diário sai de madrugada, a
        # coleta pode falhar num dia, e reprocessar é barato -- a chave
        # (diario_slug, identificador) faz a repetição virar atualização.
        self.dias_retroativos = dias_retroativos
        self.itens_por_pagina = itens_por_pagina
        self.max_paginas = max_paginas

    # -- coleta ------------------------------------------------------------

    def janela(self, hoje: date | None = None) -> tuple[date, date]:
        fim = hoje or datetime.now(UTC).date()
        return fim - timedelta(days=self.dias_retroativos), fim

    def urls_do_termo(self, termo: str, hoje: date | None = None) -> Iterator[str]:
        inicio, fim = self.janela(hoje)
        for pagina in range(1, self.max_paginas + 1):
            parametros = {
                "siglaTribunal": self.tribunal_sigla,
                "dataDisponibilizacaoInicio": inicio.isoformat(),
                "dataDisponibilizacaoFim": fim.isoformat(),
                "texto": termo,
                "itensPorPagina": self.itens_por_pagina,
                "pagina": pagina,
            }
            yield f"{self.base_url}?{urlencode(parametros)}"

    def coletar(self, fetcher: Fetcher) -> ResultadoConector:
        resultado = ResultadoConector()
        # Termos diferentes trazem a mesma publicacao ("leilao" e "praca" casam
        # no mesmo edital). Sem este conjunto, o mesmo edital viraria quatro
        # publicacoes -- a chave unica no banco salvaria, mas depois de quatro
        # deteccoes rodadas a toa.
        vistos: set[str] = set()
        for termo in self.termos:
            for url in self.urls_do_termo(termo):
                resposta = fetcher.get(url, fonte_slug=self.meta.slug, ext="json")
                if not resposta.ok:
                    resultado.avisos.append(f"HTTP {resposta.status} em {url}")
                    break
                resultado.paginas_visitadas += 1
                pagina = self.parse(resposta.texto, url)
                for publicacao in pagina.publicacoes:
                    if publicacao.identificador in vistos:
                        continue
                    vistos.add(publicacao.identificador)
                    resultado.publicacoes.append(publicacao)
                if pagina.itens_brutos < self.itens_por_pagina:
                    break  # ultima pagina deste termo
        return resultado

    # -- parsing -----------------------------------------------------------

    def parse(self, corpo: str, url: str) -> PaginaPublicacoes:
        try:
            dados = json.loads(corpo)
        except json.JSONDecodeError as exc:
            raise EstruturaInesperada(
                f"{self.meta.slug}: resposta não é JSON ({exc}). A API Comunica mudou "
                f"de formato ou {url} devolveu uma página de erro."
            ) from exc

        itens = self._itens(dados, url)
        publicacoes = [self._publicacao(item, url) for item in itens]
        return PaginaPublicacoes(
            publicacoes=[p for p in publicacoes if p is not None], itens_brutos=len(itens)
        )

    def _itens(self, dados: object, url: str) -> list[dict]:
        if isinstance(dados, list):
            return [i for i in dados if isinstance(i, dict)]
        if isinstance(dados, dict):
            for chave in ("items", "itens", "content", "data", "resultado"):
                valor = dados.get(chave)
                if isinstance(valor, list):
                    return [i for i in valor if isinstance(i, dict)]
            # Envelope reconhecível mas sem lista: zero resultados é normal.
            if {"status", "message", "count"} & set(dados):
                return []
        raise EstruturaInesperada(
            f"{self.meta.slug}: JSON sem lista de publicações em {url} -- "
            "confira o contrato da API Comunica antes de religar esta fonte"
        )

    def _publicacao(self, item: dict, url: str) -> PublicacaoBruta | None:
        texto = _primeiro_campo(item, "texto")
        if not texto or len(texto.strip()) < 40:
            return None
        identificador = _primeiro_campo(item, "identificador")
        if not identificador:
            # Sem identificador não há idempotência: cada coleta criaria um lote
            # novo do mesmo leilão. Melhor descartar e registrar o aviso.
            return None

        numero = _primeiro_campo(item, "numero_processo")
        return PublicacaoBruta(
            fonte_slug=self.meta.slug,
            fonte_url=_primeiro_campo(item, "link") or url,
            diario_slug=self.meta.slug,
            diario_nome=self.meta.nome,
            identificador=identificador,
            texto=texto,
            esfera=self.esfera,
            tribunal_sigla=_primeiro_campo(item, "tribunal") or self.tribunal_sigla,
            uf=self.uf,
            data_publicacao=parse_data_hora(_primeiro_campo(item, "data_publicacao")),
            data_divulgacao=parse_data_hora(_primeiro_campo(item, "data_divulgacao")),
            numero_edicao=_primeiro_campo(item, "edicao"),
            caderno=_primeiro_campo(item, "caderno"),
            numero_processo=extrair_numero_cnj(numero) if numero else extrair_numero_cnj(texto),
            orgao=limpar_espacos(_primeiro_campo(item, "orgao")),
            municipio=limpar_espacos(_primeiro_campo(item, "municipio")),
            extras={"consulta": url},
        )


def meta_djen(
    tribunal_sigla: str, nome_tribunal: str, esfera: EsferaJustica
) -> MetadadosFonte:
    ufs = ufs_do_tribunal(tribunal_sigla)
    return MetadadosFonte(
        slug=f"djen-{tribunal_sigla.lower()}",
        nome=f"DJEN - {nome_tribunal}",
        tipo=TipoFonte.DIARIO_OFICIAL,
        # UF única quando o tribunal só alcança um estado do Radar; None para o
        # TRF5, que responde por AL, PE e SE -- fixar um deles esconderia os
        # outros dois do filtro por estado.
        uf=ufs[0] if len(ufs) == 1 else None,
        url_alvo=BASE_COMUNICA,
        periodicidade_horas=12,
        descricao=(
            f"Publicações de {nome_tribunal} no Diário de Justiça Eletrônico Nacional "
            f"(Res. CNJ 455/2022), via API Comunica. Cobertura: "
            f"{', '.join(ufs) if ufs else 'região inteira'}. "
            "CONTRATO NÃO VALIDADO AO VIVO: confirme com radar fontes validar."
        ),
    )
