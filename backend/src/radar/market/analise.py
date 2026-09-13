"""Motor de comparacao com valor de mercado (secao 4.5).

Produz uma ou mais AnaliseMercado por lote, cada uma com fonte, metodologia,
data de referencia e avisos explicitos. A regra que atravessa o modulo inteiro:
nenhum numero sai daqui sem dizer de onde veio e quao velho e.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from radar.config import Settings, get_settings
from radar.enums import FonteMercado, TipoBem
from radar.market import fipezap
from radar.market.fipe import criar_provedor
from radar.models import AnaliseMercado, Lote

logger = logging.getLogger(__name__)

CEM = Decimal(100)


@dataclass(frozen=True, slots=True)
class PracaVigente:
    ordem: int
    valor_minimo: Decimal | None
    data_hora: datetime | None
    ja_passou: bool


def praca_vigente(lote: Lote, agora: datetime | None = None) -> PracaVigente | None:
    """A praca que o comprador enfrenta agora: a proxima ainda por acontecer.

    Importa para o desconto: enquanto a 1a praca nao ocorreu, o lance minimo e o
    valor de avaliacao (desconto zero). O desconto real so aparece na 2a.
    """
    agora = agora or datetime.now(UTC)
    if lote.leilao is None or not lote.leilao.pracas:
        return None
    minimos = {1: lote.valor_minimo_primeira, 2: lote.valor_minimo_segunda}
    futuras = [
        p for p in sorted(lote.leilao.pracas, key=lambda x: x.ordem)
        if p.data_hora is not None and p.data_hora > agora
    ]
    escolhida = futuras[0] if futuras else None
    if escolhida is None:
        com_data = [p for p in lote.leilao.pracas if p.data_hora is not None]
        if not com_data:
            return None
        escolhida = max(com_data, key=lambda x: x.data_hora)
        return PracaVigente(
            escolhida.ordem, minimos.get(escolhida.ordem), escolhida.data_hora, True
        )
    return PracaVigente(escolhida.ordem, minimos.get(escolhida.ordem), escolhida.data_hora, False)


def _desconto(referencia: Decimal, comparado: Decimal) -> Decimal:
    if referencia <= 0:
        return Decimal(0)
    return ((referencia - comparado) / referencia * CEM).quantize(Decimal("0.01"))


def analisar(
    sessao: Session, lote: Lote, settings: Settings | None = None
) -> list[AnaliseMercado]:
    """Recalcula todas as analises do lote. Idempotente (uma linha por fonte)."""
    settings = settings or get_settings()
    vigente = praca_vigente(lote)
    if vigente is None or vigente.valor_minimo is None:
        return []

    producoes = [
        _analise_laudo(lote, vigente),
        _analise_fipe(sessao, lote, vigente, settings),
        _analise_fipezap(sessao, lote, vigente),
    ]

    existentes = {a.fonte: a for a in lote.analises}
    resultado: list[AnaliseMercado] = []
    for nova in producoes:
        if nova is None:
            continue
        atual = existentes.get(nova.fonte)
        if atual is None:
            nova.lote_id = lote.id
            nova.lote = lote
            sessao.add(nova)
            resultado.append(nova)
            continue
        for campo in (
            "valor_referencia", "valor_comparado", "praca_base", "desconto_percentual",
            "data_referencia_fonte", "metodologia", "fonte_url", "avisos", "confianca",
        ):
            setattr(atual, campo, getattr(nova, campo))
        atual.calculado_em = datetime.now(UTC)
        resultado.append(atual)
    return resultado


def _analise_laudo(lote: Lote, vigente: PracaVigente) -> AnaliseMercado | None:
    """Comparacao sempre disponivel: lance minimo x avaliacao judicial.

    E a referencia primaria da secao 4.5 item 3. Tambem a mais honesta: o laudo
    foi feito para aquele bem especifico. O risco e a idade do laudo.
    """
    if lote.valor_avaliacao is None or lote.valor_avaliacao <= 0:
        return None
    avisos = [
        "O valor de avaliação vem do laudo judicial e pode estar defasado em "
        "relação ao mercado — confira a data do laudo no edital.",
    ]
    if vigente.ja_passou:
        avisos.append("A praça usada como base já ocorreu; o lote pode estar encerrado.")
    return AnaliseMercado(
        fonte=FonteMercado.LAUDO_JUDICIAL,
        valor_referencia=lote.valor_avaliacao,
        valor_comparado=vigente.valor_minimo,
        praca_base=vigente.ordem,
        desconto_percentual=_desconto(lote.valor_avaliacao, vigente.valor_minimo),
        data_referencia_fonte=None,
        metodologia=(
            f"Desconto sobre a avaliação judicial: lance mínimo da {vigente.ordem}ª praça "
            f"({vigente.valor_minimo}) comparado ao valor de avaliação "
            f"({lote.valor_avaliacao}) constante do edital."
        ),
        fonte_url=lote.fonte_url,
        avisos=avisos,
        confianca=0.85,
    )


def _analise_fipe(
    sessao: Session, lote: Lote, vigente: PracaVigente, settings: Settings
) -> AnaliseMercado | None:
    if lote.tipo_bem is not TipoBem.VEICULO:
        return None
    provedor = criar_provedor(sessao, settings)
    valor = provedor.consultar(lote.marca, lote.modelo, lote.ano_modelo)
    if valor is None:
        return None

    avisos = [
        "A tabela FIPE é referência para veículo em estado normal de uso. "
        "Veículo de leilão costuma ter deságio adicional.",
    ]
    confianca = 0.80 * valor.similaridade
    if valor.similaridade < 0.6:
        avisos.append(
            f"O modelo do edital foi casado por aproximação com “{valor.modelo}” "
            f"(similaridade {valor.similaridade}). Confira se é o mesmo veículo."
        )
    if lote.condicao_veiculo:
        avisos.append(
            "O edital aponta " + ", ".join(lote.condicao_veiculo).replace("_", " ")
            + " — isso reduz o valor real abaixo da FIPE."
        )
        confianca *= 0.8
    if valor.demonstracao:
        avisos.insert(
            0,
            "ATENÇÃO: valor de referência de DEMONSTRAÇÃO. Carregue um espelho FIPE "
            "real com `radar mercado importar-fipe` antes de usar em decisão.",
        )
        confianca *= 0.5

    return AnaliseMercado(
        fonte=FonteMercado.FIPE,
        valor_referencia=valor.valor,
        valor_comparado=vigente.valor_minimo,
        praca_base=vigente.ordem,
        desconto_percentual=_desconto(valor.valor, vigente.valor_minimo),
        data_referencia_fonte=valor.data_referencia,
        metodologia=(
            f"FIPE {valor.codigo_fipe} — {valor.marca} {valor.modelo} "
            f"{valor.ano_modelo}, referência {valor.mes_referencia}. "
            f"Comparado ao lance mínimo da {vigente.ordem}ª praça."
        ),
        fonte_url="https://veiculos.fipe.org.br",
        avisos=avisos,
        confianca=round(min(confianca, 0.9), 3),
    )


def _analise_fipezap(
    sessao: Session, lote: Lote, vigente: PracaVigente
) -> AnaliseMercado | None:
    if lote.tipo_bem is not TipoBem.IMOVEL:
        return None
    # O indice e calculado sobre area util; area total infla a referencia.
    area = lote.area_privativa_m2 or lote.area_total_m2
    if area is None or area <= 0:
        return None
    indice = fipezap.consultar(sessao, lote.uf, lote.cidade, lote.bairro)
    if indice is None:
        return None

    referencia = (indice.valor_m2 * area).quantize(Decimal("0.01"))
    avisos = [
        "O FipeZap mede preço de ANÚNCIO por m², não preço de venda fechado.",
    ]
    confianca = 0.70 if indice.precisao == "BAIRRO" else 0.55
    if lote.area_privativa_m2 is None:
        avisos.append(
            "Usada a área total por falta de área privativa no edital; o índice é "
            "calculado sobre área útil, então a referência tende a ficar superestimada."
        )
        confianca *= 0.8
    if indice.precisao == "CIDADE" and lote.bairro:
        avisos.append(
            f"Não há índice para o bairro {lote.bairro}; usada a média da cidade."
        )
    if indice.demonstracao:
        avisos.insert(
            0,
            "ATENÇÃO: índice de DEMONSTRAÇÃO. Importe o boletim FipeZap real com "
            "`radar mercado importar-fipezap` antes de usar em decisão.",
        )
        confianca *= 0.5

    return AnaliseMercado(
        fonte=FonteMercado.FIPEZAP,
        valor_referencia=referencia,
        valor_comparado=vigente.valor_minimo,
        praca_base=vigente.ordem,
        desconto_percentual=_desconto(referencia, vigente.valor_minimo),
        data_referencia_fonte=indice.data_referencia,
        metodologia=(
            f"{area} m² × R$ {indice.valor_m2}/m² (FipeZap, {indice.rotulo}, "
            f"precisão {indice.precisao.lower()}) = R$ {referencia}. "
            f"Comparado ao lance mínimo da {vigente.ordem}ª praça."
        ),
        fonte_url=fipezap.FONTE_URL,
        avisos=avisos,
        confianca=round(confianca, 3),
    )


def melhor_analise(lote: Lote) -> AnaliseMercado | None:
    """A analise que a UI destaca: maior confianca, desempate pelo desconto."""
    if not lote.analises:
        return None
    return max(
        lote.analises,
        key=lambda a: (a.confianca, a.desconto_percentual or Decimal(0)),
    )


def custo_total_estimado(
    lote: Lote, valor_lance: Decimal | None = None
) -> tuple[Decimal | None, list[str]]:
    """Lance + comissao + debitos que o edital atribui ao arrematante.

    Estimativa de caixa, nao parecer: a lista de avisos diz o que entrou e o que
    ficou de fora (ITBI, registro, custas e reforma nao estao aqui).
    """
    base = valor_lance or lote.valor_minimo_segunda or lote.valor_minimo_primeira
    if base is None:
        return None, ["sem lance mínimo conhecido para simular"]
    total = Decimal(base)
    detalhes = [f"lance base R$ {base}"]
    if lote.comissao_leiloeiro_percentual:
        comissao = (total * lote.comissao_leiloeiro_percentual / CEM).quantize(Decimal("0.01"))
        total += comissao
        detalhes.append(f"comissão do leiloeiro {lote.comissao_leiloeiro_percentual}% = R$ {comissao}")
    else:
        detalhes.append("comissão do leiloeiro não informada no edital")
    for debito in lote.debitos or []:
        valor = debito.get("valor")
        if valor:
            total += Decimal(str(valor))
            detalhes.append(f"débito de {debito.get('tipo')} R$ {valor}")
    detalhes.append(
        "Não inclui ITBI, custas de registro, despesas de imissão na posse nem reforma."
    )
    return total.quantize(Decimal("0.01")), detalhes
