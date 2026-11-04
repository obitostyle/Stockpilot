from datetime import date
from decimal import Decimal as D

import pytest

from stockpilot.domain.enums import AssessmentStatus, TaxRegime
from stockpilot.domain.errors import MissingRuleError, ValidationError
from stockpilot.models import Company
from stockpilot.services import tax_rules as tr
from stockpilot.services import tax_service as ts


def company(session, regime, start):
    c = Company(legal_name="X LTDA", cnpj="11222333000181", tax_regime=regime, activity_start_date=start)
    session.add(c)
    session.flush()
    return c


def fill(session, start_comp, n, amount):
    for i in range(n):
        ts.set_revenue(session, ts.add_comp(start_comp, i), "COMERCIO", D(amount))


def test_seed_tem_fonte_e_vigencia(session):
    tabs = {t.code: t for t in tr.list_tables(session)}
    assert set(tabs) >= {"SIMPLES_ANEXO_I", "INSS_EMPREGADO", "IRRF_MENSAL"}
    for t in tabs.values():
        assert t.source and t.legal_basis and t.verified_at and t.valid_from
    assert len(tabs["SIMPLES_ANEXO_I"].brackets) == 6


def test_simples_aliquota_efetiva_rbt_360k(session):
    # (360000*7,3% - 5940)/360000 = 5,65%
    c = company(session, TaxRegime.SIMPLES_NACIONAL, date(2025, 1, 1))
    fill(session, "2025-11", 12, "30000")  # 12 meses anteriores = 360.000
    ts.set_revenue(session, "2026-11", "COMERCIO", D("20000"))
    r = ts.assess_simples(session, "2026-11", c)
    assert r.rbt12 == D("360000")
    assert r.effective_rate == D("5.650000")
    assert r.amount == D("1130.00")
    assert r.due_date == date(2026, 12, 20)
    assert r.status == AssessmentStatus.ESTIMATIVA
    assert any("ICMS-ST" in w for w in r.warnings)


def test_simples_primeira_faixa_e_limites(session):
    c = company(session, TaxRegime.SIMPLES_NACIONAL, date(2026, 11, 1))
    ts.set_revenue(session, "2026-11", "COMERCIO", D("10000"))
    r = ts.assess_simples(session, "2026-11", c)  # 1º mês: 10.000*12 = 120.000 -> 4%
    assert r.rbt12 == D("120000") and r.effective_rate == D("4.000000") and r.amount == D("400.00")


def test_rbt12_media_meses_iniciais(session):
    ts.set_revenue(session, "2026-09", "COMERCIO", D("1000"))
    ts.set_revenue(session, "2026-10", "COMERCIO", D("3000"))
    ts.set_revenue(session, "2026-11", "COMERCIO", D("5000"))
    r = ts.compute_rbt12(session, "2026-11", date(2026, 9, 5))
    assert r.value == D("24000.00")  # média(1000,3000)=2000 * 12


def test_meses_sem_dado_deixam_incompleta(session):
    c = company(session, TaxRegime.SIMPLES_NACIONAL, date(2024, 1, 1))
    ts.set_revenue(session, "2026-11", "COMERCIO", D("1000"))
    r = ts.assess_simples(session, "2026-11", c)
    assert r.status == AssessmentStatus.INCOMPLETA
    assert any("sem registro" in m for m in r.missing)


def test_2027_avisa_regra_nao_implementada(session):
    c = company(session, TaxRegime.SIMPLES_NACIONAL, date(2024, 1, 1))
    r = ts.assess_simples(session, "2027-02", c)
    assert r.status == AssessmentStatus.INCOMPLETA
    assert any("190/2026" in w for w in r.warnings)


def test_mei_valores_2026(session):
    c = company(session, TaxRegime.MEI, date(2020, 1, 1))
    assert ts.assess_mei(session, "2026-05", c, "COMERCIO").amount == D("82.05")
    assert ts.assess_mei(session, "2026-05", c, "SERVICOS").amount == D("86.05")
    assert ts.assess_mei(session, "2026-05", c, "AMBOS").amount == D("87.05")


def test_mei_limite_proporcional_e_aviso(session):
    c = company(session, TaxRegime.MEI, date(2026, 7, 10))
    ts.set_revenue(session, "2026-07", "COMERCIO", D("45000"))
    r = ts.assess_mei(session, "2026-07", c)
    limite = dict(r.breakdown)["Limite anual aplicável"]
    assert limite == D("6750") * 6  # jul..dez
    assert any("ATENÇÃO" in w for w in r.warnings)


def test_regimes_nao_calculados(session):
    c = company(session, TaxRegime.LUCRO_PRESUMIDO, date(2020, 1, 1))
    with pytest.raises(MissingRuleError, match="não está implementado"):
        ts.assess(session, "2026-05", c)


def test_sem_tabela_vigente_nao_chuta(session):
    with pytest.raises(MissingRuleError):
        tr.get_table(session, "IRRF_MENSAL", date(2035, 1, 1))


def test_nova_versao_encerra_anterior_e_exige_fonte(session):
    with pytest.raises(ValidationError):
        tr.add_table_version(session, code="IRRF_MENSAL", description="d", valid_from=date(2027, 1, 1),
                             legal_basis="x", source="", rows=[(None, D("0"), D("0"))])
    tr.add_table_version(session, code="IRRF_MENSAL", description="2027", valid_from=date(2027, 1, 1),
                         legal_basis="lei", source="receita", rows=[(None, D("10"), D("0"))])
    assert tr.get_table(session, "IRRF_MENSAL", date(2026, 6, 1)).valid_to == date(2026, 12, 31)
    assert tr.get_table(session, "IRRF_MENSAL", date(2027, 6, 1)).description == "2027"


def test_save_assessment_substitui_sem_apagar(session):
    c = company(session, TaxRegime.MEI, date(2020, 1, 1))
    a1 = ts.save_assessment(session, ts.assess_mei(session, "2026-05", c))
    a2 = ts.save_assessment(session, ts.assess_mei(session, "2026-05", c))
    assert a1.superseded and not a2.superseded
    assert len(ts.list_assessments(session, include_superseded=True)) == 2
    assert len(ts.list_obligations(session)) == 1
    ts.mark_paid(session, a2.id, D("82.05"), date(2026, 6, 19))
    assert ts.list_obligations(session, only_pending=True) == []


def test_faturamento_vem_das_vendas_quando_nao_informado(session):
    from tests.conftest import make_product  # noqa
    mr = ts.month_revenue(session, "2026-03")
    assert not mr.has_data and mr.source == "sem dados"
