"""Camada HTTP dos coletores.

Tres responsabilidades, todas exigidas pelas secoes 4.3, 5 e 11 do spec:

1. **robots.txt de verdade** -- consultado antes de cada URL, com Crawl-delay
   respeitado. Um 5xx no robots.txt bloqueia a fonte (RFC 9309): preferimos
   perder uma coleta a raspar um site que talvez nos proiba.
2. **Limite de taxa por host** e User-Agent identificavel.
3. **Arquivamento do HTML bruto** por 30 dias, para depurar quebra de layout e
   para servir de prova de auditoria do que o site publicava naquele dia.
"""

from __future__ import annotations

import hashlib
import logging
import time
import urllib.robotparser
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from radar.config import Settings, get_settings

logger = logging.getLogger(__name__)


class ErroColeta(Exception):
    """Falha recuperavel de coleta: a execucao e marcada como FALHA."""


class RobotsBloqueado(ErroColeta):
    """A fonte proibe este caminho. Nunca contornar -- e o fim da coleta."""


class EstruturaInesperada(ErroColeta):
    """O HTML nao tem mais a estrutura que o conector espera.

    Sinaliza "o site mudou de layout" para o painel de saude das fontes
    (secao 15), em vez de silenciosamente coletar zero itens.
    """


@dataclass(frozen=True)
class RespostaBruta:
    url: str
    status: int
    conteudo: bytes
    headers: dict[str, str]
    buscado_em: datetime
    sha256: str
    caminho_arquivo: Path | None = None

    @property
    def texto(self) -> str:
        return self.conteudo.decode("utf-8", errors="replace")

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class EstatisticasFetcher:
    requisicoes: int = 0
    bytes_baixados: int = 0
    bloqueios_robots: int = 0
    erros: int = 0


