"""Cliente da API Publica do DataJud (CNJ) -- secao 4.4.

Dois usos, como o spec pede:

a) **enriquecer** um lote que ja temos com o andamento do processo de execucao;
b) **descobrir** processos com movimentacao tipica de hasta publica antes de o
   leiloeiro publicar o edital.

E uma API oficial e documentada -- por isso ela tem preferencia sobre scraping
(secao 11). Sem ``RADAR_DATAJUD_API_KEY`` o modulo se desliga sozinho e o resto
do pipeline continua funcionando.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from radar.collectors.base import Conector, MetadadosFonte, registrar
from radar.collectors.dto import LoteBruto, ResultadoConector
from radar.collectors.http import ErroColeta, Fetcher
from radar.config import Settings, get_settings
from radar.enums import TipoFonte
from radar.jurisdicoes import INDICES_DATAJUD, SIGLAS, UF_POR_TRIBUNAL
from radar.normalizacao import extrair_numero_cnj, limpar_espacos, normalizar_texto

logger = logging.getLogger(__name__)

# Indices por tribunal na API publica, derivados da tabela de jurisdicoes.
INDICES = dict(INDICES_DATAJUD)

# O DataJud nao expoe um filtro "tem leilao designado". Casamos pelo NOME do
# movimento da Tabela Processual Unificada, que e texto estavel o bastante.
# Se/quando os codigos TPU forem confirmados, troque por filtro de codigo --
# fica mais barato e mais preciso.
TERMOS_HASTA = ("leilão", "leilao", "hasta pública", "hasta publica", "praça", "praca", "alienação judicial")


class DataJudDesabilitado(ErroColeta):
    """Sem chave de API configurada."""


@dataclass(slots=True)
class ProcessoDataJud:
    numero_cnj: str
    tribunal: str | None = None
    classe: str | None = None
    assunto: str | None = None
    orgao_julgador: str | None = None
    grau: str | None = None
    data_ajuizamento: datetime | None = None
    movimentos: list[dict] = field(default_factory=list)

    @property
    def tem_movimento_de_hasta(self) -> bool:
        for mov in self.movimentos:
            nome = normalizar_texto(str(mov.get("nome", "")))
            if any(normalizar_texto(t) in nome for t in TERMOS_HASTA):
                return True
        return False

    @property
    def ultimo_movimento(self) -> dict | None:
        if not self.movimentos:
            return None
        return max(self.movimentos, key=lambda m: str(m.get("dataHora", "")))


def _parse_data(valor: Any) -> datetime | None:
    if not valor:
        return None
    texto = str(valor).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class ClienteDataJud:
    def __init__(self, settings: Settings | None = None, cliente: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._cliente = cliente
        self._proprio = cliente is None

    @property
    def habilitado(self) -> bool:
        return bool(self.settings.datajud_api_key)

    @property
    def cliente(self) -> httpx.Client:
        if self._cliente is None:
            self._cliente = httpx.Client(
                timeout=self.settings.timeout_http_s,
                headers={
                    "Authorization": f"APIKey {self.settings.datajud_api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": self.settings.user_agent,
                },
            )
        return self._cliente

    def _buscar(self, tribunal: str, corpo: dict) -> dict:
        if not self.habilitado:
            raise DataJudDesabilitado(
                "RADAR_DATAJUD_API_KEY nao configurada: enriquecimento processual desligado"
            )
        indice = INDICES.get(tribunal.upper())
        if indice is None:
            raise ErroColeta(f"tribunal fora do escopo do DataJud no Radar: {tribunal}")
        url = f"{self.settings.datajud_base_url.rstrip('/')}/{indice}/_search"
        resposta = self.cliente.post(url, json=corpo)
        if resposta.status_code == 401:
            raise ErroColeta("DataJud recusou a chave de API (401)")
        resposta.raise_for_status()
        return resposta.json()

    @staticmethod
    def _para_processo(fonte: dict) -> ProcessoDataJud:
        orgao = fonte.get("orgaoJulgador") or {}
        assuntos = fonte.get("assuntos") or []
        return ProcessoDataJud(
            numero_cnj=extrair_numero_cnj(str(fonte.get("numeroProcesso", "")))
            or str(fonte.get("numeroProcesso", "")),
            tribunal=fonte.get("tribunal"),
            classe=(fonte.get("classe") or {}).get("nome"),
            assunto=assuntos[0].get("nome") if assuntos else None,
            orgao_julgador=orgao.get("nome") if isinstance(orgao, dict) else None,
            grau=fonte.get("grau"),
            data_ajuizamento=_parse_data(fonte.get("dataAjuizamento")),
            movimentos=fonte.get("movimentos") or [],
        )

    def consultar_processo(self, numero_cnj: str, tribunal: str) -> ProcessoDataJud | None:
        """Metadados de um processo. Retorna None quando nao encontrado."""
        digitos = "".join(c for c in numero_cnj if c.isdigit())
        corpo = {"size": 1, "query": {"match": {"numeroProcesso": digitos}}}
        dados = self._buscar(tribunal, corpo)
        hits = dados.get("hits", {}).get("hits", [])
        if not hits:
            return None
        return self._para_processo(hits[0].get("_source", {}))

    def descobrir_hastas(
        self, tribunal: str, desde_dias: int = 30, limite: int = 200
    ) -> list[ProcessoDataJud]:
        """Processos com movimentacao recente que menciona leilao/hasta/praca."""
        desde = (datetime.now(UTC) - timedelta(days=desde_dias)).date().isoformat()
        corpo = {
            "size": limite,
            "query": {
                "bool": {
                    "must": [
                        {
                            "nested": {
                                "path": "movimentos",
                                "query": {
                                    "bool": {
                                        "should": [
                                            {"match_phrase": {"movimentos.nome": termo}}
                                            for termo in TERMOS_HASTA
                                        ],
                                        "minimum_should_match": 1,
                                    }
                                },
                            }
                        }
                    ],
                    "filter": [{"range": {"dataHoraUltimaAtualizacao": {"gte": desde}}}],
                }
            },
        }
        dados = self._buscar(tribunal, corpo)
        hits = dados.get("hits", {}).get("hits", [])
        return [self._para_processo(h.get("_source", {})) for h in hits]

    def fechar(self) -> None:
        if self._proprio and self._cliente is not None:
            self._cliente.close()


META = MetadadosFonte(
    slug="datajud-hastas",
    nome="CNJ DataJud - descoberta de hastas",
    tipo=TipoFonte.PROCESSUAL,
    uf=None,
    url_alvo="https://api-publica.datajud.cnj.jus.br",
    periodicidade_horas=24,
    descricao=(
        "API publica do CNJ. Descobre processos das UFs cobertas com movimentacao de "
        "leilao/hasta/praca, antes mesmo de o edital sair no site do leiloeiro."
    ),
)


class ConectorDataJud(Conector):
    meta = META

    def __init__(self, tribunais: tuple[str, ...] = SIGLAS) -> None:
        self.tribunais = tribunais

    def coletar(self, fetcher: Fetcher) -> ResultadoConector:
        resultado = ResultadoConector()
        cliente = ClienteDataJud(fetcher.settings)
        if not cliente.habilitado:
            resultado.avisos.append(
                "DataJud sem chave de API: descoberta processual pulada (nao e erro)"
            )
            return resultado
        try:
            for tribunal in self.tribunais:
                for processo in cliente.descobrir_hastas(tribunal):
                    if not processo.tem_movimento_de_hasta:
                        continue
                    resultado.paginas_visitadas += 1
                    resultado.lotes.append(self._para_lote(processo, tribunal))
        finally:
            cliente.fechar()
        return resultado

    def _para_lote(self, processo: ProcessoDataJud, tribunal: str) -> LoteBruto:
        """Lote "semente": sinaliza que ha hasta designada, sem detalhe do bem.

        O bem so aparece quando o edital do leiloeiro for coletado e extraido --
        ate la o registro fica visivel apenas como sinal de calendario.
        """
        ultimo = processo.ultimo_movimento or {}
        uf = UF_POR_TRIBUNAL[tribunal]
        return LoteBruto(
            fonte_slug=self.slug,
            fonte_url=f"{self.meta.url_alvo}/{INDICES[tribunal]}",
            titulo=limpar_espacos(
                f"Hasta publica sinalizada - {processo.classe or 'processo'} "
                f"({processo.orgao_julgador or tribunal})"
            )[:300],
            descricao=limpar_espacos(str(ultimo.get("nome") or "")),
            numero_processo=processo.numero_cnj,
            tribunal_sigla=tribunal,
            uf=uf,
            vara=processo.orgao_julgador,
            extras={
                "origem": "datajud",
                "somente_sinal": True,
                "assunto": processo.assunto,
                "grau": processo.grau,
            },
        )


CONECTOR = registrar(ConectorDataJud())
