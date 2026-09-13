"""Combina o que a regra extraiu com o que o modelo extraiu (secao 7.4).

Politica, em uma frase: concordancia sobe a confianca, discordancia derruba e
manda revisar, e a regra nunca e sobrescrita em silencio pelo modelo.

Isso importa porque um valor errado aqui vira um desconto errado na secao 8 e um
score errado na tela. Preferimos "conferir no edital" a um numero bonito e falso.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from radar.enums import MetodoExtracao
from radar.extraction.campos import (
    CONF_ACORDO_REGRA_LLM,
    CONF_ROTULO_AMBIGUO,
    Achado,
    ResultadoExtracao,
)
from radar.normalizacao import normalizar_texto

TOLERANCIA_DATA = timedelta(minutes=1)


def _concordam(a: Achado, b: Achado) -> bool:
    if a.valor_numerico is not None and b.valor_numerico is not None:
        maior = max(abs(a.valor_numerico), abs(b.valor_numerico), Decimal("0.01"))
        return abs(a.valor_numerico - b.valor_numerico) / maior < Decimal("0.005")
    if a.valor_data is not None and b.valor_data is not None:
        return abs(a.valor_data - b.valor_data) <= TOLERANCIA_DATA
    if a.valor_booleano is not None and b.valor_booleano is not None:
        return a.valor_booleano is b.valor_booleano
    if a.valor_texto and b.valor_texto:
        x, y = normalizar_texto(a.valor_texto), normalizar_texto(b.valor_texto)
        return x == y or x in y or y in x
    return False


def combinar(
    da_regra: ResultadoExtracao, do_llm: ResultadoExtracao
) -> ResultadoExtracao:
    combinado = ResultadoExtracao(
        parser_versao=da_regra.parser_versao,
        prompt_versao=do_llm.prompt_versao,
        avisos=[*da_regra.avisos, *do_llm.avisos],
    )
    por_regra = da_regra.por_nome()
    por_llm = do_llm.por_nome()

    for nome, achado in por_regra.items():
        do_modelo = por_llm.pop(nome, None)
        if do_modelo is None:
            combinado.achados.append(achado)
            continue

        if _concordam(achado, do_modelo):
            achado.confianca = max(achado.confianca, CONF_ACORDO_REGRA_LLM)
            achado.metodo = MetodoExtracao.REGRA_E_LLM
            combinado.achados.append(achado)
            continue

        # Discordancia: fica o valor da regra (auditavel), mas marcado.
        achado.confianca = min(achado.confianca, CONF_ROTULO_AMBIGUO - 0.05)
        achado.evidencia = (
            f"{achado.evidencia} || divergencia: o modelo leu "
            f"'{do_modelo.valor}' em '{do_modelo.evidencia[:160]}'"
        )
        combinado.achados.append(achado)
        combinado.avisos.append(
            f"{nome}: regra e modelo discordam ({achado.valor} x {do_modelo.valor}) "
            "-- campo marcado para revisao"
        )

    # O que so o modelo viu entra com confianca baixa, sempre para revisao.
    combinado.achados.extend(por_llm.values())
    return combinado
