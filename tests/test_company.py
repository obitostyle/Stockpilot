import pytest

from stockpilot.domain.enums import TaxRegime
from stockpilot.domain.errors import ValidationError
from stockpilot.services import company_service as cs
from stockpilot.services.schemas import CompanyInput, build


def test_salvar_e_atualizar_empresa(session):
    assert cs.get_company(session) is None
    data = build(CompanyInput, legal_name="Loja Exemplo LTDA", cnpj="11.222.333/0001-81",
                 tax_regime="SIMPLES_NACIONAL", cnae_primary="4781-4/00",
                 cnae_secondary=["4782-2/01", "4781400", ""], email="contato@loja.com.br")
    c = cs.save_company(session, data)
    assert c.cnpj == "11222333000181" and c.tax_regime == TaxRegime.SIMPLES_NACIONAL
    assert [x.code for x in c.cnaes] == ["4781400", "4782201"]  # sem duplicar o principal
    data2 = build(CompanyInput, legal_name="Loja Exemplo ME", cnpj="12.ABC.345/01DE-35")
    c2 = cs.save_company(session, data2)
    assert c2.id == c.id and c2.legal_name == "Loja Exemplo ME" and c2.cnaes == []


def test_empresa_validacoes():
    with pytest.raises(ValidationError) as e:
        build(CompanyInput, legal_name="", cnpj="123", email="x", cnae_primary="12")
    msg = str(e.value)
    assert "Razão social" in msg and "CNPJ" in msg and "E-mail" in msg and "CNAE principal" in msg
