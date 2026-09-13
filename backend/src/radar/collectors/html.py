"""Helpers de parsing tolerantes a mudanca de layout.

Em vez de fixar caminhos CSS ("div.content > table:nth-child(3) td"), que quebram
no primeiro redesign, os conectores procuram a *estrutura semantica*: a tabela
cujo cabecalho fala de "nome" e "matricula", o link cujo texto parece um edital.
E mais lento de escrever e muito mais estavel -- risco numero 1 da secao 15.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from radar.normalizacao import limpar_espacos, normalizar_texto

_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_TELEFONE = re.compile(r"\(?\d{2}\)?[\s-]?\d{4,5}[-\s]?\d{4}")


def sopa(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:  # pragma: no cover - lxml ausente
        return BeautifulSoup(html, "html.parser")


def texto(node: Tag | None, separador: str = " ") -> str:
    if node is None:
        return ""
    return limpar_espacos(node.get_text(separador, strip=True)) or ""


def _cabecalhos(tabela: Tag) -> list[str]:
    linha_th = tabela.find("tr")
    if linha_th is None:
        return []
    celulas = linha_th.find_all(["th", "td"])
    return [normalizar_texto(texto(c)) for c in celulas]


def tabelas_com_colunas(
    raiz: BeautifulSoup | Tag, termos: Iterable[str], minimo: int = 1
) -> Iterator[Tag]:
    """Tabelas cujo cabecalho contem pelo menos ``minimo`` dos termos dados."""
    alvos = [normalizar_texto(t) for t in termos]
    for tabela in raiz.find_all("table"):
        cabecalhos = _cabecalhos(tabela)
        if not cabecalhos:
            continue
        achados = sum(
            1 for alvo in alvos if any(alvo and alvo in cab for cab in cabecalhos)
        )
        if achados >= minimo:
            yield tabela


def linhas_como_dicts(tabela: Tag) -> list[dict[str, str]]:
    """Converte a tabela em dicts com chave = cabecalho normalizado.

    Tolera tabelas sem <thead>, com colspan simples e com linhas de rodape
    (que viram dicts com menos chaves e sao filtradas pelo chamador).
    """
    linhas = tabela.find_all("tr")
    if not linhas:
        return []
    cabecalhos = _cabecalhos(tabela)
    if not cabecalhos:
        return []
    resultado: list[dict[str, str]] = []
    for linha in linhas[1:]:
        celulas = linha.find_all(["td", "th"])
        if not celulas:
            continue
        registro: dict[str, str] = {}
        for i, celula in enumerate(celulas):
            chave = cabecalhos[i] if i < len(cabecalhos) else f"coluna_{i}"
            valor = texto(celula)
            if chave in registro and valor:
                registro[chave] = f"{registro[chave]} {valor}".strip()
            else:
                registro[chave] = valor
            link = celula.find("a", href=True)
            if link is not None:
                registro.setdefault(f"{chave}__href", link["href"])
        if any(v for v in registro.values()):
            resultado.append(registro)
    return resultado


def valor_por_rotulo(registro: dict[str, str], *rotulos: str) -> str | None:
    """Busca no dict pelo primeiro cabecalho que contenha um dos rotulos."""
    for rotulo in rotulos:
        alvo = normalizar_texto(rotulo)
        for chave, valor in registro.items():
            if chave.endswith("__href"):
                continue
            if alvo and alvo in chave and valor:
                return valor
    return None


def href_por_rotulo(registro: dict[str, str], *rotulos: str) -> str | None:
    for rotulo in rotulos:
        alvo = normalizar_texto(rotulo)
        for chave, valor in registro.items():
            if chave.endswith("__href") and alvo in chave and valor:
                return valor
    return None


def links(
    raiz: BeautifulSoup | Tag, base_url: str, padrao: str | None = None, extensao: str | None = None
) -> list[tuple[str, str]]:
    """(url_absoluta, texto) dos <a> que casam com o padrao/extensao."""
    regex = re.compile(padrao, re.IGNORECASE) if padrao else None
    achados: list[tuple[str, str]] = []
    vistos: set[str] = set()
    for a in raiz.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "#")):
            continue
        rotulo = texto(a)
        url = urljoin(base_url, href)
        if extensao and not url.lower().split("?")[0].endswith(extensao.lower()):
            continue
        if regex and not (regex.search(rotulo) or regex.search(url)):
            continue
        if url in vistos:
            continue
        vistos.add(url)
        achados.append((url, rotulo))
    return achados


def primeiro_email(node: Tag | str | None) -> str | None:
    alvo = node if isinstance(node, str) else texto(node)
    m = _RE_EMAIL.search(alvo or "")
    return m.group(0) if m else None


def primeiro_telefone(node: Tag | str | None) -> str | None:
    alvo = node if isinstance(node, str) else texto(node)
    m = _RE_TELEFONE.search(alvo or "")
    return limpar_espacos(m.group(0)) if m else None


def primeiro_site(node: Tag | None) -> str | None:
    """Primeira URL http(s) que nao seja do proprio portal governamental."""
    if node is None:
        return None
    for a in node.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("http") and not re.search(
            r"(jus\.br|gov\.br)(/|$)", href, re.IGNORECASE
        ):
            return href
    m = re.search(r"https?://[^\s,;)\"']+", texto(node))
    return m.group(0) if m else None


def blocos_repetidos(raiz: BeautifulSoup | Tag, minimo: int = 3) -> list[Tag]:
    """Detecta listagens em "cards": o maior grupo de irmaos com a mesma classe.

    Usado pelos conectores de leiloeiro quando o site nao usa <table>.
    """
    grupos: dict[tuple[str, str], list[Tag]] = {}
    for node in raiz.find_all(["li", "article", "div", "section"]):
        classes = node.get("class")
        if not classes:
            continue
        chave = (node.name, " ".join(sorted(classes)))
        grupos.setdefault(chave, []).append(node)
    candidatos = [g for g in grupos.values() if len(g) >= minimo]
    if not candidatos:
        return []
    # Preferimos o grupo mais numeroso; empate resolve pelo que tem mais texto.
    candidatos.sort(key=lambda g: (len(g), sum(len(texto(n)) for n in g)), reverse=True)
    return candidatos[0]
