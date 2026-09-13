from datetime import date
from decimal import Decimal

import pytest

from radar.normalizacao import (
    extrair_numero_cnj,
    formatar_cnj,
    mascarar_placa,
    numero_cnj_valido,
    para_local,
    parse_area,
    parse_data,
    parse_data_hora,
    parse_moeda,
    parse_percentual,
    remover_cpf,
    slugify,
    tribunal_do_cnj,
)


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("R$ 1.234.567,89", Decimal("1234567.89")),
        ("R$ 85.000,00", Decimal("85000.00")),
        ("1.500", Decimal("1500")),
        ("R$ 250 mil", Decimal("250000")),
        ("R$ 1,2 milhões", Decimal("1200000.0")),
        ("valor de avaliação: R$ 320.000,00.", Decimal("320000.00")),
        ("sem valor", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_moeda(entrada, esperado):
    assert parse_moeda(entrada) == esperado


def test_parse_percentual_rejeita_fora_da_faixa():
    assert parse_percentual("50% do valor") == Decimal("50")
    assert parse_percentual("5,5%") == Decimal("5.5")
    assert parse_percentual("250%") is None
    assert parse_percentual("sem percentual") is None


@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("15/03/2026", date(2026, 3, 15)),
        ("15-03-2026", date(2026, 3, 15)),
        ("15 de março de 2026", date(2026, 3, 15)),
        ("1 de janeiro de 2027", date(2027, 1, 1)),
        ("31/02/2026", None),  # data impossivel
        ("sem data", None),
    ],
)
def test_parse_data(entrada, esperado):
    assert parse_data(entrada) == esperado


def test_parse_data_hora_converte_de_brasilia_para_utc():
    dt = parse_data_hora("15/03/2026 às 14h30")
    assert dt is not None
    assert (dt.hour, dt.minute) == (17, 30)  # 14h30 em UTC-3
    local = para_local(dt)
    assert (local.hour, local.minute) == (14, 30)


def test_parse_data_hora_sem_hora_usa_meia_noite():
    dt = parse_data_hora("15/03/2026")
    assert dt.hour == 3  # 00h00 local = 03h UTC


def test_cnj_ida_e_volta():
    numero = formatar_cnj("710702", "2021", "8", "02", "0001")
    assert numero_cnj_valido(numero)
    assert tribunal_do_cnj(numero) == "TJAL"
    assert extrair_numero_cnj(f"Processo nº {numero} da 3ª Vara") == numero
    # Sem formatacao nenhuma tambem tem de funcionar.
    assert extrair_numero_cnj(numero.replace("-", "").replace(".", "")) == numero


def test_cnj_invalido_e_rejeitado():
    assert not numero_cnj_valido("0000000-00.0000.0.00.0000")
    assert not numero_cnj_valido("123")
    assert not numero_cnj_valido(None)
    assert tribunal_do_cnj(formatar_cnj("1", "2024", "4", "05", "0001")) is None  # federal


def test_minimizacao_lgpd():
    assert mascarar_placa("OKZ1D23") == "OKZ1**3"
    assert mascarar_placa("ABC-1234") == "ABC1**4"
    assert mascarar_placa("nao e placa") is None
    assert "[CPF removido]" in remover_cpf("CPF 123.456.789-00 do executado")
    assert "123.456.789-00" not in remover_cpf("CPF 123.456.789-00")


def test_parse_area_e_slug():
    assert parse_area("área total de 120,50 m²") == Decimal("120.50")
    assert parse_area("1.200m2") == Decimal("1200")
    assert slugify("Palmeira dos Índios / AL") == "palmeira-dos-indios-al"
