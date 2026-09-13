"""Geocodificacao de imoveis (secao 5).

O padrao e o centroide do municipio, carregado de um CSV proprio: funciona
offline, nao depende de servico de terceiros e -- principalmente -- e honesto
sobre a precisao, que viaja junto com a coordenada ate a UI.

Para precisao de endereco, habilite ``GeocodificadorNominatim``: ele respeita o
limite de 1 req/s e exige User-Agent identificavel, como manda a politica de uso
do OpenStreetMap.
"""

from __future__ import annotations

import csv
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from radar.normalizacao import normalizar_texto

logger = logging.getLogger(__name__)

ARQUIVO_CENTROIDES = Path(__file__).resolve().parents[1] / "data" / "municipios_centroides.csv"


@dataclass(frozen=True, slots=True)
class Coordenada:
    latitude: float
    longitude: float
    precisao: str  # MUNICIPIO | BAIRRO | ENDERECO


class Geocodificador(ABC):
    @abstractmethod
    def localizar(
        self, endereco: str | None, bairro: str | None, cidade: str | None, uf: str | None
    ) -> Coordenada | None: ...


class GeocodificadorNulo(Geocodificador):
    def localizar(self, endereco, bairro, cidade, uf):  # noqa: D102
        return None


class GeocodificadorMunicipio(Geocodificador):
    """Centroide do municipio. Precisao declarada: MUNICIPIO."""

    def __init__(self, caminho: Path | None = None) -> None:
        self._tabela: dict[tuple[str, str], tuple[float, float]] = {}
        arquivo = caminho or ARQUIVO_CENTROIDES
        if not arquivo.exists():
            logger.warning("tabela de centroides ausente: %s", arquivo)
            return
        with arquivo.open(encoding="utf-8") as fh:
            linhas = (linha for linha in fh if not linha.startswith("#"))
            for registro in csv.DictReader(linhas):
                chave = (registro["uf"].upper(), normalizar_texto(registro["cidade"]))
                self._tabela[chave] = (
                    float(registro["latitude"]),
                    float(registro["longitude"]),
                )

    def localizar(self, endereco, bairro, cidade, uf):  # noqa: D102
        if not cidade or not uf:
            return None
        coord = self._tabela.get((uf.upper(), normalizar_texto(cidade)))
        if coord is None:
            return None
        return Coordenada(latitude=coord[0], longitude=coord[1], precisao="MUNICIPIO")

    @property
    def municipios_conhecidos(self) -> int:
        return len(self._tabela)


class GeocodificadorNominatim(Geocodificador):  # pragma: no cover - exige rede
    """OpenStreetMap/Nominatim. Desligado por padrao.

    Politica de uso do servico publico: no maximo 1 requisicao por segundo e
    User-Agent identificavel. Para volume de producao, hospede sua propria
    instancia ou contrate um provedor.
    """

    def __init__(self, user_agent: str, fallback: Geocodificador | None = None) -> None:
        import httpx  # noqa: PLC0415

        self._cliente = httpx.Client(
            base_url="https://nominatim.openstreetmap.org",
            headers={"User-Agent": user_agent},
            timeout=20.0,
        )
        self._fallback = fallback or GeocodificadorMunicipio()
        self._ultimo = 0.0

    def localizar(self, endereco, bairro, cidade, uf):  # noqa: D102
        import time  # noqa: PLC0415

        partes = [p for p in (endereco, bairro, cidade, uf, "Brasil") if p]
        if len(partes) < 3:
            return self._fallback.localizar(endereco, bairro, cidade, uf)

        espera = 1.0 - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo = time.monotonic()

        try:
            resp = self._cliente.get(
                "/search", params={"q": ", ".join(partes), "format": "json", "limit": 1}
            )
            resp.raise_for_status()
            dados = resp.json()
        except Exception as exc:
            logger.warning("Nominatim falhou (%s); usando centroide de municipio", exc)
            return self._fallback.localizar(endereco, bairro, cidade, uf)

        if not dados:
            return self._fallback.localizar(endereco, bairro, cidade, uf)
        item = dados[0]
        precisao = "ENDERECO" if endereco else "BAIRRO" if bairro else "MUNICIPIO"
        return Coordenada(float(item["lat"]), float(item["lon"]), precisao)


def criar_geocodificador(nome: str = "municipio", user_agent: str = "") -> Geocodificador:
    match nome:
        case "nulo":
            return GeocodificadorNulo()
        case "nominatim":  # pragma: no cover
            return GeocodificadorNominatim(user_agent)
        case _:
            return GeocodificadorMunicipio()
