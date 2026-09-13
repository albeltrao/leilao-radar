"""Testes de regressao dos conectores.

Cada parser roda contra uma fixture HTML congelada. Quando um site muda de
layout, o teste correspondente quebra e mostra exatamente qual campo sumiu --
que e a mitigacao do risco numero 1 da secao 15.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from conftest import carregar_html
from radar.collectors.base import MetadadosFonte, listar, obter
from radar.collectors.cadastro import ColetorCadastroLeiloeiros, interpretar_status
from radar.collectors.editais import ColetorEditaisTribunal, rotulo_comarca
from radar.collectors.http import EstruturaInesperada
from radar.collectors.leiloeiros.declarativo import (
    ConectorDeclarativo,
    carregar_perfis,
    inferir_status,
    inferir_tipo_bem,
)
from radar.enums import (
    JuntaComercial,
    StatusLeiloeiro,
    StatusLote,
    TipoBem,
    TipoFonte,
)


def _meta(slug: str, tipo: TipoFonte, uf: str) -> MetadadosFonte:
    return MetadadosFonte(
        slug=slug, nome=slug, tipo=tipo, uf=uf, url_alvo="https://exemplo.invalid",
        periodicidade_horas=24,
    )


# ---------------------------------------------------------------------------
# Cadastro de leiloeiros (juntas comerciais e corregedorias)
# ---------------------------------------------------------------------------


@pytest.fixture
def coletor_juceal():
    return ColetorCadastroLeiloeiros(
        meta=_meta("juceal-teste", TipoFonte.JUNTA_COMERCIAL, "AL"),
        urls=["https://exemplo.invalid/leiloeiros"],
        junta=JuntaComercial.JUCEAL,
        uf="AL",
    )


def test_cadastro_le_tabela_com_cabecalho(coletor_juceal):
    itens = coletor_juceal.parse(carregar_html("juceal_leiloeiros.html"), "https://x.invalid")
    assert len(itens) == 3
    por_nome = {i.nome: i for i in itens}

    ana = por_nome["Ana Paula Ferreira Lima"]
    assert ana.matricula == "12/2019"
    assert ana.status is StatusLeiloeiro.ATIVO
    assert ana.junta is JuntaComercial.JUCEAL
    assert ana.uf == "AL"
    assert ana.email == "ana.lima@example.org"
    assert ana.telefone == "(82) 3333-4444"
    assert ana.site_url == "https://leiloes-exemplo-al.invalid"
    assert ana.comarcas == ["Maceió", "Arapiraca"]

    assert por_nome["Carlos Eduardo Monteiro"].status is StatusLeiloeiro.SUSPENSO
    assert por_nome["Joana Ribeiro da Silva"].comarcas == [
        "Palmeira dos Índios",
        "União dos Palmares",
    ]


def test_cadastro_ignora_linha_de_rodape(coletor_juceal):
    itens = coletor_juceal.parse(carregar_html("juceal_leiloeiros.html"), "https://x.invalid")
    assert not any(i.nome.lower().startswith("total") for i in itens)


def test_cadastro_cai_para_cards_quando_nao_ha_tabela():
    coletor = ColetorCadastroLeiloeiros(
        meta=_meta("jucese-teste", TipoFonte.JUNTA_COMERCIAL, "SE"),
        urls=["https://exemplo.invalid"],
        junta=JuntaComercial.JUCESE,
        uf="SE",
    )
    itens = coletor.parse(carregar_html("jucese_leiloeiros.html"), "https://x.invalid")
    assert len(itens) == 3
    por_nome = {i.nome: i for i in itens}
    marcos = por_nome["Marcos Vinícius Andrade"]
    assert marcos.matricula == "05/2018"
    assert marcos.status is StatusLeiloeiro.ATIVO
    assert marcos.email == "marcos@example.org"
    assert marcos.site_url == "https://leiloeiro-se-exemplo.invalid"
    assert por_nome["Rafael Teixeira Gomes"].status is StatusLeiloeiro.INATIVO


def test_cadastro_deduplica_por_nome_e_matricula(coletor_juceal):
    html = carregar_html("juceal_leiloeiros.html")
    duplicado = html.replace("</tbody>", "</tbody>") + html
    itens = coletor_juceal.parse(duplicado, "https://x.invalid")
    assert len(itens) == 3


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Ativo", StatusLeiloeiro.ATIVO),
        ("EM ATIVIDADE", StatusLeiloeiro.ATIVO),
        ("suspenso por 90 dias", StatusLeiloeiro.SUSPENSO),
        ("Cancelado", StatusLeiloeiro.INATIVO),
        ("baixado a pedido", StatusLeiloeiro.INATIVO),
        ("", StatusLeiloeiro.DESCONHECIDO),
        ("qualquer coisa", StatusLeiloeiro.DESCONHECIDO),
    ],
)
def test_interpretar_status(texto, esperado):
    assert interpretar_status(texto) is esperado


# ---------------------------------------------------------------------------
# Editais de tribunal
# ---------------------------------------------------------------------------


def test_tjpe_extrai_linhas_da_tabela():
    coletor = ColetorEditaisTribunal(
        meta=_meta("tjpe-teste", TipoFonte.TRIBUNAL, "PE"),
        urls=["https://portal.tjpe.jus.br/x"],
        tribunal_sigla="TJPE",
        uf="PE",
    )
    lotes = coletor.parse(carregar_html("tjpe_leiloes.html"), "https://portal.tjpe.jus.br/x")
    assert len(lotes) == 2
    primeiro = lotes[0]
    assert primeiro.numero_processo == "0055012-25.2024.8.17.2001"
    assert primeiro.comarca == "Recife"
    assert primeiro.vara == "5ª Vara Cível"
    assert primeiro.leiloeiro_nome == "José Almeida Leiloeiro Oficial"
    assert primeiro.tribunal_sigla == "TJPE"
    assert primeiro.documentos[0].url.endswith("/documents/edital-0055012.pdf")
    assert primeiro.pracas[0].data_hora is not None
    assert primeiro.pracas[0].data_hora.hour == 13  # 10h00 local -> 13h UTC


def test_tjse_cai_para_lista_de_pdfs():
    coletor = ColetorEditaisTribunal(
        meta=_meta("tjse-teste", TipoFonte.TRIBUNAL, "SE"),
        urls=["https://www.tjse.jus.br/x"],
        tribunal_sigla="TJSE",
        uf="SE",
    )
    lotes = coletor.parse(
        carregar_html("tjse_leilao_judicial.html"), "https://www.tjse.jus.br/x"
    )
    # So os dois editais; o link "Outros servicos" nao entra.
    assert len(lotes) == 2
    assert all(lote.documentos[0].url.endswith(".pdf") for lote in lotes)
    assert lotes[0].pracas[0].data_hora is not None
    assert "Aracaju" in lotes[0].titulo


def test_editais_sem_nada_reconhecivel_levanta_estrutura_inesperada():
    coletor = ColetorEditaisTribunal(
        meta=_meta("vazio", TipoFonte.TRIBUNAL, "PE"),
        urls=["https://exemplo.invalid"],
        tribunal_sigla="TJPE",
        uf="PE",
    )
    assert coletor.parse("<html><body><p>Página em manutenção</p></body></html>", "u") == []


def test_rotulo_comarca():
    assert rotulo_comarca("Comarca de Maceió | 3ª Vara") == "Maceió"
    assert rotulo_comarca("Circunscrição Judiciária de Caruaru") == "Caruaru"
    assert rotulo_comarca("nada aqui") is None


# ---------------------------------------------------------------------------
# Engine declarativa
# ---------------------------------------------------------------------------


@pytest.fixture
def perfil_demo():
    perfis = {p.slug: p for p in carregar_perfis()}
    return perfis["demo-leiloes-nordeste"]


def test_engine_declarativa_extrai_todos_os_campos(perfil_demo):
    conector = ConectorDeclarativo(perfil_demo)
    lotes = conector.parse(
        carregar_html("demo_leiloes_nordeste.html"), "https://exemplo.invalid/leiloes"
    )
    # O terceiro <article> nao tem sinal financeiro nenhum: e descartado.
    assert len(lotes) == 2

    imovel = lotes[0]
    assert imovel.titulo == "Apartamento 2 quartos no Farol, Maceió/AL"
    assert imovel.numero_lote == "001"
    assert imovel.tipo_bem is TipoBem.IMOVEL
    assert imovel.valor_avaliacao == Decimal("320000.00")
    assert imovel.numero_processo == "0710702-95.2021.8.02.0001"
    assert imovel.comarca == "Maceió"
    assert imovel.cidade == "Maceió"
    assert imovel.bairro == "Farol"
    assert imovel.comissao_percentual == Decimal("5")
    assert imovel.status is StatusLote.ABERTO
    assert imovel.fonte_url == "https://exemplo.invalid/lote/1"
    assert [d.url for d in imovel.documentos] == ["https://exemplo.invalid/editais/lote1.pdf"]
    assert imovel.fotos == [
        "https://exemplo.invalid/fotos/lote1-a.jpg",
        "https://exemplo.invalid/fotos/lote1-b.jpg",
    ]

    pracas = {p.ordem: p for p in imovel.pracas}
    assert pracas[1].valor_minimo == Decimal("320000.00")
    assert pracas[2].valor_minimo == Decimal("160000.00")
    assert pracas[1].data_hora.day == 10
    assert pracas[2].data_hora.day == 24

    veiculo = lotes[1]
    assert veiculo.tipo_bem is TipoBem.VEICULO
    assert veiculo.valor_avaliacao == Decimal("28500.00")


def test_engine_declarativa_com_seletores_por_substring():
    """Os perfis nao validados usam [class*=card]; isso precisa funcionar."""
    perfil = {p.slug: p for p in carregar_perfis()}["superbid"]
    conector = ConectorDeclarativo(perfil)
    lotes = conector.parse(
        carregar_html("plataforma_generica.html"), "https://www.superbid.net/x"
    )
    assert len(lotes) == 2
    casa = lotes[0]
    assert "Olinda" in casa.titulo
    assert casa.valor_avaliacao == Decimal("450000.00")
    assert casa.numero_processo == "0055012-25.2024.8.17.2001"
    pracas = {p.ordem: p for p in casa.pracas}
    assert pracas[1].valor_minimo == Decimal("450000.00")
    assert pracas[2].valor_minimo == Decimal("225000.00")
    assert pracas[1].data_hora.day == 5
    assert lotes[1].valor_avaliacao == Decimal("120000.00")


def test_engine_levanta_quando_pagina_nao_tem_lotes(perfil_demo):
    conector = ConectorDeclarativo(perfil_demo)
    assert conector.parse("<html><body><h1>Nada</h1></body></html>", "u") == []


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Apartamento 2 quartos", TipoBem.IMOVEL),
        ("Veículo Fiat Uno", TipoBem.VEICULO),
        ("Motocicleta Honda CG", TipoBem.VEICULO),
        ("Terreno urbano", TipoBem.IMOVEL),
        ("Lote de jóias", TipoBem.OUTRO),
    ],
)
def test_inferir_tipo_bem(texto, esperado):
    assert inferir_tipo_bem(texto) is esperado


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("Arrematado por R$ 100", StatusLote.ARREMATADO),
        ("Leilão suspenso", StatusLote.SUSPENSO),
        ("Deserto - sem lance", StatusLote.DESERTO),
        ("Aberto para lances", StatusLote.ABERTO),
        ("", StatusLote.ABERTO),
    ],
)
def test_inferir_status(texto, esperado):
    assert inferir_status(texto) is esperado


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


def test_registro_tem_as_fontes_oficiais_do_spec():
    slugs = {c.slug for c in listar()}
    obrigatorias = {
        "tjal-banco-leiloeiros",
        "tjse-leiloeiros-credenciados",
        "tjse-leilao-judicial",
        "tjpe-leiloes-judiciais",
        "juceal-leiloeiros",
        "jucese-leiloeiros",
        "jucepe-leiloeiros",
        "datajud-hastas",
    }
    assert obrigatorias <= slugs


def test_registro_cobre_as_tres_ufs():
    for uf in ("AL", "SE", "PE"):
        assert listar(uf=uf), f"nenhuma fonte para {uf}"


def test_pelo_menos_dez_conectores_de_leiloeiro():
    # Criterio de aceite do MVP (secao 14). Configurados; a validacao ao vivo
    # de cada um e rastreada por meta.validado_ao_vivo.
    assert len(listar(tipo=TipoFonte.LEILOEIRO)) >= 10


def test_fonte_desconhecida_da_erro_util():
    with pytest.raises(KeyError, match="Disponiveis"):
        obter("nao-existe")
