"""Score de oportunidade (secao 8).

Requisito central: "nunca apenas um numero sem explicacao". Por isso o score
nao e um float solto -- e uma lista de componentes, cada um com seus pontos, seu
maximo e uma frase em portugues dizendo POR QUE ganhou aqueles pontos. A API
devolve a lista inteira e a UI mostra no termometro.

Os pesos sao constantes nomeadas aqui em cima justamente para serem discutiveis:
mudar a politica de ranqueamento e editar este arquivo, nao cacar numeros
magicos espalhados pelo sistema.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from radar.enums import StatusLote, TipoBem
from radar.extraction.campos import LIMIAR_REVISAO
from radar.market.analise import melhor_analise, praca_vigente
from radar.models import Lote, ScoreOportunidade

logger = logging.getLogger(__name__)

VERSAO = "1.0"

PESO_DESCONTO = 40
PESO_QUALIDADE = 20
PESO_RISCO = 25
PESO_JANELA = 10
PESO_HISTORICO = 5

DESCONTO_PARA_NOTA_MAXIMA = Decimal(50)  # 50% de desconto ja vale os 40 pontos

FAIXAS = (
    (80, "ALTA"),
    (60, "BOA"),
    (40, "MODERADA"),
    (0, "BAIXA"),
)

CAMPOS_CHAVE = {
    TipoBem.IMOVEL: (
        "valor_avaliacao", "data_praca_1", "valor_minimo_praca_2",
        "matricula_imovel", "area_total_m2", "ocupado", "endereco",
    ),
    TipoBem.VEICULO: (
        "valor_avaliacao", "data_praca_1", "valor_minimo_praca_2",
        "marca", "modelo", "ano_modelo", "condicao_veiculo",
    ),
    TipoBem.OUTRO: ("valor_avaliacao", "data_praca_1", "valor_minimo_praca_2"),
}

# Risco documental: quanto cada achado tira dos PESO_RISCO pontos iniciais.
PENALIDADES_ONUS = {
    "hipoteca": 5,
    "alienacao_fiduciaria": 6,
    "usufruto": 6,
    "indisponibilidade": 5,
    "inalienabilidade": 6,
    "arresto": 3,
    "penhora": 1,  # a penhora e o que motiva o leilao; risco baixo
    "servidao": 2,
    "arrolamento": 2,
}
PENALIDADES_VEICULO = {
    "sucata": 10,
    "sem_documento": 7,
    "sem_motor": 6,
    "sem_chave": 3,
    "nao_vistoriado": 3,
}


@dataclass(slots=True)
class Componente:
    chave: str
    rotulo: str
    pontos: float
    maximo: int
    explicacao: str

    def para_dict(self) -> dict:
        d = asdict(self)
        d["pontos"] = round(self.pontos, 1)
        return d


def _faixa(total: float) -> str:
    for limite, nome in FAIXAS:
        if total >= limite:
            return nome
    return "BAIXA"


# ---------------------------------------------------------------------------
# Componentes
# ---------------------------------------------------------------------------


def _componente_desconto(lote: Lote) -> Componente:
    analise = melhor_analise(lote)
    if analise is None or analise.desconto_percentual is None:
        return Componente(
            "desconto", "Desconto estimado", 0, PESO_DESCONTO,
            "Sem referência de mercado confiável para este lote, então o desconto "
            "não entra no score. Compare manualmente com imóveis ou veículos "
            "semelhantes antes de decidir.",
        )
    desconto = analise.desconto_percentual
    if desconto <= 0:
        return Componente(
            "desconto", "Desconto estimado", 0, PESO_DESCONTO,
            f"O lance mínimo da praça vigente não está abaixo da referência de "
            f"mercado ({analise.fonte}). Sem desconto, não há oportunidade de preço.",
        )
    proporcao = min(Decimal(desconto) / DESCONTO_PARA_NOTA_MAXIMA, Decimal(1))
    pontos = float(proporcao) * PESO_DESCONTO
    return Componente(
        "desconto", "Desconto estimado", pontos, PESO_DESCONTO,
        f"Lance mínimo {desconto}% abaixo da referência de {analise.fonte} "
        f"(R$ {analise.valor_referencia}). {PESO_DESCONTO} pontos exigem "
        f"{DESCONTO_PARA_NOTA_MAXIMA}% ou mais de desconto.",
    )


def _componente_qualidade(lote: Lote) -> Componente:
    esperados = CAMPOS_CHAVE.get(lote.tipo_bem, CAMPOS_CHAVE[TipoBem.OUTRO])
    confirmados = {
        c.nome for c in lote.campos if c.confianca >= LIMIAR_REVISAO
    }
    achados = [c for c in esperados if c in confirmados]
    proporcao = len(achados) / len(esperados)
    pontos = proporcao * PESO_QUALIDADE
    faltando = [c for c in esperados if c not in confirmados]
    if not lote.documentos:
        return Componente(
            "qualidade_informacao", "Qualidade da informação", pontos * 0.5, PESO_QUALIDADE,
            "Nenhum edital foi analisado para este lote — os dados vêm só da "
            "listagem do leiloeiro, sem confirmação documental.",
        )
    explicacao = (
        f"{len(achados)} de {len(esperados)} campos-chave confirmados no edital "
        f"com confiança suficiente."
    )
    if faltando:
        explicacao += " Não confirmados: " + ", ".join(faltando[:4]) + "."
    return Componente(
        "qualidade_informacao", "Qualidade da informação", pontos, PESO_QUALIDADE, explicacao
    )


def _componente_risco(lote: Lote) -> Componente:
    pontos = float(PESO_RISCO)
    motivos: list[str] = []

    if lote.ocupado is True:
        pontos -= 9
        motivos.append("imóvel ocupado (imissão na posse costuma exigir ação judicial)")
    elif lote.ocupado is None and lote.tipo_bem is TipoBem.IMOVEL:
        pontos -= 3
        motivos.append("situação de ocupação não informada")

    for onus in lote.onus or []:
        penalidade = PENALIDADES_ONUS.get(str(onus).strip().lower(), 2)
        pontos -= penalidade
        motivos.append(f"ônus: {str(onus).replace('_', ' ')}")

    for condicao in lote.condicao_veiculo or []:
        penalidade = PENALIDADES_VEICULO.get(str(condicao).strip().lower(), 3)
        pontos -= penalidade
        motivos.append(f"veículo {str(condicao).replace('_', ' ')}")

    campos = {c.nome: c for c in lote.campos}
    atribui = campos.get("edital_atribui_debitos_ao_arrematante")
    if atribui is not None and atribui.valor_booleano:
        pontos -= 4
        motivos.append("o edital atribui débitos ao arrematante")
    sub_roga = campos.get("edital_invoca_sub_rogacao_no_preco")
    if sub_roga is not None and sub_roga.valor_booleano:
        pontos += 2
        motivos.append(
            "o edital invoca sub-rogação no preço para débitos tributários "
            "(confirme o alcance com seu advogado)"
        )

    if lote.tipo_bem is TipoBem.IMOVEL and not lote.matricula:
        pontos -= 3
        motivos.append("matrícula do imóvel não identificada")

    pontos = max(0.0, min(pontos, float(PESO_RISCO)))
    if not motivos:
        explicacao = (
            "Nenhum ônus, dívida ou restrição foi encontrado no que analisamos. "
            "Isso não garante que não exista — confirme na matrícula atualizada."
        )
    else:
        explicacao = "Riscos encontrados: " + "; ".join(motivos[:5]) + "."
    return Componente("risco_documental", "Risco documental", pontos, PESO_RISCO, explicacao)


def _componente_janela(lote: Lote, agora: datetime | None = None) -> Componente:
    agora = agora or datetime.now(UTC)
    vigente = praca_vigente(lote, agora)
    if vigente is None or vigente.data_hora is None:
        return Componente(
            "janela_tempo", "Janela de decisão", 0, PESO_JANELA,
            "Sem data de praça conhecida — não dá para dizer quanto tempo resta.",
        )
    if vigente.ja_passou:
        return Componente(
            "janela_tempo", "Janela de decisão", 0, PESO_JANELA,
            "A última praça conhecida já ocorreu. O lote pode estar encerrado; "
            "confirme na fonte antes de agir.",
        )
    dias = (vigente.data_hora - agora).days
    if dias <= 3:
        pontos, texto = PESO_JANELA, "menos de 3 dias — decisão urgente"
    elif dias <= 15:
        pontos, texto = PESO_JANELA * 0.8, f"{dias} dias — prazo curto"
    elif dias <= 45:
        pontos, texto = PESO_JANELA * 0.5, f"{dias} dias — dá tempo de visitar e pesquisar"
    else:
        pontos, texto = PESO_JANELA * 0.3, f"{dias} dias — ainda distante"
    return Componente(
        "janela_tempo", "Janela de decisão", pontos, PESO_JANELA,
        f"Faltam {texto} para a {vigente.ordem}ª praça. Pontuação maior significa "
        "mais urgência, não mais qualidade do lote.",
    )


def _componente_historico(sessao: Session, lote: Lote) -> Componente:
    leiloeiro = lote.leilao.leiloeiro if lote.leilao else None
    if leiloeiro is None:
        return Componente(
            "historico", "Histórico do leiloeiro", PESO_HISTORICO * 0.5, PESO_HISTORICO,
            "Leiloeiro não identificado neste lote — histórico não avaliado.",
        )
    total = sessao.scalar(
        select(func.count(Lote.id))
        .join(Lote.leilao)
        .where(
            Lote.leilao.has(leiloeiro_id=leiloeiro.id),
            Lote.status.in_([StatusLote.ARREMATADO, StatusLote.DESERTO, StatusLote.SUSPENSO]),
        )
    ) or 0
    if total < 5:
        return Componente(
            "historico", "Histórico do leiloeiro", PESO_HISTORICO * 0.5, PESO_HISTORICO,
            f"Ainda não há histórico suficiente de {leiloeiro.nome} na nossa base "
            f"({total} lotes encerrados). Pontuação neutra.",
        )
    ruins = sessao.scalar(
        select(func.count(Lote.id))
        .join(Lote.leilao)
        .where(
            Lote.leilao.has(leiloeiro_id=leiloeiro.id),
            Lote.status.in_([StatusLote.DESERTO, StatusLote.SUSPENSO]),
        )
    ) or 0
    taxa = ruins / total
    pontos = max(0.0, (1 - taxa)) * PESO_HISTORICO
    return Componente(
        "historico", "Histórico do leiloeiro", pontos, PESO_HISTORICO,
        f"{leiloeiro.nome}: {ruins} de {total} lotes encerrados ficaram desertos ou "
        f"suspensos ({taxa:.0%}).",
    )


# ---------------------------------------------------------------------------
# Calculo
# ---------------------------------------------------------------------------


def calcular(
    sessao: Session, lote: Lote, agora: datetime | None = None
) -> ScoreOportunidade:
    componentes = [
        _componente_desconto(lote),
        _componente_qualidade(lote),
        _componente_risco(lote),
        _componente_janela(lote, agora),
        _componente_historico(sessao, lote),
    ]
    total = round(sum(c.pontos for c in componentes), 1)

    score = lote.score
    if score is None:
        score = ScoreOportunidade(lote_id=lote.id, lote=lote)
        sessao.add(score)
    score.total = total
    score.faixa = _faixa(total)
    score.componentes = [c.para_dict() for c in componentes]
    score.versao = VERSAO
    score.calculado_em = agora or datetime.now(UTC)
    return score


def recalcular_todos(sessao: Session, limite: int | None = None) -> int:
    consulta = select(Lote)
    if limite:
        consulta = consulta.limit(limite)
    total = 0
    for lote in sessao.scalars(consulta):
        calcular(sessao, lote)
        total += 1
    sessao.flush()
    return total
