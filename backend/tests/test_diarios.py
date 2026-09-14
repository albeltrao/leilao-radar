"""Diário da Justiça: classificação do bem, detecção de leilão e conector.

Tudo offline. O conector é exercitado contra JSON congelado em
``fixtures/diarios/``, nunca contra a API do CNJ.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from radar.collectors.base import obter
from radar.collectors.dto import PublicacaoBruta
from radar.collectors.http import EstruturaInesperada
from radar.diarios.classificacao import classificar_bem
from radar.diarios.deteccao import (
    detectar_leilao,
    para_lote_bruto,
    uf_da_secao_judiciaria,
)
from radar.enums import (
    EsferaJustica,
    NaturezaBem,
    TipoBem,
    TipoDocumento,
    TipoFonte,
    ZonaImovel,
)
from radar.extraction.campos import LIMIAR_REVISAO

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "diarios"


def carregar(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Classificação do bem
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("texto", "natureza", "zona"),
    [
        (
            "Imóvel rural denominado Sítio Boa Esperança, com 12 hectares, na zona "
            "rural de Arapiraca/AL",
            NaturezaBem.IMOVEL,
            ZonaImovel.RURAL,
        ),
        (
            "Apartamento nº 302 do Edifício Jatobá, Rua do Sol, bairro Ponta Verde, "
            "Maceió/AL",
            NaturezaBem.IMOVEL,
            ZonaImovel.URBANA,
        ),
        (
            "Terreno urbano medindo 450 m², quadra 12, lote 8, em Arapiraca/AL",
            NaturezaBem.IMOVEL,
            ZonaImovel.URBANA,
        ),
        (
            "Veículo automóvel marca Fiat, modelo Strada, placa ABC1D23",
            NaturezaBem.MOVEL,
            ZonaImovel.INDEFINIDA,
        ),
        (
            "Um trator agrícola marca Valtra e uma colheitadeira",
            NaturezaBem.MOVEL,
            ZonaImovel.INDEFINIDA,
        ),
        (
            "Rebanho de 40 bovinos, semoventes penhorados",
            NaturezaBem.MOVEL,
            ZonaImovel.INDEFINIDA,
        ),
        ("Intimação das partes para manifestação", NaturezaBem.INDEFINIDA, ZonaImovel.INDEFINIDA),
    ],
)
def test_classifica_natureza_e_zona(texto, natureza, zona):
    resultado = classificar_bem(texto)
    assert resultado.natureza is natureza
    assert resultado.zona is zona


def test_classificacao_sempre_traz_evidencia_literal():
    """Regra 2 do CLAUDE.md: nada derivado é apresentado sem o trecho que o sustenta."""
    texto = "Imóvel rural denominado Sítio Boa Esperança, na zona rural do município."
    resultado = classificar_bem(texto)
    assert resultado.evidencia_natureza and resultado.evidencia_natureza in texto
    assert resultado.evidencia_zona and resultado.evidencia_zona in texto
    for achado in resultado.achados():
        assert achado.evidencia
        assert 0 < achado.confianca < 1.0  # nunca certeza absoluta


def test_zona_em_conflito_fica_indefinida_e_vai_para_revisao():
    """Sítio dentro do perímetro urbano: os dois sinais são verdadeiros.

    O certo aqui é dizer "não sei", não escolher o de peso maior por 0,02.
    """
    resultado = classificar_bem(
        "Bem imóvel: casa situada no Sítio Água Fria, dentro do perímetro urbano "
        "do município."
    )
    assert resultado.natureza is NaturezaBem.IMOVEL
    assert resultado.zona is ZonaImovel.INDEFINIDA
    assert resultado.conflito_zona
    assert resultado.confianca_zona < LIMIAR_REVISAO


def test_movel_nao_ganha_zona_mesmo_citando_fazenda():
    """"Trator na Fazenda X" é bem móvel; a fazenda é onde ele está, não o lote."""
    resultado = classificar_bem("Trator agrícola localizado na Fazenda Boa Vista")
    assert resultado.natureza is NaturezaBem.MOVEL
    assert resultado.zona is ZonaImovel.INDEFINIDA
    assert resultado.categoria == "MOVEL"


def test_tipo_declarado_pela_fonte_nao_sobrescreve_o_texto():
    """Fonte diz VEICULO, texto grita imóvel: vira dúvida, não obediência."""
    resultado = classificar_bem(
        "Apartamento nº 12 do Edifício Central, matrícula 9.000 do Registro de Imóveis",
        TipoBem.VEICULO,
    )
    assert resultado.confianca_natureza < 0.9


# ---------------------------------------------------------------------------
# Detecção
# ---------------------------------------------------------------------------


def test_detecta_edital_de_leilao_com_confianca_alta():
    dados = json.loads(carregar("djen_tjal.json"))
    detectado = detectar_leilao(dados["items"][0]["texto"])
    assert detectado is not None
    assert detectado.confianca >= 0.75
    assert detectado.contexto_judicial
    assert not detectado.revisao_necessaria
    assert detectado.numero_processo == "0710702-95.2021.8.02.0001"
    assert detectado.classificacao.categoria == "IMOVEL_URBANO"


def test_intimacao_comum_nao_e_leilao():
    dados = json.loads(carregar("djen_tjal.json"))
    assert detectar_leilao(dados["items"][2]["texto"]) is None


def test_leilao_de_energia_nao_entra_na_agenda():
    """O diário da Justiça Federal publica aviso de leilão que não é judicial."""
    texto = (
        "AVISO. Fica publicado o resultado do leilão de energia elétrica promovido "
        "pela ANEEL, bem como o pregão eletrônico nº 3/2026 para contratação de "
        "serviços de vigilância."
    )
    assert detectar_leilao(texto) is None


def test_limiar_controla_o_que_vira_lote():
    texto = (
        "Fica o executado intimado da nomeação de leiloeiro nos autos, para "
        "manifestação sobre a praça a ser designada pelo juízo da 2ª Vara Cível."
    )
    assert detectar_leilao(texto, limiar=0.9) is None
    frouxo = detectar_leilao(texto, limiar=0.2)
    assert frouxo is not None and frouxo.revisao_necessaria


def test_uf_da_secao_judiciaria():
    """O código TR do CNJ não dá a UF de processo federal: o TRF5 cobre seis estados."""
    assert uf_da_secao_judiciaria("12ª Vara Federal da Seção Judiciária de Pernambuco") == "PE"
    assert uf_da_secao_judiciaria("Subseção Judiciária de Alagoas") == "AL"
    assert uf_da_secao_judiciaria("3ª Vara Cível da Comarca de Maceió") is None


# ---------------------------------------------------------------------------
# Publicação -> lote
# ---------------------------------------------------------------------------


def _publicacao(nome: str, indice: int = 0) -> PublicacaoBruta:
    conector = obter("djen-tjal" if "tjal" in nome else "djen-trf5")
    return conector.parse(carregar(nome), "https://exemplo.invalid/consulta").publicacoes[
        indice
    ]


def test_lote_do_diario_carrega_pracas_valores_e_procedencia():
    publicacao = _publicacao("djen_tjal.json", 0)
    detectado = detectar_leilao(publicacao.texto)
    bruto = para_lote_bruto(publicacao, detectado)

    assert bruto.tipo_bem is TipoBem.IMOVEL
    assert bruto.uf == "AL"
    assert bruto.tribunal_sigla == "TJAL"
    assert bruto.valor_avaliacao == 450000
    ordens = {p.ordem: p for p in bruto.pracas}
    assert ordens[1].data_hora is not None and ordens[2].data_hora is not None
    assert ordens[2].percentual_minimo == 60  # lido do edital, nunca assumido
    assert bruto.leiloeiro_matricula == "12/2019"
    assert bruto.extras["categoria_bem"] == "IMOVEL_URBANO"
    assert bruto.extras["origem"] == "diario"
    assert bruto.documentos[0].tipo is TipoDocumento.PUBLICACAO_DIARIO


def test_lote_federal_herda_uf_da_secao_judiciaria():
    publicacao = _publicacao("djen_trf5.json", 0)
    detectado = detectar_leilao(publicacao.texto)
    bruto = para_lote_bruto(publicacao, detectado)
    assert bruto.uf == "PE"
    assert bruto.tribunal_sigla == "TRF5"
    assert bruto.tipo_bem is TipoBem.VEICULO


def test_texto_da_publicacao_perde_o_cpf_antes_de_virar_descricao():
    publicacao = _publicacao("djen_tjal.json", 0)
    publicacao.texto += " Executado inscrito no CPF 123.456.789-00."
    detectado = detectar_leilao(publicacao.texto)
    bruto = para_lote_bruto(publicacao, detectado)
    assert "123.456.789-00" not in (bruto.descricao or "")
    assert "[CPF removido]" in bruto.descricao


def test_percentual_da_segunda_praca_nao_e_inventado():
    """A regra dos 50% é costume, não lei. Sem o percentual escrito, campo vazio."""
    publicacao = _publicacao("djen_tjal.json", 1)
    detectado = detectar_leilao(publicacao.texto)
    bruto = para_lote_bruto(publicacao, detectado)
    segunda = next(p for p in bruto.pracas if p.ordem == 2)
    assert segunda.percentual_minimo is None
    assert segunda.valor_minimo is None


# ---------------------------------------------------------------------------
# Conector
# ---------------------------------------------------------------------------


def test_conectores_de_diario_cobrem_as_duas_esferas():
    from radar.collectors.base import listar

    diarios = listar(tipo=TipoFonte.DIARIO_OFICIAL)
    slugs = {c.slug for c in diarios}
    assert {"djen-tjal", "djen-tjba", "djen-tjpe", "djen-tjse"} <= slugs
    assert {"djen-trf1", "djen-trf5"} <= slugs
    esferas = {c.esfera for c in diarios}
    assert esferas == {EsferaJustica.ESTADUAL, EsferaJustica.FEDERAL}
    # Nenhum foi conferido contra a API real ainda; ligar sem conferir seria
    # anunciar cobertura que não existe.
    assert all(not c.meta.validado_ao_vivo for c in diarios)


def test_trf5_nao_finge_cobrir_um_estado_so():
    """O TRF5 responde por AL, PE e SE: fixar uma UF esconderia as outras duas."""
    assert obter("djen-trf5").meta.uf is None
    assert obter("djen-trf1").meta.uf == "BA"  # a única UF do Radar na 1ª Região


def test_parse_ignora_item_sem_texto_mas_conta_a_pagina():
    """Item descartado não pode ser lido como fim da lista na paginação."""
    conector = obter("djen-tjal")
    corpo = json.dumps({"status": "success", "items": [{"id": 1, "texto": "curto"}]})
    pagina = conector.parse(corpo, "https://exemplo.invalid")
    assert pagina.publicacoes == []
    assert pagina.itens_brutos == 1


def test_parse_sem_identificador_descarta():
    """Sem identificador não há idempotência: cada coleta criaria um lote novo."""
    conector = obter("djen-tjal")
    corpo = json.dumps({"items": [{"texto": "EDITAL DE LEILÃO " + "x" * 80}]})
    assert conector.parse(corpo, "https://exemplo.invalid").publicacoes == []


def test_zero_resultados_nao_e_falha_de_estrutura():
    """Dia sem leilão é normal; tratar como quebra encheria o painel de alarme falso."""
    conector = obter("djen-tjal")
    corpo = json.dumps({"status": "success", "message": "ok", "count": 0})
    assert conector.parse(corpo, "https://exemplo.invalid").publicacoes == []


def test_json_invalido_vira_estrutura_inesperada():
    conector = obter("djen-tjal")
    with pytest.raises(EstruturaInesperada):
        conector.parse("<html>erro 500</html>", "https://exemplo.invalid")


def test_json_sem_lista_reconhecivel_vira_estrutura_inesperada():
    conector = obter("djen-tjal")
    with pytest.raises(EstruturaInesperada):
        conector.parse(json.dumps({"resposta": "mudou o contrato"}), "https://exemplo.invalid")


def test_urls_da_busca_carregam_janela_tribunal_e_termo():
    from datetime import date

    conector = obter("djen-tjse")
    urls = list(conector.urls_do_termo("leilão", hoje=date(2026, 9, 18)))
    assert urls, "o conector precisa gerar ao menos uma página"
    primeira = urls[0]
    assert "siglaTribunal=TJSE" in primeira
    assert "dataDisponibilizacaoFim=2026-09-18" in primeira
    assert "dataDisponibilizacaoInicio=2026-09-15" in primeira  # 3 dias retroativos
