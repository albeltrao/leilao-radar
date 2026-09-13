"""Achado de extracao: um campo, com confianca e evidencia.

Regra da secao 7.4, que nao pode ser relaxada em nenhum ponto do sistema: nada
extraido automaticamente e apresentado como certeza. Todo achado carrega
``confianca``, ``evidencia`` (o trecho literal do documento) e o metodo. Abaixo
de ``LIMIAR_REVISAO`` a UI mostra "nao confirmado -- conferir edital original".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from radar.enums import MetodoExtracao

LIMIAR_REVISAO = 0.70

# Confianca por qualidade do casamento.
CONF_ROTULO_EXPLICITO = 0.92  # "Valor da avaliação: R$ X" -- rotulo inequivoco
CONF_ROTULO_AMBIGUO = 0.65  # rotulo presente, mas varios candidatos no texto
CONF_INFERIDO = 0.45  # deduzido do contexto, sem rotulo
CONF_ACORDO_REGRA_LLM = 0.97  # parser e modelo chegaram ao mesmo valor
CONF_SO_LLM = 0.60  # so o modelo viu; sempre vai para revisao


@dataclass(slots=True)
class Achado:
    nome: str
    confianca: float
    evidencia: str
    metodo: MetodoExtracao = MetodoExtracao.REGRA
    valor_texto: str | None = None
    valor_numerico: Decimal | None = None
    valor_data: datetime | None = None
    valor_booleano: bool | None = None

    @property
    def revisao_necessaria(self) -> bool:
        return self.confianca < LIMIAR_REVISAO

    @property
    def valor(self):
        for candidato in (
            self.valor_numerico,
            self.valor_data,
            self.valor_booleano,
            self.valor_texto,
        ):
            if candidato is not None:
                return candidato
        return None

    def __post_init__(self) -> None:
        self.confianca = max(0.0, min(1.0, float(self.confianca)))
        if len(self.evidencia) > 600:
            self.evidencia = self.evidencia[:597] + "..."


@dataclass(slots=True)
class ResultadoExtracao:
    achados: list[Achado] = field(default_factory=list)
    parser_versao: str | None = None
    prompt_versao: str | None = None
    avisos: list[str] = field(default_factory=list)

    def por_nome(self) -> dict[str, Achado]:
        return {a.nome: a for a in self.achados}

    def obter(self, nome: str) -> Achado | None:
        return self.por_nome().get(nome)

    @property
    def confianca_media(self) -> float:
        if not self.achados:
            return 0.0
        return round(sum(a.confianca for a in self.achados) / len(self.achados), 3)

    @property
    def campos_para_revisao(self) -> list[Achado]:
        return [a for a in self.achados if a.revisao_necessaria]
