from datetime import date
from decimal import Decimal as D

import pytest

from stockpilot.domain.enums import EmployeeStatus, TaxRegime, UserRole
from stockpilot.domain.errors import PermissionDeniedError, ValidationError
from stockpilot.models import Company, User
from stockpilot.services import payroll_service as ps
from stockpilot.services import settings_service as st

REF = date(2026, 6, 1)


def emp(session, uid, salary="3000", cpf="52998224725", **kw):
    return ps.save_employee(session, uid, ps.EmployeeData("Maria Silva", cpf, date(2024, 3, 10), D(salary), **kw))


def test_inss_vetores_oficiais(session):
    assert ps.inss_employee(session, D("1621.00"), REF) == D("121.58")
    assert ps.inss_employee(session, D("8475.55"), REF) == D("988.09")
    assert ps.inss_employee(session, D("50000"), REF) == D("988.09")   # teto
    assert ps.inss_employee(session, D("0"), REF) == D("0.00")


def test_irrf_faixas_e_reducao(session):
    # isenção até 5.000 pela Lei 15.270
    tax, _ = ps.irrf_monthly(session, D("5000"), D("500"), 0, REF)
    assert tax == D("0.00")
    # redução: 978,62 - 0,133145*6000 = 179,75 (vetor da fonte)
    assert ps.q2(ps.irrf_reduction(session, D("6000"), REF)) == D("179.75")
    assert ps.irrf_reduction(session, D("7350.01"), REF) == 0
    # sem redução, renda 3.000 e INSS 300: legal = 2.700 -> 15% - 394,16 = 10,84 ; simplificado = 2.392,80 -> isento
    tax, how = ps.irrf_monthly(session, D("3000"), D("300"), 0, REF, apply_reduction=False)
    assert tax == D("0.00") and "simplificado" in how
    # renda 6.000: INSS pelas faixas, escolhe a opção de menor imposto, depois aplica a redução de 179,75
    inss = ps.inss_employee(session, D("6000"), REF)
    sem, _ = ps.irrf_monthly(session, D("6000"), inss, 0, REF, apply_reduction=False)
    com, _ = ps.irrf_monthly(session, D("6000"), inss, 0, REF)
    assert sem - com == D("179.75") and com > 0
    t0, _ = ps.irrf_monthly(session, D("8000"), D("900"), 2, REF)
    # acima de 7.350: sem redução; base legal = 8000-900-379,18
    assert t0 == ps.q2((D("8000") - D("900") - D("189.59") * 2) * D("0.275") - D("908.73"))


def test_holerite_basico(session, uid):
    e = emp(session, uid, "3000")
    r = ps.calculate_payslip(session, uid, e.id, "2026-06")
    assert r.gross == D("3000.00")
    assert r.inss == ps.inss_employee(session, D("3000"), REF)
    assert r.net == r.gross - r.inss - r.irrf - r.other_deductions
    assert r.fgts == D("240.00")
    assert any("Regime tributário" in m for m in r.missing)
    assert r.total_cost is None   # faltam dados -> não inventa custo total


def test_horas_extras_e_dsr(session, uid):
    e = emp(session, uid, "2200")  # 220h -> R$ 10/h
    r = ps.calculate_payslip(session, uid, e.id, "2026-06", ps.PayrollInputs(overtime_hours=D("10")))
    assert [l.value for l in r.lines if l.code == "HE"] == [D("150.00")]
    assert any("DSR" in m for m in r.missing)
    r2 = ps.calculate_payslip(session, uid, e.id, "2026-06",
                              ps.PayrollInputs(overtime_hours=D("10"), dsr_days_off=5, dsr_workdays=25))
    assert [l.value for l in r2.lines if l.code == "DSR"] == [D("30.00")]
    assert r2.gross == D("2380.00")


def test_faltas_atrasos_noturno(session, uid):
    e = emp(session, uid, "2200")
    r = ps.calculate_payslip(session, uid, e.id, "2026-06",
                             ps.PayrollInputs(absence_days=D("2"), late_minutes=D("30"), night_hours=D("10")))
    # 2*2200/30=146.67 ; 0,5h*10=5 ; noturno 10*10*0,2=20
    assert r.gross == D("2200") + D("20.00") - D("146.67") - D("5.00")


def test_encargos_por_regime(session, uid):
    e = emp(session, uid, "2000")
    session.add(Company(legal_name="X", cnpj="11222333000181", tax_regime=TaxRegime.SIMPLES_NACIONAL))
    session.flush()
    r = ps.calculate_payslip(session, uid, e.id, "2026-06")
    assert r.patronal == 0 and r.total_cost == D("2000.00") + D("160.00")
    c = session.query(Company).one()
    c.tax_regime = TaxRegime.LUCRO_PRESUMIDO
    session.flush()
    r = ps.calculate_payslip(session, uid, e.id, "2026-06")
    assert r.patronal is None and any("RAT" in m for m in r.missing)
    st.set_setting(session, "rat_percent", "2")
    st.set_setting(session, "terceiros_percent", "5.8")
    r = ps.calculate_payslip(session, uid, e.id, "2026-06")
    assert r.patronal == D("2000") * D("27.8") / 100