class PoliticaRobots:
    """Cache de robots.txt por host."""

    def __init__(self, cliente: httpx.Client, user_agent: str, habilitado: bool = True) -> None:
        self._cliente = cliente
        self._ua = user_agent
        self._habilitado = habilitado
        self._cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _parser(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        partes = urlparse(url)
        raiz = f"{partes.scheme}://{partes.netloc}"
        if raiz in self._cache:
            return self._cache[raiz]

        parser = urllib.robotparser.RobotFileParser()
        parser.set_url(urljoin(raiz, "/robots.txt"))
        try:
            resp = self._cliente.get(urljoin(raiz, "/robots.txt"))
        except httpx.HTTPError as exc:
            logger.warning("robots.txt de %s inacessivel (%s): bloqueando a fonte", raiz, exc)
            self._cache[raiz] = None  # None = indisponivel => negar
            return None

        if resp.status_code >= 500:
            logger.warning("robots.txt de %s devolveu %s: bloqueando", raiz, resp.status_code)
            self._cache[raiz] = None
            return None
        if resp.status_code >= 400:
            # RFC 9309: robots.txt ausente significa acesso liberado.
            parser.parse([])
            parser.allow_all = True
        else:
            parser.parse(resp.text.splitlines())
        self._cache[raiz] = parser
        return parser

    def pode_buscar(self, url: str) -> bool:
        if not self._habilitado:
            return True
        parser = self._parser(url)
        if parser is None:
            return False
        return parser.can_fetch(self._ua, url)

    def crawl_delay(self, url: str) -> float | None:
        if not self._habilitado:
            return None
        parser = self._parser(url)
        if parser is None:
            return None
        try:
            valor = parser.crawl_delay(self._ua)
        except Exception:  # pragma: no cover - parsers antigos
            return None
        return float(valor) if valor else None


class LimitadorPorHost:
    def __init__(self, delay_minimo: float) -> None:
        self._delay = delay_minimo
        self._ultimo: dict[str, float] = {}
        self._delays_especificos: dict[str, float] = {}

    def definir_delay(self, host: str, delay: float) -> None:
        self._delays_especificos[host] = max(delay, self._delay)

    def aguardar(self, url: str) -> None:
        host = urlparse(url).netloc
        delay = self._delays_especificos.get(host, self._delay)
        ultimo = self._ultimo.get(host)
        if ultimo is not None:
            restante = delay - (time.monotonic() - ultimo)
            if restante > 0:
                time.sleep(restante)
        self._ultimo[host] = time.monotonic()


class ArquivoBruto:
    """Guarda o que foi baixado, em data/raw/<fonte>/<AAAA-MM-DD>/<sha>.<ext>."""

    def __init__(self, raiz: Path, retencao_dias: int) -> None:
        self.raiz = raiz
        self.retencao_dias = retencao_dias

    def salvar(self, fonte_slug: str, url: str, conteudo: bytes, sha: str, ext: str) -> Path:
        dia = datetime.now(UTC).strftime("%Y-%m-%d")
        destino = self.raiz / fonte_slug / dia
        destino.mkdir(parents=True, exist_ok=True)
        caminho = destino / f"{sha[:16]}.{ext}"
        if not caminho.exists():
            caminho.write_bytes(conteudo)
            caminho.with_suffix(f".{ext}.url").write_text(url, encoding="utf-8")
        return caminho

    def limpar_expirados(self) -> int:
        """Remove capturas alem da janela de retencao. Devolve quantos dias sumiram."""
        if not self.raiz.exists():
            return 0
        limite = datetime.now(UTC).date() - timedelta(days=self.retencao_dias)
        removidos = 0
        for pasta_fonte in self.raiz.iterdir():
            if not pasta_fonte.is_dir():
                continue
            for pasta_dia in pasta_fonte.iterdir():
                try:
                    dia = datetime.strptime(pasta_dia.name, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if dia < limite:
                    for arquivo in pasta_dia.iterdir():
                        arquivo.unlink()
                    pasta_dia.rmdir()
                    removidos += 1
        return removidos


class Fetcher:
    """Cliente HTTP dos conectores. Use sempre via ``criar_fetcher``."""

    def __init__(
        self,
        settings: Settings | None = None,
        cliente: httpx.Client | None = None,
        arquivo: ArquivoBruto | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._proprio_cliente = cliente is None
        self.cliente = cliente or httpx.Client(
            headers={
                "User-Agent": self.settings.user_agent,
                "Accept-Language": "pt-BR,pt;q=0.9",
            },
            timeout=self.settings.timeout_http_s,
            follow_redirects=True,
        )
        self.robots = PoliticaRobots(
            self.cliente, self.settings.user_agent, self.settings.respeitar_robots
        )
        self.limitador = LimitadorPorHost(self.settings.delay_minimo_por_host_s)
        self.arquivo = arquivo or ArquivoBruto(
            self.settings.diretorio_raw, self.settings.retencao_raw_dias
        )
        self.stats = EstatisticasFetcher()

    def get(self, url: str, fonte_slug: str = "desconhecida", ext: str = "html") -> RespostaBruta:
        if not self.robots.pode_buscar(url):
            self.stats.bloqueios_robots += 1
            raise RobotsBloqueado(f"robots.txt proibe coletar {url}")

        delay = self.robots.crawl_delay(url)
        if delay:
            self.limitador.definir_delay(urlparse(url).netloc, delay)

        ultimo_erro: Exception | None = None
        for tentativa in range(1, self.settings.max_tentativas_http + 1):
            self.limitador.aguardar(url)
            try:
                resp = self.cliente.get(url)
            except httpx.HTTPError as exc:
                ultimo_erro = exc
                self.stats.erros += 1
                logger.warning("tentativa %s falhou para %s: %s", tentativa, url, exc)
                time.sleep(min(2**tentativa, 16))
                continue

            self.stats.requisicoes += 1
            self.stats.bytes_baixados += len(resp.content)

            if resp.status_code in (429, 503) and tentativa < self.settings.max_tentativas_http:
                espera = float(resp.headers.get("Retry-After", 2**tentativa))
                logger.info("%s pediu espera de %ss", url, espera)
                time.sleep(min(espera, 60))
                continue

            sha = hashlib.sha256(resp.content).hexdigest()
            caminho = self.arquivo.salvar(fonte_slug, url, resp.content, sha, ext)
            return RespostaBruta(
                url=str(resp.url),
                status=resp.status_code,
                conteudo=resp.content,
                headers=dict(resp.headers),
                buscado_em=datetime.now(UTC),
                sha256=sha,
                caminho_arquivo=caminho,
            )

        raise ErroColeta(f"falha ao buscar {url}: {ultimo_erro}")

    def baixar_documento(self, url: str, fonte_slug: str) -> RespostaBruta:
        ext = "pdf" if url.lower().split("?")[0].endswith(".pdf") else "bin"
        return self.get(url, fonte_slug=fonte_slug, ext=ext)

    def fechar(self) -> None:
        if self._proprio_cliente:
            self.cliente.close()


@contextmanager
def criar_fetcher(settings: Settings | None = None) -> Iterator[Fetcher]:
    settings = settings or get_settings()
    settings.garantir_diretorios()
    fetcher = Fetcher(settings)
    try:
        yield fetcher
    finally:
        fetcher.fechar()
