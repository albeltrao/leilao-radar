"""Referencia FIPE para veiculos (secao 4.5).

A FIPE nao publica API oficial gratuita e estavel. Por isso o acesso e por tras
de uma interface: o padrao e um espelho local (CSV carregado no banco), e um
provedor HTTP pode ser ligado por configuracao sem mexer no resto do sistema.

O valor FIPE e uma REFERENCIA de mercado para veiculo em estado normal de uso.
Veiculo de leilao costuma valer menos: sinistro, falta de chave, documentacao
pendente, meses parado em patio. Nunca apresentamos FIPE como o valor que o bem
vale -- a analise devolve a metodologia junto, e o score penaliza as condicoes
encontradas no edital.
"""

from __future__ import annotations

import csv
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from radar.config import Settings, get_settings
from radar.models import ReferenciaFipe
from radar.normalizacao import normalizar_texto

logger = logging.getLogger(__name__)

ARQUIVO_ESPELHO = Path(__file__).resolve().parents[1] / "data" / "fipe_espelho_demo.csv"

_RUIDO = {
    "flex", "4p", "5p", "2p", "aut", "mec", "16v", "12v", "8v", "v", "cv",
    "gasolina", "alcool", "diesel", "turbo", "mpi", "tsi", "fire",
}


@dataclass(frozen=True, slots=True)
class ValorFipe:
    codigo_fipe: str
    marca: str
    modelo: str
    ano_modelo: int
    valor: Decimal
    mes_referencia: str
    combustivel: str | None = None
    similaridade: float = 1.0
    demonstracao: bool = False

    @property
    def data_referencia(self) -> datetime | None:
        try:
            ano, mes = self.mes_referencia.split("-")
            return datetime(int(ano), int(mes), 1, tzinfo=UTC)
        except (ValueError, AttributeError):
            return None


def _tokens(texto: str | None) -> set[str]:
    if not texto:
        return set()
    bruto = re.split(r"[^a-z0-9.]+", normalizar_texto(texto))
    return {t for t in bruto if t and t not in _RUIDO and len(t) > 1}


def similaridade(consulta: str, candidato: str) -> float:
    """Jaccard sobre tokens significativos. Simples e previsivel."""
    a, b = _tokens(consulta), _tokens(candidato)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class ProvedorFipe(ABC):
    @abstractmethod
    def consultar(
        self, marca: str | None, modelo: str | None, ano_modelo: int | None
    ) -> ValorFipe | None: ...


class ProvedorEspelhoLocal(ProvedorFipe):
    """Le a tabela do banco (carregada por ``radar mercado importar-fipe``)."""

    LIMIAR_SIMILARIDADE = 0.34

    def __init__(self, sessao: Session) -> None:
        self.sessao = sessao

    def consultar(self, marca, modelo, ano_modelo):  # noqa: D102
        if not modelo:
            return None
        consulta = select(ReferenciaFipe)
        if ano_modelo:
            consulta = consulta.where(ReferenciaFipe.ano_modelo == ano_modelo)
        if marca:
            consulta = consulta.where(
                ReferenciaFipe.marca == normalizar_texto(marca).upper()
            )
        candidatos = list(self.sessao.scalars(consulta))
        if not candidatos and marca:
            # Marca pode estar escrita diferente ("VW" x "VOLKSWAGEN"): tenta sem ela.
            candidatos = list(self.sessao.scalars(select(ReferenciaFipe)))

        alvo = f"{marca or ''} {modelo}"
        melhor, melhor_score = None, 0.0
        for candidato in candidatos:
            score = similaridade(alvo, f"{candidato.marca} {candidato.modelo}")
            if ano_modelo and candidato.ano_modelo != ano_modelo:
                score *= 0.6  # ano diferente ainda serve, mas vale menos
            if score > melhor_score:
                melhor, melhor_score = candidato, score

        if melhor is None or melhor_score < self.LIMIAR_SIMILARIDADE:
            return None
        return ValorFipe(
            codigo_fipe=melhor.codigo_fipe,
            marca=melhor.marca,
            modelo=melhor.modelo,
            ano_modelo=melhor.ano_modelo,
            valor=melhor.valor,
            mes_referencia=melhor.mes_referencia,
            combustivel=melhor.combustivel,
            similaridade=round(melhor_score, 3),
            # Por linha: um banco com espelho real e amostra ao mesmo tempo
            # responde conforme a referencia que de fato casou.
            demonstracao=bool(melhor.demonstracao),
        )