def test_vt_limite_6_porcento(session, uid):
    e = emp(session, uid, "2000", vt_enabled=True, vt_monthly_cost=D("300"))
    r = ps.calculate_payslip(session, uid, e.id, "2026-06")
    assert [l.value for l in r.lines if l.code == "VT"] == [D("120.00")]
    e2 = emp(session, uid, "2000", cpf="11144477735", vt_enabled=True, vt_monthly_cost=D("90"))
    r = ps.calculate_payslip(session, uid, e2.id, "2026-06")
    assert [l.value for l in r.lines if l.code == "VT"] == [D("90")]


def test_acesso_restrito(session, uid):
    op = User(username="op", full_name="Op", role=UserRole.OPERADOR)
    session.add(op)
    session.flush()
    with pytest.raises(PermissionDeniedError):
        ps.list_employees(session, op.id)
    with pytest.raises(PermissionDeniedError):
        ps.save_employee(session, op.id, ps.EmployeeData("A", "52998224725", date(2024, 1, 1), D("1000")))
    with pytest.raises(PermissionDeniedError):
        ps.list_employees(session, None)


def test_validacoes_cadastro(session, uid):
    with pytest.raises(ValidationError, match="CPF"):
        emp(session, uid, cpf="11111111111")
    emp(session, uid)
    with pytest.raises(ValidationError, match="CPF"):
        emp(session, uid)  # duplicado
    with pytest.raises(ValidationError):
        emp(session, uid, cpf="11144477735", overtime_pct=D("30"))


def test_historico_salarial_e_desligamento(session, uid):
    e = emp(session, uid, "2000")
    ps.save_employee(session, uid, ps.EmployeeData("Maria Silva", "52998224725", date(2024, 3, 10), D("2400")), e.id, "Dissídio")
    e = ps.get_employee(session, uid, e.id)
    assert [h.salary for h in e.salary_history] == [D("2000"), D("2400")]
    with pytest.raises(ValidationError):
        ps.set_status(session, uid, e.id, EmployeeStatus.DESLIGADO)
    ps.set_status(session, uid, e.id, EmployeeStatus.DESLIGADO, date(2026, 5, 31))
    assert len(ps.list_employees(session, uid, include_terminated=False)) == 0


def test_salvar_holerite_substitui(session, uid):
    e = emp(session, uid)
    r = ps.calculate_payslip(session, uid, e.id, "2026-06")
    a = ps.save_payslip(session, uid, r)
    b = ps.save_payslip(session, uid, r)
    assert a.superseded and not b.superseded
    assert len(ps.payroll_history(session, uid, "2026-06")) == 1


def test_13o_e_ferias(session, uid):
    e = emp(session, uid, "3000")
    e.admission_date = date(2025, 1, 1)
    r = ps.simulate_13th(session, uid, e.id, 2026)
    assert r.total == D("3000.00")
    assert any("NÃO verificada" in w for w in r.warnings)
    f = ps.simulate_vacation(session, uid, e.id, date(2026, 7, 1), 30)
    assert f.total == D("4000.00")
    f2 = ps.simulate_vacation(session, uid, e.id, date(2026, 7, 1), 20, sell_days=10)
    assert f2.total == D("4000.00")
    with pytest.raises(ValidationError):
        ps.simulate_vacation(session, uid, e.id, date(2026, 7, 1), 25, sell_days=10)


def test_rescisao_sem_justa_causa(session, uid):
    e = emp(session, uid, "3000")
    e.admission_date = date(2023, 1, 10)
    r = ps.simulate_termination(session, uid, e.id, "SEM_JUSTA_CAUSA", date(2026, 6, 15), fgts_balance=D("10000"))
    d = dict(r.items)
    assert d["Multa do FGTS (40% do saldo informado)"] == D("4000.00")
    assert any("Aviso prévio indenizado (39 dias" in k for k in d)  # 30 + 3*3
    assert any("NÃO são calculados" in w for w in r.warnings)
    j = ps.simulate_termination(session, uid, e.id, "JUSTA_CAUSA", date(2026, 6, 15))
    assert not any("13º" in k or "proporcionais" in k for k, _ in j.items)


def test_rescisao_sem_saldo_fgts_lista_faltante(session, uid):
    e = emp(session, uid, "3000")
    r = ps.simulate_termination(session, uid, e.id, "ACORDO", date(2026, 6, 15))
    assert any("Saldo do FGTS" in m for m in r.missing)
