"""Contrato de um conector e o registro global de fontes."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from radar.collectors.dto import ResultadoConector
from radar.collectors.http import Fetcher
from radar.enums import TipoFonte

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetadadosFonte:
    slug: str
    nome: str
    tipo: TipoFonte
    uf: str | None
    url_alvo: str
    periodicidade_horas: int
    descricao: str = ""
    validado_ao_vivo: bool = False
    """False = os seletores foram escritos a partir da estrutura documentada da
    pagina e exercitados apenas contra fixture. Antes de rodar em producao,
    execute ``radar coletar --fonte <slug> --validar`` com rede liberada e
    confira o relatorio. O painel de saude mostra esse selo."""


class Conector(ABC):
    """Uma fonte. Deve ser idempotente e nunca levantar por HTML vazio."""

    meta: MetadadosFonte

    @abstractmethod
    def coletar(self, fetcher: Fetcher) -> ResultadoConector:
        """Busca e devolve DTOs. Levanta EstruturaInesperada se o layout mudou."""

    @property
    def slug(self) -> str:
        return self.meta.slug

    def __repr__(self) -> str:  # pragma: no cover - diagnostico
        return f"<{type(self).__name__} {self.meta.slug}>"


_REGISTRO: dict[str, Conector] = {}


def registrar(conector: Conector) -> Conector:
    if conector.slug in _REGISTRO:
        raise ValueError(f"conector duplicado: {conector.slug}")
    _REGISTRO[conector.slug] = conector
    return conector


def obter(slug: str) -> Conector:
    carregar_todos()
    if slug not in _REGISTRO:
        disponiveis = ", ".join(sorted(_REGISTRO)) or "(nenhum)"
        raise KeyError(f"fonte desconhecida: {slug}. Disponiveis: {disponiveis}")
    return _REGISTRO[slug]


def listar(tipo: TipoFonte | None = None, uf: str | None = None) -> list[Conector]:
    carregar_todos()
    itens = list(_REGISTRO.values())
    if tipo is not None:
        itens = [c for c in itens if c.meta.tipo == tipo]
    if uf is not None:
        itens = [c for c in itens if c.meta.uf in (uf, None)]
    return sorted(itens, key=lambda c: c.slug)


_carregado = False


def carregar_todos() -> None:
    """Importa os modulos de conector para que os decoradores rodem."""
    global _carregado
    if _carregado:
        return
    _carregado = True
    from radar.collectors import datajud  # noqa: F401
    from radar.collectors.juntas import juceal, juceb, jucepe, jucese  # noqa: F401
    from radar.collectors.leiloeiros import declarativo  # noqa: F401
    from radar.collectors.tribunais import tjal, tjba, tjpe, tjse  # noqa: F401

    declarativo.registrar_perfis()