class ProvedorHttp(ProvedorFipe):  # pragma: no cover - exige rede
    """Provedor externo (ex.: fipe.api.br). Requer contrato/SLA proprio."""

    def __init__(self, base_url: str, user_agent: str, cliente=None) -> None:
        import httpx  # noqa: PLC0415

        self._cliente = cliente or httpx.Client(
            base_url=base_url, headers={"User-Agent": user_agent}, timeout=20.0
        )

    def consultar(self, marca, modelo, ano_modelo):  # noqa: D102
        if not (marca and modelo):
            return None
        try:
            resposta = self._cliente.get(
                "/carros/buscar", params={"marca": marca, "modelo": modelo, "ano": ano_modelo}
            )
            resposta.raise_for_status()
            dados = resposta.json()
        except Exception as exc:
            logger.warning("provedor FIPE indisponivel: %s", exc)
            return None
        if not dados:
            return None
        item = dados[0] if isinstance(dados, list) else dados
        from radar.normalizacao import parse_moeda  # noqa: PLC0415

        valor = parse_moeda(str(item.get("valor")))
        if valor is None:
            return None
        return ValorFipe(
            codigo_fipe=str(item.get("codigoFipe", "")),
            marca=str(item.get("marca", marca)),
            modelo=str(item.get("modelo", modelo)),
            ano_modelo=int(item.get("anoModelo", ano_modelo or 0)),
            valor=valor,
            mes_referencia=str(item.get("mesReferencia", "")),
            combustivel=item.get("combustivel"),
        )


def criar_provedor(sessao: Session, settings: Settings | None = None) -> ProvedorFipe:
    settings = settings or get_settings()
    if settings.fipe_provider == "fipe_api_br":  # pragma: no cover
        return ProvedorHttp(settings.fipe_api_base, settings.user_agent)
    return ProvedorEspelhoLocal(sessao)


def carregar_espelho(
    sessao: Session, caminho: Path | None = None
) -> int:
    """Importa um CSV de espelho FIPE. Idempotente por (codigo, ano, mes)."""
    arquivo = caminho or ARQUIVO_ESPELHO
    if not arquivo.exists():
        logger.warning("espelho FIPE nao encontrado: %s", arquivo)
        return 0
    importados = 0
    with arquivo.open(encoding="utf-8") as fh:
        linhas = (linha for linha in fh if not linha.startswith("#"))
        for registro in csv.DictReader(linhas):
            chave = (
                registro["codigo_fipe"],
                int(registro["ano_modelo"]),
                registro["mes_referencia"],
            )
            existente = sessao.scalar(
                select(ReferenciaFipe).where(
                    ReferenciaFipe.codigo_fipe == chave[0],
                    ReferenciaFipe.ano_modelo == chave[1],
                    ReferenciaFipe.mes_referencia == chave[2],
                )
            )
            demonstracao = str(registro.get("demonstracao", "")).strip().lower() in {
                "1", "sim", "true", "demonstracao", "demonstração"
            }
            if existente is not None:
                existente.valor = Decimal(registro["valor"])
                existente.demonstracao = demonstracao
                continue
            sessao.add(
                ReferenciaFipe(
                    codigo_fipe=registro["codigo_fipe"],
                    marca=registro["marca"].upper(),
                    modelo=registro["modelo"],
                    modelo_normalizado=normalizar_texto(registro["modelo"]),
                    ano_modelo=int(registro["ano_modelo"]),
                    combustivel=registro.get("combustivel"),
                    valor=Decimal(registro["valor"]),
                    mes_referencia=registro["mes_referencia"],
                    demonstracao=demonstracao,
                )
            )
            importados += 1
    sessao.flush()
    return importados
