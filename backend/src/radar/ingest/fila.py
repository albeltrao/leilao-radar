"""Fila de ingestao (secao 5).

A fila desacopla coleta de processamento: o coletor so precisa terminar rapido e
nao perder o que ja baixou; o worker faz o trabalho caro (normalizar, dedup,
baixar PDF, extrair) no seu proprio ritmo e pode ser reiniciado sem refazer HTTP.

Duas implementacoes atras da mesma interface: memoria (dev/teste, sincrona) e
Redis Streams (producao, com ack e reentrega).
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from radar.config import Settings, get_settings

logger = logging.getLogger(__name__)

TOPICO_LOTES = "lotes"
TOPICO_LEILOEIROS = "leiloeiros"
TOPICO_DOCUMENTOS = "documentos"
TOPICO_PUBLICACOES = "publicacoes"


@dataclass(slots=True)
class Mensagem:
    topico: str
    payload: dict[str, Any]
    id: str | None = None
    tentativas: int = 0
    criada_em: datetime = field(default_factory=lambda: datetime.now(UTC))

    def para_json(self) -> str:
        dados = asdict(self)
        dados["criada_em"] = self.criada_em.isoformat()
        return json.dumps(dados, default=str, ensure_ascii=False)


class FilaIngestao(ABC):
    @abstractmethod
    def publicar(self, mensagem: Mensagem) -> None: ...

    @abstractmethod
    def consumir(self, topico: str, limite: int = 100) -> list[Mensagem]: ...

    @abstractmethod
    def confirmar(self, mensagem: Mensagem) -> None:
        """Ack. Sem isso a mensagem volta a ser entregue."""

    @abstractmethod
    def pendentes(self, topico: str) -> int: ...


class FilaMemoria(FilaIngestao):
    """Fila em processo. Nao sobrevive a reinicio -- so para dev e testes."""

    def __init__(self) -> None:
        self._filas: dict[str, deque[Mensagem]] = {}
        self._em_voo: dict[str, Mensagem] = {}
        self._contador = 0

    def publicar(self, mensagem: Mensagem) -> None:
        self._contador += 1
        mensagem.id = mensagem.id or f"mem-{self._contador}"
        self._filas.setdefault(mensagem.topico, deque()).append(mensagem)

    def consumir(self, topico: str, limite: int = 100) -> list[Mensagem]:
        fila = self._filas.setdefault(topico, deque())
        saida: list[Mensagem] = []
        while fila and len(saida) < limite:
            msg = fila.popleft()
            msg.tentativas += 1
            self._em_voo[msg.id] = msg
            saida.append(msg)
        return saida

    def confirmar(self, mensagem: Mensagem) -> None:
        self._em_voo.pop(mensagem.id, None)

    def devolver(self, mensagem: Mensagem) -> None:
        """Nack: recoloca no inicio da fila para nova tentativa."""
        self._em_voo.pop(mensagem.id, None)
        self._filas.setdefault(mensagem.topico, deque()).appendleft(mensagem)

    def pendentes(self, topico: str) -> int:
        return len(self._filas.get(topico, ()))


class FilaRedisStreams(FilaIngestao):
    """Redis Streams com grupo de consumidores (producao)."""

    GRUPO = "radar"

    def __init__(self, url: str, consumidor: str = "worker-1") -> None:
        try:
            import redis  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "backend de fila 'redis' exige o extra: pip install 'radar-leilao[redis]'"
            ) from exc
        self._redis = redis.Redis.from_url(url, decode_responses=True)
        self._consumidor = consumidor
        self._grupos_criados: set[str] = set()

    def _garantir_grupo(self, topico: str) -> None:
        if topico in self._grupos_criados:
            return
        try:
            self._redis.xgroup_create(topico, self.GRUPO, id="0", mkstream=True)
        except Exception as exc:  # grupo ja existe
            if "BUSYGROUP" not in str(exc):
                raise
        self._grupos_criados.add(topico)

    def publicar(self, mensagem: Mensagem) -> None:
        self._garantir_grupo(mensagem.topico)
        self._redis.xadd(mensagem.topico, {"dados": mensagem.para_json()})

    def consumir(self, topico: str, limite: int = 100) -> list[Mensagem]:
        self._garantir_grupo(topico)
        resposta = self._redis.xreadgroup(
            self.GRUPO, self._consumidor, {topico: ">"}, count=limite, block=100
        )
        mensagens: list[Mensagem] = []
        for _stream, entradas in resposta or []:
            for id_msg, campos in entradas:
                dados = json.loads(campos["dados"])
                mensagens.append(
                    Mensagem(
                        topico=topico,
                        payload=dados["payload"],
                        id=id_msg,
                        tentativas=dados.get("tentativas", 0) + 1,
                    )
                )
        return mensagens

    def confirmar(self, mensagem: Mensagem) -> None:
        self._redis.xack(mensagem.topico, self.GRUPO, mensagem.id)

    def pendentes(self, topico: str) -> int:
        self._garantir_grupo(topico)
        try:
            return int(self._redis.xlen(topico))
        except Exception:  # pragma: no cover
            return 0


def criar_fila(settings: Settings | None = None) -> FilaIngestao:
    settings = settings or get_settings()
    if settings.fila_backend == "redis":
        return FilaRedisStreams(settings.redis_url)
    return FilaMemoria()
