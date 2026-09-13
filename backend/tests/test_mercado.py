"""Comparacao de mercado (secao 4.5) e score de oportunidade (secao 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from radar.enums import FonteMercado, StatusLote, TipoBem
from radar.market import fipezap
from radar.market.analise import (
    analisar,
    custo_total_estimado,
    melhor_analise,
    praca_vigente,
)
from radar.market.fipe import ProvedorEspelhoLocal, carregar_espelho, similaridade
from radar.models import Leilao, Lote, Praca
from radar.scoring import score as motor_score

AGORA = datetime(2026, 10, 1, 12, tzinfo=UTC)


def _lote(sessao, **ajustes) -> Lote:
    leilao = Leilao(chave_natural=f"leilao-{ajustes.get('chave', 'x')}", fonte_slug="teste")
    sessao.add(leilao)
    sessao.flush()
    campos = dict(
        chave_natural=f"lote-{ajustes.pop('chave', 'x')}",
        leilao=leilao,
        titulo="Apartamento no Farol",
        tipo_bem=TipoBem.IMOVEL,
        status=StatusLote.ABERTO,
        valor_avaliacao=Decimal("320000.00"),
        valor_minimo_primeira=Decimal("320000.00"),
        valor_minimo_segunda=Decimal("160000.00"),
        cidade="Maceió",
        bairro="Farol",
        uf="AL",
        area_privativa_m2=Decimal("68.50"),
        fonte_slug="teste",
    )
    pracas = ajustes.pop(
        "pracas",
        [(1, datetime(2026, 11, 10, 17, tzinfo=UTC)), (2, datetime(2026, 11, 24, 17, tzinfo=UTC))],
    )
    campos.update(ajustes)
    lote = Lote(**campos)
    sessao.add(lote)
    for ordem, data in pracas:
        sessao.add(Praca(leilao=leilao, ordem=ordem, data_hora=data))
    sessao.flush()
    return lote


@pytest.fixture
def base_mercado(sessao_db):
    carregar_espelho(sessao_db)
    fipezap.carregar_indice(sessao_db)
    return sessao_db


# ---------------------------------------------------------------------------
# FIPE
# ---------------------------------------------------------------------------


def test_espelho_fipe_carrega_e_e_idempotente(sessao_db):
    primeiro = carregar_espelho(sessao_db)
    segundo = carregar_espelho(sessao_db)
    assert primeiro == 10
    assert segundo == 0  # recarregar nao duplica


def test_fipe_casa_modelo_por_aproximacao(base_mercado):
    provedor = ProvedorEspelhoLocal(base_mercado)
    valor = provedor.consultar("FIAT", "UNO MILLE ECONOMY", 2015)
    assert valor is not None
    assert valor.valor == Decimal("24500.00")
    assert valor.ano_modelo == 2015
    assert valor.similaridade > 0.5


def test_fipe_recusa_modelo_sem_semelhanca(base_mercado):
    provedor = ProvedorEspelhoLocal(base_mercado)
    assert provedor.consultar("FERRARI", "TESTAROSSA BERLINETTA", 1989) is None


def test_similaridade_ignora_ruido_de_versao():
    assert similaridade("GOL 1.0", "GOL 1.0 FLEX 12V 5P") > 0.6
    assert similaridade("GOL", "ONIX") == 0.0


# ---------------------------------------------------------------------------
# FipeZap
# ---------------------------------------------------------------------------


def test_fipezap_prefere_bairro(base_mercado):
    indice = fipezap.consultar(base_mercado, "AL", "Maceió", "Ponta Verde")
    assert indice.valor_m2 == Decimal("11400.00")
    assert indice.precisao == "BAIRRO"


def test_fipezap_cai_para_cidade_quando_bairro_desconhecido(base_mercado):
    indice = fipezap.consultar(base_mercado, "AL", "Maceió", "Bairro Inexistente")
    assert indice.valor_m2 == Decimal("7200.00")
    assert indice.precisao == "CIDADE"


def test_fipezap_sem_cidade_retorna_nada(base_mercado):
    assert fipezap.consultar(base_mercado, "AL", "Cidade Fantasma", None) is None
    assert fipezap.consultar(base_mercado, None, None, None) is None


# ---------------------------------------------------------------------------
# Praca vigente
# ---------------------------------------------------------------------------


def test_praca_vigente_antes_da_primeira(sessao_db):
    lote = _lote(sessao_db)
    vigente = praca_vigente(lote, AGORA)
    assert (vigente.ordem, vigente.ja_passou) == (1, False)
    assert vigente.valor_minimo == Decimal("320000.00")


def test_praca_vigente_entre_a_primeira_e_a_segunda(sessao_db):
    lote = _lote(sessao_db)
    vigente = praca_vigente(lote, datetime(2026, 11, 15, tzinfo=UTC))
    assert vigente.ordem == 2
    assert vigente.valor_minimo == Decimal("160000.00")


def test_praca_vigente_depois_de_todas(sessao_db):
    lote = _lote(sessao_db)
    vigente = praca_vigente(lote, datetime(2027, 1, 1, tzinfo=UTC))
    assert vigente.ja_passou is True


# ---------------------------------------------------------------------------
# Analise de mercado
# ---------------------------------------------------------------------------


def test_analise_de_laudo_sempre_disponivel(base_mercado):
    lote = _lote(base_mercado, area_privativa_m2=None, cidade=None)
    analises = {a.fonte: a for a in analisar(base_mercado, lote)}
    laudo = analises[FonteMercado.LAUDO_JUDICIAL]
    # Antes da 1a praca o lance minimo e o proprio valor de avaliacao.
    assert laudo.desconto_percentual == Decimal("0.00")
    assert any("defasado" in a for a in laudo.avisos)


def test_desconto_na_segunda_praca(base_mercado, monkeypatch):
    lote = _lote(base_mercado, pracas=[(1, datetime(2026, 9, 1, tzinfo=UTC)),
                                       (2, datetime(2026, 11, 24, 17, tzinfo=UTC))])
    analises = {a.fonte: a for a in analisar(base_mercado, lote)}
    laudo = analises[FonteMercado.LAUDO_JUDICIAL]
    assert laudo.praca_base == 2
    assert laudo.desconto_percentual == Decimal("50.00")


def test_analise_fipezap_usa_area_privativa_e_declara_metodologia(base_mercado):
    lote = _lote(base_mercado, pracas=[(1, datetime(2026, 9, 1, tzinfo=UTC)),
                                       (2, datetime(2026, 11, 24, 17, tzinfo=UTC))])
    analises = {a.fonte: a for a in analisar(base_mercado, lote)}
    zap = analises[FonteMercado.FIPEZAP]
    assert zap.valor_referencia == Decimal("68.50") * Decimal("8100.00")
    assert "68.50 m²" in zap.metodologia
    assert "FipeZap" in zap.metodologia
    assert zap.data_referencia_fonte.strftime("%Y-%m") == "2026-08"
    assert zap.fonte_url.startswith("https://downloads.fipe.org.br")


def test_dado_de_demonstracao_avisa_e_derruba_a_confianca(base_mercado):
    lote = _lote(base_mercado)
    zap = {a.fonte: a for a in analisar(base_mercado, lote)}[FonteMercado.FIPEZAP]
    assert any("DEMONSTRAÇÃO" in a for a in zap.avisos)
    assert zap.confianca < 0.4


def test_area_total_no_lugar_da_privativa_gera_aviso(base_mercado):
    lote = _lote(base_mercado, area_privativa_m2=None, area_total_m2=Decimal("92.30"))
    zap = {a.fonte: a for a in analisar(base_mercado, lote)}[FonteMercado.FIPEZAP]
    assert any("superestimada" in a for a in zap.avisos)


def test_analise_fipe_para_veiculo_com_condicao_de_risco(base_mercado):
    lote = _lote(
        base_mercado,
        chave="veiculo",
        titulo="Fiat Uno 2015",
        tipo_bem=TipoBem.VEICULO,
        marca="FIAT",
        modelo="UNO MILLE ECONOMY",
        ano_modelo=2015,
        area_privativa_m2=None,
        valor_avaliacao=Decimal("28500.00"),
        valor_minimo_primeira=Decimal("28500.00"),
        valor_minimo_segunda=Decimal("14250.00"),
        condicao_veiculo=["sem_chave", "sem_documento"],
        pracas=[(1, datetime(2026, 9, 1, tzinfo=UTC)), (2, datetime(2026, 11, 24, 17, tzinfo=UTC))],
    )
    analises = {a.fonte: a for a in analisar(base_mercado, lote)}
    fipe = analises[FonteMercado.FIPE]
    assert fipe.valor_referencia == Decimal("24500.00")
    assert any("deságio adicional" in a for a in fipe.avisos)
    assert any("sem chave" in a for a in fipe.avisos)
    assert FonteMercado.FIPEZAP not in analises  # veiculo nao usa indice de imovel


def test_analise_e_idempotente(base_mercado):
    lote = _lote(base_mercado)
    analisar(base_mercado, lote)
    base_mercado.flush()
    analisar(base_mercado, lote)
    base_mercado.flush()
    fontes = [a.fonte for a in lote.analises]
    assert len(fontes) == len(set(fontes))


def test_melhor_analise_prefere_fonte_de_mercado_ao_laudo(base_mercado):
    """O laudo tem confianca maior, mas nao carrega informacao de mercado.

    "Lance minimo x avaliacao" da 0% em toda 1a praca e exatamente o percentual
    do edital na 2a, para qualquer bem. Se o laudo ganhasse o destaque, o
    desconto exibido nunca refletiria o mercado.
    """
    lote = _lote(base_mercado)
    analisar(base_mercado, lote)
    base_mercado.flush()

    destaque = melhor_analise(lote)
    assert destaque.fonte is FonteMercado.FIPEZAP
    laudo = next(a for a in lote.analises if a.fonte is FonteMercado.LAUDO_JUDICIAL)
    assert laudo.confianca > destaque.confianca  # ganha em confianca, perde em relevancia


def test_laudo_e_o_destaque_quando_nao_ha_fonte_de_mercado(base_mercado):
    lote = _lote(base_mercado, chave="sem-mercado", cidade=None, area_privativa_m2=None)
    analisar(base_mercado, lote)
    base_mercado.flush()
    assert melhor_analise(lote).fonte is FonteMercado.LAUDO_JUDICIAL


def test_custo_total_soma_comissao_e_debitos(sessao_db):
    lote = _lote(
        sessao_db,
        comissao_leiloeiro_percentual=Decimal("5"),
        debitos=[{"tipo": "iptu", "valor": 8450.0}],
    )
    total, detalhes = custo_total_estimado(lote)
    # 160.000 + 5% (8.000) + 8.450 de IPTU
    assert total == Decimal("176450.00")
    assert any("comissão" in d for d in detalhes)
    assert any("iptu" in d for d in detalhes)
    # A ressalva de ITBI mora no campo `aviso` da API, não na composição do custo.
    assert not any("ITBI" in d for d in detalhes)


def test_custo_total_sem_lance_conhecido(sessao_db):
    lote = _lote(sessao_db, valor_minimo_primeira=None, valor_minimo_segunda=None)
    total, detalhes = custo_total_estimado(lote)
    assert total is None and detalhes


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------


def test_score_soma_componentes_e_todos_tem_explicacao(base_mercado):
    lote = _lote(base_mercado, pracas=[(1, datetime(2026, 9, 1, tzinfo=UTC)),
                                       (2, datetime(2026, 11, 24, 17, tzinfo=UTC))])
    analisar(base_mercado, lote)
    base_mercado.flush()
    score = motor_score.calcular(base_mercado, lote, AGORA)

    assert 0 <= score.total <= 100
    assert score.faixa in {"ALTA", "BOA", "MODERADA", "BAIXA"}
    chaves = {c["chave"] for c in score.componentes}
    assert chaves == {
        "desconto", "qualidade_informacao", "risco_documental", "janela_tempo", "historico",
    }
    assert round(sum(c["pontos"] for c in score.componentes), 1) == pytest.approx(
        score.total, abs=0.5
    )
    # Secao 8: nunca um numero sem explicacao.
    for componente in score.componentes:
        assert len(componente["explicacao"]) > 30
        assert componente["pontos"] <= componente["maximo"]


def test_score_penaliza_imovel_ocupado_com_onus(base_mercado):
    limpo = _lote(base_mercado, chave="limpo", ocupado=False, matricula="45.678")
    arriscado = _lote(
        base_mercado, chave="risco", ocupado=True, matricula="45.679",
        onus=["hipoteca", "usufruto"],
    )
    for lote in (limpo, arriscado):
        analisar(base_mercado, lote)
    base_mercado.flush()

    risco_limpo = next(
        c for c in motor_score.calcular(base_mercado, limpo, AGORA).componentes
        if c["chave"] == "risco_documental"
    )
    risco_alto = next(
        c for c in motor_score.calcular(base_mercado, arriscado, AGORA).componentes
        if c["chave"] == "risco_documental"
    )
    assert risco_limpo["pontos"] > risco_alto["pontos"]
    assert "ocupado" in risco_alto["explicacao"]
    assert "hipoteca" in risco_alto["explicacao"]


def test_janela_de_tempo_premia_urgencia(base_mercado):
    urgente = _lote(
        base_mercado, chave="urgente",
        pracas=[(1, AGORA + timedelta(days=2))],
    )
    distante = _lote(
        base_mercado, chave="distante",
        pracas=[(1, AGORA + timedelta(days=120))],
    )
    base_mercado.flush()
    def janela(lote):
        return next(
            c for c in motor_score.calcular(base_mercado, lote, AGORA).componentes
            if c["chave"] == "janela_tempo"
        )
    assert janela(urgente)["pontos"] > janela(distante)["pontos"]
    assert "urgência" in janela(urgente)["explicacao"]


def test_praca_ja_ocorrida_zera_a_janela(base_mercado):
    lote = _lote(base_mercado, pracas=[(1, AGORA - timedelta(days=10))])
    base_mercado.flush()
    janela = next(
        c for c in motor_score.calcular(base_mercado, lote, AGORA).componentes
        if c["chave"] == "janela_tempo"
    )
    assert janela["pontos"] == 0
    assert "já ocorreu" in janela["explicacao"]


def test_score_sem_referencia_de_mercado_explica_a_ausencia(sessao_db):
    lote = _lote(sessao_db, valor_avaliacao=None, valor_minimo_primeira=None,
                 valor_minimo_segunda=None)
    sessao_db.flush()
    desconto = next(
        c for c in motor_score.calcular(sessao_db, lote, AGORA).componentes
        if c["chave"] == "desconto"
    )
    assert desconto["pontos"] == 0
    assert "Sem referência de mercado" in desconto["explicacao"]


def test_recalcular_todos(base_mercado):
    for i in range(3):
        _lote(base_mercado, chave=f"l{i}")
    base_mercado.flush()
    assert motor_score.recalcular_todos(base_mercado) >= 3
