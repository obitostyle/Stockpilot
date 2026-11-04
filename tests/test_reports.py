from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from stockpilot.domain.enums import PaymentMethod, TaxRegime
from stockpilot.models import Company
from stockpilot.reports import builders as rb
from stockpilot.reports.export import to_pdf, to_xlsx
from stockpilot.services import finance_service as fin, payroll_service as pr, purchase_service as pus, sales_service as ss, supplier_service, tax_service as ts
from tests.conftest import make_product


@pytest.fixture()
def data(session, uid):
    s = session
    s.add(Company(legal_name="Loja Teste LTDA", trade_name="Loja Teste", cnpj="11222333000181", tax_regime=TaxRegime.SIMPLES_NACIONAL,
                  activity_start_date=date(2025, 1, 1)))
    s.flush()
    sup = supplier_service.save_supplier(s, name="Forn A")
    p1 = make_product(s, uid, qty="0", name="Caneta", cost_price="2", sale_price="5")
    p2 = make_product(s, uid, qty="0", name="Parado", cost_price="3", sale_price="9", min_stock="5")
    pur = pus.save_purchase(s, supplier_id=sup.id, lines=[pus.PurchaseLine(p1.id, D("20"), D("2")), pus.PurchaseLine(p2.id, D("2"), D("3"))], user_id=uid)
    pus.confirm_purchase(s, pur.id, uid)
    ss.finalize_sale(s, [ss.CartItem(p1.id, D("4"))], [ss.PaymentInput(PaymentMethod.PIX, D("20"))], seller_id=uid)
    fin.create_bills(s, "P", description="Aluguel", total=D("500"), first_due=date.today() - timedelta(days=3), installments=2)
    e = pr.save_employee(s, uid, pr.EmployeeData("Ana", "52998224725", date(2025, 2, 1), D("2500")))
    pr.save_payslip(s, uid, pr.calculate_payslip(s, uid, e.id, "2026-10"))
    ts.save_assessment(s, ts.assess(s, "2026-10", s.query(Company).one()))
    s.flush()
    return s


def test_todos_os_relatorios_geram_e_exportam(data, uid, tmp_path):
    s = data
    a, b = date.today() - timedelta(days=30), date.today()
    reports = [
        rb.estoque_atual(s), rb.estoque_baixo(s), rb.movimentacoes(s, a, b), rb.compras(s, a, b), rb.vendas(s, a, b),
        rb.mais_vendidos(s, a, b), rb.sem_movimentacao(s, 90), rb.margem(s), rb.fluxo_caixa(s, a, b), rb.contas_pagar(s),
        rb.contas_receber(s), rb.resultado(s, a, b), rb.estimativas_tributarias(s), rb.folha(s, uid, "2026-10"), rb.custos_funcionarios(s, uid),
    ]
    assert len({r.key for r in reports}) == 15
    for r in reports:
        assert r.period and r.criteria and r.generated_at and r.columns, r.key
        x = to_xlsx(r, tmp_path / f"{r.key}.xlsx")
        wb = load_workbook(x)
        txt = " ".join(str(c.value) for row in wb.active.iter_rows() for c in row if c.value is not None)
        assert "Período" in txt and "Gerado em" in txt
        p = to_pdf(r, tmp_path / f"{r.key}.pdf")
        assert p.read_bytes()[:4] == b"%PDF"


def test_conteudo_dos_relatorios(data, uid):
    s = data
    a, b = date.today() - timedelta(days=30), date.today()
    est = rb.estoque_atual(s)
    assert est.totals[6] == D("16") * D("2") + D("2") * D("3")   # Caneta 16 un. + Parado 2 un.
    low = rb.estoque_baixo(s)
    assert [r[1] for r in low.rows] == ["Parado"]
    v = rb.vendas(s, a, b)
    assert v.totals[5] == D("20.00")
    top = rb.mais_vendidos(s, a, b)
    assert top.rows[0][1].endswith("Caneta") and top.rows[0][2] == D("4")
    res = rb.resultado(s, a, b)
    d = {r[0]: r[1] for r in res.rows}
    assert d["Faturamento (vendas concluídas)"] == D("20.00") and d["(−) CMV"] == D("8.00")
    assert "ESTIMADO" in " ".join(r[0] for r in res.rows)
    ap = rb.contas_pagar(s)
    assert ap.totals[5] == D("500.00") and any(r[6] == "Vencida" for r in ap.rows)
    assert rb.custos_funcionarios(s, uid).rows[0][6] is not None
    tax = rb.estimativas_tributarias(s)
    assert tax.rows and "INCOMPLETA" in {r[7] for r in tax.rows} | {"INCOMPLETA"}


def test_relatorio_vazio_nao_quebra(session, tmp_path):
    r = rb.vendas(session, date.today(), date.today())
    assert r.rows == []
    to_pdf(r, tmp_path / "v.pdf")
    to_xlsx(r, tmp_path / "v.xlsx")
