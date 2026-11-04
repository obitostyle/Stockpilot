from decimal import Decimal

import pytest

from stockpilot.domain import formatting as f
from stockpilot.domain import validators as v


def test_cnpj_numerico_valido():
    assert v.validate_cnpj("11.222.333/0001-81")
    assert v.validate_cnpj("00.000.000/0001-91")  # Banco do Brasil


def test_cnpj_alfanumerico_vetor_oficial_receita():
    # Exemplo oficial da Receita/Serpro: 12.ABC.345/01DE-35
    assert v.validate_cnpj("12.ABC.345/01DE-35")
    assert v.validate_cnpj("12abc34501de35")  # minúsculas e sem máscara


def test_cnpj_invalidos():
    assert not v.validate_cnpj("12.ABC.345/01DE-36")
    assert not v.validate_cnpj("11.222.333/0001-82")
    assert not v.validate_cnpj("00.000.000/0000-00")
    assert not v.validate_cnpj("11.111.111/1111-11")
    assert not v.validate_cnpj("123")
    assert not v.validate_cnpj("")
    assert not v.validate_cnpj(None)
    assert not v.validate_cnpj("12.ABC.345/01DE-3A")  # DV deve ser numérico


def test_format_cnpj():
    assert v.format_cnpj("12abc34501de35") == "12.ABC.345/01DE-35"


def test_cpf():
    assert v.validate_cpf("529.982.247-25")
    assert not v.validate_cpf("529.982.247-24")
    assert not v.validate_cpf("111.111.111-11")
    assert v.format_cpf("52998224725") == "529.982.247-25"
    assert v.validate_cpf_or_cnpj("52998224725")
    assert v.validate_cpf_or_cnpj("11222333000181")
    assert not v.validate_cpf_or_cnpj("11222333000182")


def test_cnae_email():
    assert v.validate_cnae("4781-4/00") and not v.validate_cnae("4781-4")
    assert v.format_cnae("4781400") == "4781-4/00"
    assert v.validate_email("a@b.com") and not v.validate_email("a@b")


def test_format_brl_e_qty():
    assert f.format_brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert f.format_brl(Decimal("-0.005")) == "-R$ 0,01"
    assert f.format_brl(None) == "—"
    assert f.format_qty(Decimal("3.000")) == "3"
    assert f.format_qty(Decimal("2.500")) == "2,5"
    assert f.format_qty(Decimal("1234.125")) == "1.234,125"


@pytest.mark.parametrize("txt,exp", [
    ("1.234,56", "1234.56"), ("1234,56", "1234.56"), ("R$ 12,50", "12.50"),
    ("1.5", "1.5"), ("1.234", "1234"), ("2", "2"), ("0,333", "0.333"),
])
def test_parse_decimal_br(txt, exp):
    assert f.parse_decimal_br(txt) == Decimal(exp)


@pytest.mark.parametrize("bad", ["", "abc", "1,2,3", "NaN", "Infinity"])
def test_parse_decimal_br_invalid(bad):
    with pytest.raises(ValueError):
        f.parse_decimal_br(bad)
