"""Coletor generico das paginas de leilao/edital dos tribunais (secao 4.1).

O que um portal de TJ publica e "existe um leilao neste processo, aqui esta o
edital em PDF" -- raramente o detalhe do bem. Entao este coletor produz um lote
minimo (processo, comarca, data da praca, link do edital) e deixa o
enriquecimento para o pipeline de extracao documental da secao 7.
"""

from __future__ import annotations

import logging
import re

from radar.collectors.base import Conector, MetadadosFonte
from radar.collectors.dto import DocumentoBruto, LoteBruto, PracaBruta, ResultadoConector
from radar.collectors.html import (
    linhas_como_dicts,
    links,
    sopa,
    tabelas_com_colunas,
    valor_por_rotulo,
)
from radar.collectors.http import EstruturaInesperada, Fetcher
from radar.enums import TipoDocumento
from radar.normalizacao import (
    extrair_numero_cnj,
    hash_conteudo,
    limpar_espacos,
    parse_data_hora,
)

logger = logging.getLogger(__name__)

_COLUNAS_EDITAL = ("processo", "comarca", "edital", "data", "leilao", "vara", "leiloeiro")
_RE_EDITAL = re.compile(r"edital|leil[aã]o|hasta|praça|praca", re.IGNORECASE)


class ColetorEditaisTribunal(Conector):
    def __init__(
        self,
        meta: MetadadosFonte,
        urls: list[str],
        tribunal_sigla: str,
        uf: str,
        paginacao: str | None = None,
        max_paginas: int = 10,
    ) -> None:
        self.meta = meta
        self.urls = urls
        self.tribunal_sigla = tribunal_sigla
        self.uf = uf
        # Ex.: "?page={n}" -- o TJPE pagina por circunscricao judiciaria.
        self.paginacao = paginacao
        self.max_paginas = max_paginas

    def coletar(self, fetcher: Fetcher) -> ResultadoConector:
        resultado = ResultadoConector()
        for url in self._urls_a_visitar():
            resposta = fetcher.get(url, fonte_slug=self.meta.slug)
            if not resposta.ok:
                resultado.avisos.append(f"{url} devolveu HTTP {resposta.status}")
                continue
            resultado.paginas_visitadas += 1
            lotes = self.parse(resposta.texto, url)
            if not lotes and self.paginacao:
                break  # pagina vazia encerra a paginacao
            resultado.lotes.extend(lotes)

        if not resultado.lotes:
            raise EstruturaInesperada(
                f"{self.meta.slug}: nenhum edital reconhecido -- verifique se a pagina "
                f"{self.urls[0]} mudou de estrutura"
            )
        return resultado

    def _urls_a_visitar(self):
        for url in self.urls:
            if not self.paginacao:
                yield url
                continue
            for pagina in range(1, self.max_paginas + 1):
                yield url + self.paginacao.format(n=pagina)

    # -- parsing -----------------------------------------------------------

    def parse(self, html: str, url: str) -> list[LoteBruto]:
        doc = sopa(html)
        lotes: list[LoteBruto] = []

        for tabela in tabelas_com_colunas(doc, _COLUNAS_EDITAL, minimo=2):
            for linha in linhas_como_dicts(tabela):
                lote = self._de_linha(linha, url)
                if lote is not None:
                    lotes.append(lote)

        if not lotes:
            lotes = self._de_links_pdf(doc, url)

        return lotes

    def _de_linha(self, linha: dict[str, str], url: str) -> LoteBruto | None:
        conteudo = " ".join(v for k, v in linha.items() if not k.endswith("__href"))
        if len(conteudo) < 8:
            return None
        processo = extrair_numero_cnj(conteudo)
        comarca = limpar_espacos(
            valor_por_rotulo(linha, "comarca", "circunscricao", "foro", "municipio")
        )
        titulo = limpar_espacos(
            valor_por_rotulo(linha, "edital", "leilao", "titulo", "objeto", "descricao")
        )
        if not (processo or titulo or comarca):
            return None

        href = next(
            (v for k, v in linha.items() if k.endswith("__href") and v),
            None,
        )
        documentos = []
        if href:
            from urllib.parse import urljoin

            documentos.append(
                DocumentoBruto(url=urljoin(url, href), tipo=TipoDocumento.EDITAL, titulo=titulo)
            )

        data_praca = parse_data_hora(
            valor_por_rotulo(linha, "data", "praca", "sessao", "realizacao") or conteudo
        )
        pracas = [PracaBruta(ordem=1, data_hora=data_praca)] if data_praca else []

        rotulo = titulo or f"Leilao judicial {comarca or self.tribunal_sigla}"
        return LoteBruto(
            fonte_slug=self.meta.slug,
            fonte_url=documentos[0].url if documentos else url,
            titulo=rotulo[:300],
            descricao=limpar_espacos(conteudo),
            numero_processo=processo,
            tribunal_sigla=self.tribunal_sigla,
            comarca=comarca,
            vara=limpar_espacos(valor_por_rotulo(linha, "vara", "juizo", "unidade")),
            leiloeiro_nome=limpar_espacos(valor_por_rotulo(linha, "leiloeiro", "responsavel")),
            uf=self.uf,
            pracas=pracas,
            documentos=documentos,
            extras={"origem": "tabela", "chave_fallback": hash_conteudo(url, conteudo)},
        )

    def _de_links_pdf(self, doc, url: str) -> list[LoteBruto]:
        """Fallback: a pagina e so uma lista de PDFs de edital."""
        lotes: list[LoteBruto] = []
        candidatos = links(doc, url, extensao=".pdf")
        if not candidatos:
            candidatos = links(doc, url, padrao=_RE_EDITAL.pattern)
        for href, rotulo in candidatos:
            rotulo_limpo = limpar_espacos(rotulo) or href.rsplit("/", 1)[-1]
            if not _RE_EDITAL.search(rotulo_limpo) and not _RE_EDITAL.search(href):
                continue
            processo = extrair_numero_cnj(f"{rotulo_limpo} {href}")
            data_praca = parse_data_hora(rotulo_limpo)
            lotes.append(
                LoteBruto(
                    fonte_slug=self.meta.slug,
                    fonte_url=href,
                    titulo=rotulo_limpo[:300],
                    numero_processo=processo,
                    tribunal_sigla=self.tribunal_sigla,
                    uf=self.uf,
                    pracas=[PracaBruta(ordem=1, data_hora=data_praca)] if data_praca else [],
                    documentos=[
                        DocumentoBruto(
                            url=href, tipo=TipoDocumento.EDITAL, titulo=rotulo_limpo
                        )
                    ],
                    extras={"origem": "link_pdf", "chave_fallback": hash_conteudo(href)},
                )
            )
        return lotes


def rotulo_comarca(texto_bruto: str | None) -> str | None:
    """Extrai "Comarca de X" / "Circunscricao de X" de um texto corrido."""
    if not texto_bruto:
        return None
    m = re.search(
        r"(?:comarca|circunscri[cç][aã]o|foro)\s+(?:judici[aá]ria\s+)?(?:de|da|do)\s+"
        r"([A-ZÁÂÃÉÊÍÓÔÕÚÇ][\wÀ-ÿ'\s-]{2,60})",
        texto_bruto,
        re.IGNORECASE,
    )
    return limpar_espacos(m.group(1)) if m else None
