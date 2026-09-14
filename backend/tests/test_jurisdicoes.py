"""Tabela canônica de jurisdições (radar.jurisdicoes).

Existe para que acrescentar um estado seja acrescentar uma linha. Estes testes
guardam essa promessa: se alguém acrescentar a UF no enum e esquecer da tabela
(ou vice-versa), quebra aqui e não em produção com lote sem tribunal.
"""

from __future__ import annotations

import pytest

from radar.collectors.base import listar
from radar.enums import UF, JuntaComercial
from radar.jurisdicoes import (
    INDICES_DATAJUD,
    JURISDICOES,
    SIGLAS,
    TRIBUNAL_POR_UF,
    UF_POR_TRIBUNAL,
    UFS,
    tribunal_por_codigo_tr,
    uf_valida,
)
from radar.normalizacao import formatar_cnj, numero_cnj_valido, tribunal_do_cnj


def test_cobre_os_quatro_estados():
    assert set(UFS) == {"AL", "BA", "PE", "SE"}
    assert set(SIGLAS) == {"TJAL", "TJBA", "TJPE", "TJSE"}


def test_enum_uf_e_tabela_nao_divergem():
    """O enum e a tabela têm de descrever o mesmo conjunto de estados."""
    assert {str(u) for u in UF} == set(UFS)


def test_codigos_tr_sao_unicos():
    codigos = [j.codigo_tr for j in JURISDICOES]
    assert len(codigos) == len(set(codigos))


def test_mapeamentos_sao_inversos():
    for sigla, uf in UF_POR_TRIBUNAL.items():
        assert TRIBUNAL_POR_UF[uf] == sigla


@pytest.mark.parametrize(
    "tr,sigla", [("02", "TJAL"), ("05", "TJBA"), ("17", "TJPE"), ("25", "TJSE")]
)
def test_numero_cnj_resolve_o_tribunal(tr, sigla):
    numero = formatar_cnj("123456", "2026", "8", tr, "0001")
    assert numero_cnj_valido(numero)
    assert tribunal_do_cnj(numero) == sigla
    assert tribunal_por_codigo_tr(tr) == sigla


def test_tribunal_fora_do_escopo_nao_resolve():
    # Justiça estadual de São Paulo (TR 26) não é coberta pelo produto.
    assert tribunal_do_cnj(formatar_cnj("1", "2026", "8", "26", "0001")) is None
    # Justiça federal da 2ª Região (RJ/ES): segmento coberto, região não.
    assert tribunal_do_cnj(formatar_cnj("1", "2026", "4", "02", "0001")) is None
    # Trabalhista (segmento 5) está fora inteira.
    assert tribunal_do_cnj(formatar_cnj("1", "2026", "5", "19", "0001")) is None


def test_segmento_separa_tribunal_estadual_de_federal():
    """O par TR 05 é TJBA no segmento 8 e TRF5 no segmento 4.

    Os dois números passam no dígito verificador, então ignorar o segmento não
    dá erro: dá um processo federal de Pernambuco entrando como estadual da
    Bahia, e o lote aparecendo no filtro do estado errado.
    """
    assert tribunal_do_cnj(formatar_cnj("1", "2026", "8", "05", "0001")) == "TJBA"
    assert tribunal_do_cnj(formatar_cnj("1", "2026", "4", "05", "8200")) == "TRF5"


def test_uf_valida():
    assert uf_valida("ba") and uf_valida("BA")
    assert not uf_valida("SP")
    assert not uf_valida(None)


def test_todo_estado_tem_indice_datajud():
    assert set(INDICES_DATAJUD) == set(SIGLAS)
    assert INDICES_DATAJUD["TJBA"] == "api_publica_tjba"


def test_todo_estado_tem_conector_de_cadastro_de_leiloeiro():
    """Sem isso, um estado entra no sistema sem caminho para popular leiloeiros."""
    for uf in UFS:
        fontes = {c.slug for c in listar(uf=uf)}
        assert fontes, f"nenhuma fonte para {uf}"


def test_bahia_tem_junta_e_tribunal_registrados():
    slugs = {c.slug for c in listar(uf="BA")}
    assert {"juceb-leiloeiros", "tjba-leiloeiros-credenciados", "tjba-leiloes-judiciais"} <= slugs
    assert JuntaComercial.JUCEB in set(JuntaComercial)


def test_fontes_da_bahia_nascem_nao_validadas():
    """As URLs do TJBA e da JUCEB são candidatas, não confirmadas. Elas não
    podem entrar na coleta automática antes de alguém conferir."""
    for conector in listar(uf="BA"):
        if conector.slug.startswith(("tjba", "juceb")):
            assert conector.meta.validado_ao_vivo is False
            assert "CANDIDATA" in conector.meta.descricao.upper()
