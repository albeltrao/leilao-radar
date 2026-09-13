"""Extracao documental (secao 7): parser de edital, merge e salvaguardas."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest

from radar.enums import MetodoExtracao
from radar.extraction.campos import (
    CONF_ACORDO_REGRA_LLM,
    CONF_SO_LLM,
    LIMIAR_REVISAO,
    Achado,
    ResultadoExtracao,
)
from radar.extraction.edital import extrair_de_texto
from radar.extraction.llm import CampoLLM, ExtracaoLLM, ExtratorLLM
from radar.extraction.merge import combinar
from radar.extraction.pdf import normalizar_texto_pdf

FIXTURES = Path(__file__).parent / "fixtures" / "texto"


def carregar(nome: str) -> str:
    return (FIXTURES / f"{nome}.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def imovel() -> ResultadoExtracao:
    return extrair_de_texto(carregar("edital_imovel_maceio"))


@pytest.fixture(scope="module")
def veiculo() -> ResultadoExtracao:
    return extrair_de_texto(carregar("edital_veiculo_aracaju"))


# ---------------------------------------------------------------------------
# Parser de regra -- edital de imovel
# ---------------------------------------------------------------------------


def test_extrai_identificacao_processual(imovel):
    campos = imovel.por_nome()
    assert campos["numero_processo"].valor_texto == "0710702-95.2021.8.02.0001"
    assert campos["comarca"].valor_texto.upper() == "MACEIÓ"
    assert "VARA CÍVEL" in campos["vara"].valor_texto.upper()
    assert campos["leiloeiro_nome"].valor_texto == "ANA PAULA FERREIRA LIMA"


def test_extrai_valores_e_datas(imovel):
    campos = imovel.por_nome()
    assert campos["valor_avaliacao"].valor_numerico == Decimal("320000.00")
    assert campos["valor_minimo_praca_1"].valor_numerico == Decimal("320000.00")
    assert campos["valor_minimo_praca_2"].valor_numerico == Decimal("160000.00")
    assert campos["percentual_minimo_segunda_praca"].valor_numerico == Decimal("50")
    assert campos["comissao_leiloeiro"].valor_numerico == Decimal("5")
    # 14h00 local (UTC-3) = 17h UTC
    assert campos["data_praca_1"].valor_data.hour == 17
    assert campos["data_praca_1"].valor_data.day == 10
    assert campos["data_praca_2"].valor_data.day == 24


def test_menciona_avaliacao_na_segunda_praca_nao_vira_ambiguidade(imovel):
    """"nao inferior a 50% do valor da avaliacao, R$ 160.000,00" nao e um
    segundo valor de avaliacao -- senao todo edital cairia em revisao."""
    avaliacao = imovel.obter("valor_avaliacao")
    assert avaliacao.confianca >= LIMIAR_REVISAO
    assert not avaliacao.revisao_necessaria


def test_separa_area_total_de_area_privativa(imovel):
    campos = imovel.por_nome()
    assert campos["area_total_m2"].valor_numerico == Decimal("92.30")
    assert campos["area_privativa_m2"].valor_numerico == Decimal("68.50")


def test_detecta_ocupacao(imovel):
    ocupado = imovel.obter("ocupado")
    assert ocupado.valor_booleano is True
    assert "ocupado" in ocupado.evidencia.lower()


def test_extrai_matricula_e_cartorio(imovel):
    campos = imovel.por_nome()
    assert campos["matricula_imovel"].valor_texto == "45.678"
    assert "Ofício de Registro de Imóveis" in campos["cartorio"].valor_texto
    # O sufixo "da Comarca de X" nao faz parte do nome do cartorio.
    assert "Comarca" not in campos["cartorio"].valor_texto


def test_onus_e_debitos(imovel):
    campos = imovel.por_nome()
    assert set(campos["onus"].valor_texto.split(", ")) == {"hipoteca", "penhora"}
    # "Nao consta usufruto" nao pode virar onus.
    assert "usufruto" not in campos["onus"].valor_texto
    assert campos["debito_iptu"].valor_numerico == Decimal("8450.00")
    assert campos["debito_condominio"].valor_numerico == Decimal("12300.00")


def test_sub_rogacao_relata_os_dois_lados_sem_opinar(imovel):
    """Secao 7.3: sinalizar o que o edital diz, sem dar parecer juridico."""
    campos = imovel.por_nome()
    assert campos["edital_invoca_sub_rogacao_no_preco"].valor_booleano is True
    assert campos["edital_atribui_debitos_ao_arrematante"].valor_booleano is True
    # A evidencia precisa trazer o texto que sustenta a afirmacao.
    evidencia = campos["edital_invoca_sub_rogacao_no_preco"].evidencia.lower()
    assert "130" in evidencia or "sub-rog" in evidencia


def test_formas_de_pagamento(imovel):
    formas = set(imovel.obter("formas_pagamento").valor_texto.split(", "))
    assert {"a_vista", "parcelado", "fgts", "financiamento"} <= formas


# ---------------------------------------------------------------------------
# Parser de regra -- edital de veiculo
# ---------------------------------------------------------------------------


def test_veiculo_percentual_diferente_de_50(veiculo):
    """Nao assumimos 50%: este edital exige 60% e o parser tem de ler isso."""
    campos = veiculo.por_nome()
    assert campos["percentual_minimo_segunda_praca"].valor_numerico == Decimal("60")
    assert campos["valor_minimo_praca_2"].valor_numerico == Decimal("17100.00")


def test_veiculo_condicao_de_risco(veiculo):
    condicoes = set(veiculo.obter("condicao_veiculo").valor_texto.split(", "))
    assert {"sem_chave", "sem_documento", "nao_vistoriado"} <= condicoes


def test_veiculo_comarca_com_travessao(veiculo):
    assert veiculo.obter("comarca").valor_texto.upper() == "ARACAJU"


# ---------------------------------------------------------------------------
# Casos de borda do parser
# ---------------------------------------------------------------------------


def test_desocupado_nao_vira_ocupado():
    texto = "EDITAL DE LEILÃO. " * 5 + "O imóvel encontra-se desocupado e livre de ocupantes."
    achado = extrair_de_texto(texto).obter("ocupado")
    assert achado is not None and achado.valor_booleano is False


def test_contradicao_de_ocupacao_cai_em_revisao():
    texto = (
        "EDITAL DE LEILÃO JUDICIAL. " * 4
        + "O imóvel encontra-se desocupado. Consta que está ocupado por terceiros."
    )
    achado = extrair_de_texto(texto).obter("ocupado")
    assert achado.revisao_necessaria


def test_livre_de_hipoteca_nao_vira_onus():
    texto = "EDITAL DE LEILÃO JUDICIAL. " * 4 + "O imóvel está livre de hipoteca e de arresto."
    assert extrair_de_texto(texto).obter("onus") is None


def test_texto_curto_nao_quebra():
    resultado = extrair_de_texto("nada")
    assert resultado.achados == []
    assert resultado.avisos


def test_comissao_absurda_e_descartada():
    texto = "EDITAL DE LEILÃO. " * 5 + "Desconto de comissão de 80% sobre tudo."
    assert extrair_de_texto(texto).obter("comissao_leiloeiro") is None


def test_evidencia_sempre_acompanha_o_achado(imovel, veiculo):
    for resultado in (imovel, veiculo):
        for achado in resultado.achados:
            assert achado.evidencia, f"{achado.nome} sem evidencia"


def test_normalizacao_de_pdf_junta_hifenizacao_e_valores_quebrados():
    assert normalizar_texto_pdf("aliena-\nção judicial") == "alienação judicial"
    assert "R$ 320.000,00" in normalizar_texto_pdf("R$ 320.000,\n00")


# ---------------------------------------------------------------------------
# Merge regra + LLM
# ---------------------------------------------------------------------------


def _achado(nome, **kw):
    base = dict(nome=nome, confianca=0.9, evidencia="trecho do edital de referencia")
    base.update(kw)
    return Achado(**base)


def test_concordancia_eleva_a_confianca():
    regra = ResultadoExtracao(achados=[_achado("valor_avaliacao", valor_numerico=Decimal("320000"))])
    llm = ResultadoExtracao(
        achados=[
            _achado(
                "valor_avaliacao",
                valor_numerico=Decimal("320000.00"),
                confianca=CONF_SO_LLM,
                metodo=MetodoExtracao.LLM,
            )
        ]
    )
    campo = combinar(regra, llm).obter("valor_avaliacao")
    assert campo.confianca == CONF_ACORDO_REGRA_LLM
    assert campo.metodo is MetodoExtracao.REGRA_E_LLM


def test_discordancia_mantem_a_regra_e_marca_revisao():
    regra = ResultadoExtracao(achados=[_achado("valor_avaliacao", valor_numerico=Decimal("320000"))])
    llm = ResultadoExtracao(
        achados=[
            _achado(
                "valor_avaliacao",
                valor_numerico=Decimal("32000"),
                confianca=CONF_SO_LLM,
                metodo=MetodoExtracao.LLM,
            )
        ]
    )
    combinado = combinar(regra, llm)
    campo = combinado.obter("valor_avaliacao")
    assert campo.valor_numerico == Decimal("320000")  # a regra prevalece
    assert campo.revisao_necessaria
    assert any("discordam" in a for a in combinado.avisos)


def test_campo_so_do_llm_entra_com_confianca_baixa():
    llm = ResultadoExtracao(
        achados=[
            _achado("cartorio", valor_texto="1º Ofício", confianca=CONF_SO_LLM,
                    metodo=MetodoExtracao.LLM)
        ]
    )
    campo = combinar(ResultadoExtracao(), llm).obter("cartorio")
    assert campo.revisao_necessaria
    assert campo.metodo is MetodoExtracao.LLM


# ---------------------------------------------------------------------------
# Salvaguardas do extrator por LLM
# ---------------------------------------------------------------------------


@dataclass
class _Resposta:
    parsed_output: ExtracaoLLM
    stop_reason: str = "end_turn"
    stop_details: object = None


class _ClienteFalso:
    """Dubl� do SDK: expoe apenas client.messages.parse."""

    def __init__(self, resposta):
        self._resposta = resposta

        class _Messages:
            parse = lambda _self, **kwargs: resposta  # noqa: E731

        self.messages = _Messages()


@pytest.fixture
def settings_llm(settings, monkeypatch):
    monkeypatch.setattr(settings, "llm_habilitado", True)
    monkeypatch.setattr(settings, "llm_api_key", "chave-de-teste")
    return settings


def test_llm_desligado_por_padrao(settings):
    resultado = ExtratorLLM(settings).extrair("qualquer texto longo o suficiente aqui")
    assert resultado.achados == []
    assert any("desligada" in a for a in resultado.avisos)


def test_llm_descarta_campo_sem_evidencia_no_documento(settings_llm):
    """Defesa contra alucinacao: trecho citado tem de existir no edital."""
    texto = carregar("edital_imovel_maceio")
    resposta = _Resposta(
        ExtracaoLLM(
            campos=[
                CampoLLM(
                    nome="valor_avaliacao",
                    valor="R$ 999.999,00",
                    confianca=0.99,
                    trecho_do_documento="o valor da avaliação é de R$ 999.999,00 conforme laudo",
                )
            ]
        )
    )
    resultado = ExtratorLLM(settings_llm, cliente=_ClienteFalso(resposta)).extrair(texto)
    assert resultado.achados == []
    assert any("nao existe no edital" in a for a in resultado.avisos)


def test_llm_aceita_campo_com_evidencia_real(settings_llm):
    texto = carregar("edital_imovel_maceio")
    resposta = _Resposta(
        ExtracaoLLM(
            campos=[
                CampoLLM(
                    nome="cartorio",
                    valor="2º Ofício de Registro de Imóveis",
                    confianca=0.9,
                    trecho_do_documento="do 2º Ofício de Registro de Imóveis da Comarca de Maceió",
                )
            ]
        )
    )
    resultado = ExtratorLLM(settings_llm, cliente=_ClienteFalso(resposta)).extrair(texto)
    campo = resultado.obter("cartorio")
    assert campo is not None
    # Mesmo com o modelo dizendo 0.9, teto de CONF_SO_LLM se aplica.
    assert campo.confianca <= CONF_SO_LLM
    assert campo.revisao_necessaria


def test_llm_descarta_campo_fora_da_whitelist(settings_llm):
    texto = carregar("edital_imovel_maceio")
    resposta = _Resposta(
        ExtracaoLLM(
            campos=[
                CampoLLM(
                    nome="nome_do_executado",  # dado pessoal: nao entra
                    valor="Fulano de Tal",
                    confianca=0.95,
                    trecho_do_documento="movido por Banco Exemplo S/A em face de devedor",
                )
            ]
        )
    )
    resultado = ExtratorLLM(settings_llm, cliente=_ClienteFalso(resposta)).extrair(texto)
    assert resultado.achados == []
    assert any("whitelist" in a for a in resultado.avisos)


def test_llm_recusa_degrada_para_regra(settings_llm):
    resposta = _Resposta(ExtracaoLLM(campos=[]), stop_reason="refusal")
    resultado = ExtratorLLM(settings_llm, cliente=_ClienteFalso(resposta)).extrair(
        carregar("edital_imovel_maceio")
    )
    assert resultado.achados == []
    assert any("recusou" in a for a in resultado.avisos)


def test_llm_trecho_curto_demais_nao_serve_de_evidencia(settings_llm):
    resposta = _Resposta(
        ExtracaoLLM(
            campos=[
                CampoLLM(nome="valor_avaliacao", valor="R$ 1,00", confianca=0.9,
                         trecho_do_documento="R$")
            ]
        )
    )
    resultado = ExtratorLLM(settings_llm, cliente=_ClienteFalso(resposta)).extrair(
        carregar("edital_imovel_maceio")
    )
    assert resultado.achados == []


def test_matricula_do_leiloeiro_e_extraida(imovel, veiculo):
    """Regressao: "matricula nº 12/2019" vira "matricula no 12/2019" depois da
    normalizacao NFKD, e um padrao que procurasse "º" literal nunca casava."""
    assert imovel.obter("leiloeiro_matricula").valor_texto == "12/2019"
    assert veiculo.obter("leiloeiro_matricula").valor_texto == "05/2018"


def test_nao_confunde_matricula_do_imovel_com_a_do_leiloeiro(imovel):
    """As duas usam a palavra "matricula" e a do leiloeiro vem antes no edital."""
    assert imovel.obter("matricula_imovel").valor_texto == "45.678"
    assert imovel.obter("leiloeiro_matricula").valor_texto == "12/2019"


def test_edital_sem_contexto_registral_usa_fallback_guardado():
    texto = (
        "EDITAL DE LEILÃO JUDICIAL. " * 4
        + "Leiloeiro oficial João, matrícula nº 07/2010. Bem: terreno de matrícula 99.123."
    )
    achado = extrair_de_texto(texto).obter("matricula_imovel")
    assert achado.valor_texto == "99.123"
    # Sem contexto registral explícito, o campo vai para revisão.
    assert achado.revisao_necessaria
