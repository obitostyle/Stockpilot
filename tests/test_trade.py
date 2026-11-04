from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from stockpilot.domain.enums import BillStatus, PaymentMethod as PM, PurchaseStatus, SaleStatus
from stockpilot.domain.errors import (
    DiscountNotAuthorizedError, DuplicateError, InsufficientStockError, ValidationError,
)
from stockpilot.services import finance_service as fin
from stockpilot.services import product_service as ps
from stockpilot.services import purchase_service as pu
from stockpilot.services import sales_service as ss
from stockpilot.services import stock_service as st
from stockpilot.services import supplier_service as sup
from conftest import make_product

TODAY = date.today()


def mk_supplier(session, name="Atacado Silva", doc="11.222.333/0001-81"):
    return sup.save_supplier(session, name=name, document=doc, phone="(21) 99999-0000")


# ---------------------------------------------------------------- fornecedores
def test_fornecedor_validacoes(session):
    s = mk_supplier(session)
    assert s.document == "11222333000181"
    with pytest.raises(DuplicateError):
        mk_supplier(session, "Outro")
    with pytest.raises(ValidationError):
        sup.save_supplier(session, name="X", document="123")
    with pytest.raises(ValidationError):
        sup.save_supplier(session, name="", document=None)
    cpf = sup.save_supplier(session, name="Zé", document="529.982.247-25")
    assert cpf.document == "52998224725"
    assert [x.name for x in sup.list_suppliers(session, "silva")] == ["Atacado Silva"]


# ---------------------------------------------------------------- compras
def test_compra_a_vista_atualiza_estoque_custo_e_caixa(session, uid):
    p = make_product(session, uid, qty="0", cost_price="0", name="Camiseta")
    s = mk_supplier(session)
    pur = pu.save_purchase(session, supplier_id=s.id, lines=[pu.PurchaseLine(p.id, D("10"), D("20"))],
                           discount=D("10"), extra_expenses=D("30"), user_id=uid)
    assert pur.status == PurchaseStatus.RASCUNHO and pur.total == D("220")
    assert p.quantity_on_hand == 0  # rascunho não mexe no estoque
    pu.confirm_purchase(session, pur.id, uid)
    assert p.quantity_on_hand == D("10")
    assert p.cost_price == D("22.0000")  # (200 - 10 + 30) / 10: custo de aquisição com rateio
    assert fin.total_cash_balance(session) == D("-220")
    assert st.verify_consistency(session) == []


def test_confirmar_duas_vezes_nao_duplica_estoque(session, uid):
    p = make_product(session, uid)
    s = mk_supplier(session)
    pur = pu.save_purchase(session, supplier_id=s.id, lines=[pu.PurchaseLine(p.id, D("5"), D("3"))])
    pu.confirm_purchase(session, pur.id, uid)
    with pytest.raises(ValidationError) as e:
        pu.confirm_purchase(session, pur.id, uid)
    assert "já foi confirmada" in str(e.value)
    assert p.quantity_on_hand == D("5") and fin.total_cash_balance(session) == D("-15")


def test_compra_a_prazo_gera_parcelas(session, uid):
    p = make_product(session, uid)
    s = mk_supplier(session)
    pur = pu.save_purchase(session, supplier_id=s.id, lines=[pu.PurchaseLine(p.id, D("3"), D("100"))],
                           payment_method=PM.A_PRAZO, installments=3, first_due_date=TODAY + timedelta(days=30))
    pu.confirm_purchase(session, pur.id, uid)
    bills = fin.list_bills(session, "P")
    assert [b.amount for b in bills] == [D("100"), D("100"), D("100")] and len(bills) == 3
    assert fin.total_cash_balance(session) == 0          # nada saiu do caixa ainda
    assert fin.open_total(session, "P") == D("300")
    with pytest.raises(ValidationError):  # a prazo exige vencimento
        pu.save_purchase(session, supplier_id=s.id, lines=[pu.PurchaseLine(p.id, D("1"), D("1"))],
                         payment_method=PM.A_PRAZO)


def test_parcelas_somam_exato():
    parts = fin._split(D("100.00"), 3)
    assert parts == [D("33.33"), D("33.33"), D("33.34")] and sum(parts) == D("100.00")


def test_compra_validacoes(session):
    p = make_product(session)
    s = mk_supplier(session)
    L = pu.PurchaseLine
    for kw in ({"lines": []}, {"lines": [L(p.id, D("0"), D("1"))]}, {"lines": [L(p.id, D("1.5"), D("1"))]},
               {"lines": [L(p.id, D("1"), D("-1"))]}, {"lines": [L(p.id, D("1"), D("1")), L(p.id, D("1"), D("1"))]},
               {"lines": [L(p.id, D("1"), D("10"))], "discount": D("11")}):
        with pytest.raises(ValidationError):
            pu.save_purchase(session, supplier_id=s.id, **kw)


def test_cancelar_compra_reverte_estoque_e_caixa(session, uid):
    p = make_product(session, uid)
    s = mk_supplier(session)
    pur = pu.save_purchase(session, supplier_id=s.id, lines=[pu.PurchaseLine(p.id, D("4"), D("10"))])
    pu.confirm_purchase(session, pur.id, uid)
    pu.cancel_purchase(session, pur.id, "Pedido errado", uid)
    assert p.quantity_on_hand == 0 and fin.total_cash_balance(session) == 0
    assert pur.status == PurchaseStatus.CANCELADA
    with pytest.raises(ValidationError):
        pu.cancel_purchase(session, pur.id, "de novo", uid)


def test_cancelar_compra_com_mercadoria_vendida_falha_inteira(ctx, uid):
    with ctx.db.session_scope() as s:
        p = make_product(s, uid)
        sp = mk_supplier(s)
        pur = pu.save_purchase(s, supplier_id=sp.id, lines=[pu.PurchaseLine(p.id, D("2"), D("10"))])
        pu.confirm_purchase(s, pur.id, uid)
        ss.finalize_sale(s, [ss.CartItem(p.id, D("2"))], [ss.PaymentInput(PM.PIX, D("50"))], seller_id=uid)
        pid, purid = p.id, pur.id
    with pytest.raises(InsufficientStockError):
        with ctx.db.session_scope() as s:
            pu.cancel_purchase(s, purid, "tentando", uid)
    with ctx.db.session_scope() as s:
        assert pu.get_purchase(s, purid).status == PurchaseStatus.CONFIRMADA  # nada mudou
        assert st.verify_consistency(s) == []


# ---------------------------------------------------------------- vendas
def setup_prod(session, uid, qty="10", cost="6", price="10"):
    return make_product(session, uid, qty=qty, cost_price=cost, sale_price=price, name="Item")


def test_venda_a_vista_grava_tudo(session, uid):
    p = setup_prod(session, uid)
    sale = ss.finalize_sale(session, [ss.CartItem(p.id, D("3"))], [ss.PaymentInput(PM.DINHEIRO, D("50"))], seller_id=uid)
    assert sale.number == "V000001" and sale.total == D("30") and sale.change == D("20")
    assert [(x.method, x.amount) for x in sale.payments] == [(PM.DINHEIRO, D("30"))]  # troco não vira receita
    assert p.quantity_on_hand == D("7")
    assert sale.cogs == D("18.0000") and sale.items[0].unit_cost == D("6")
    assert fin.total_cash_balance(session) == D("30")
    r = fin.result_summary(session, TODAY, TODAY)
    assert (r.gross_revenue, r.cogs, r.gross_profit, r.receipts) == (D("30"), D("18"), D("12"), D("30"))
    assert st.verify_consistency(session) == []


def test_venda_pagamento_misto_e_troco_so_em_dinheiro(session, uid):
    p = setup_prod(session, uid)
    items = [ss.CartItem(p.id, D("5"))]  # total 50
    s = ss.finalize_sale(session, items, [ss.PaymentInput(PM.PIX, D("30")), ss.PaymentInput(PM.DINHEIRO, D("30"))], seller_id=uid)
    assert s.change == D("10") and sum(x.amount for x in s.payments) == D("50")
    with pytest.raises(ValidationError):  # troco sem dinheiro
        ss.finalize_sale(session, items, [ss.PaymentInput(PM.PIX, D("60"))], seller_id=uid)
    with pytest.raises(ValidationError):  # insuficiente
        ss.finalize_sale(session, items, [ss.PaymentInput(PM.PIX, D("49.99"))], seller_id=uid)


def test_venda_estoque_insuficiente_nao_deixa_rastro(ctx, uid):
    with ctx.db.session_scope() as s:
        a = setup_prod(s, uid, qty="5")
        b = make_product(s, uid, qty="1", name="Escasso", sale_price="10")
        ids = (a.id, b.id)
    with pytest.raises(InsufficientStockError):
        with ctx.db.session_scope() as s:
            ss.finalize_sale(s, [ss.CartItem(ids[0], D("2")), ss.CartItem(ids[1], D("2"))],
                             [ss.PaymentInput(PM.PIX, D("40"))], seller_id=uid)
    with ctx.db.session_scope() as s:
        assert ss.list_sales(s) == [] and ps.get_product(s, ids[0]).quantity_on_hand == D("5")
        assert fin.total_cash_balance(s) == 0 and st.verify_consistency(s) == []


def test_desconto_limite_e_autorizacao(session, uid):
    p = setup_prod(session, uid, qty="30")
    it = [ss.CartItem(p.id, D("10"))]  # 100
    ss.finalize_sale(session, it, [ss.PaymentInput(PM.PIX, D("90"))], seller_id=uid, sale_discount=D("10"))  # 10% ok
    with pytest.raises(DiscountNotAuthorizedError):
        ss.finalize_sale(session, [ss.CartItem(p.id, D("1"))], [ss.PaymentInput(PM.PIX, D("8"))], seller_id=uid, sale_discount=D("2"))
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("1"))], [ss.PaymentInput(PM.PIX, D("8"))], seller_id=uid,
                         sale_discount=D("2"), discount_authorized=True)
    assert s.total == D("8") and s.discount == D("2")
    with pytest.raises(ValidationError):
        ss.calculate(session, it, D("101"))


def test_desconto_rateado_soma_exata(session, uid):
    a = make_product(session, uid, qty="9", sale_price="3.33", name="A")
    b = make_product(session, uid, qty="9", sale_price="6.67", name="B")
    t = ss.calculate(session, [ss.CartItem(a.id, D("1")), ss.CartItem(b.id, D("1"))], D("0.50"))
    assert t.subtotal == D("10.00") and t.total == D("9.50") and sum(l[3] for l in t.lines) == D("9.50")


def test_venda_fracionada_por_peso(session, uid):
    q = make_product(session, uid, name="Queijo", unit="KG", cost_price="40", sale_price="59.90", qty="5")
    s = ss.finalize_sale(session, [ss.CartItem(q.id, D("0.350"))], [ss.PaymentInput(PM.PIX, D("20.97"))], seller_id=uid)
    assert s.total == D("20.97") and q.quantity_on_hand == D("4.650")
    u = setup_prod(session, uid)
    with pytest.raises(ValidationError):
        ss.calculate(session, [ss.CartItem(u.id, D("1.5"))])


def test_venda_a_prazo_gera_conta_a_receber_e_recebimento(session, uid):
    p = setup_prod(session, uid)
    due = TODAY + timedelta(days=15)
    with pytest.raises(ValidationError):  # fiado exige cliente
        ss.finalize_sale(session, [ss.CartItem(p.id, D("2"))], [ss.PaymentInput(PM.A_PRAZO, D("20"), due_date=due)], seller_id=uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("2"))],
                         [ss.PaymentInput(PM.A_PRAZO, D("20"), 2, due)], seller_id=uid, customer_name="Maria")
    assert fin.total_cash_balance(session) == 0           # faturou, mas ainda não recebeu
    r = fin.result_summary(session, TODAY, TODAY)
    assert r.gross_revenue == D("20") and r.receipts == 0 and r.receivable_open == D("20")
    bills = fin.list_bills(session, "R")
    assert [b.amount for b in bills] == [D("10"), D("10")]
    acc = fin.default_account(session)
    fin.pay_bill(session, "R", bills[0].id, D("10"), account_id=acc.id, user_id=uid)
    assert bills[0].status == BillStatus.PAGA and fin.total_cash_balance(session) == D("10")
    r = fin.result_summary(session, TODAY, TODAY)
    assert r.receipts == D("10") and r.receivable_open == D("10")


def test_cancelar_venda_reverte_estoque_e_financeiro(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("4"))], [ss.PaymentInput(PM.PIX, D("40"))], seller_id=uid)
    with pytest.raises(ValidationError):
        ss.cancel_sale(session, s.id, " ", uid)
    ss.cancel_sale(session, s.id, "Cliente desistiu", uid)
    assert s.status == SaleStatus.CANCELADA and p.quantity_on_hand == D("10")
    assert fin.total_cash_balance(session) == 0 and st.verify_consistency(session) == []
    r = fin.result_summary(session, TODAY, TODAY)
    assert r.gross_revenue == 0 and r.cogs == 0 and r.receipts == 0   # cancelada não afeta totais
    with pytest.raises(ValidationError):
        ss.cancel_sale(session, s.id, "de novo", uid)


def test_cancelar_venda_a_prazo_cancela_contas(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("1"))], [ss.PaymentInput(PM.A_PRAZO, D("10"), 1, TODAY)],
                         seller_id=uid, customer_name="João")
    ss.cancel_sale(session, s.id, "erro", uid)
    assert fin.open_total(session, "R") == 0


def test_cancelar_venda_com_recebimento_exige_estorno_antes(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("1"))], [ss.PaymentInput(PM.A_PRAZO, D("10"), 1, TODAY)],
                         seller_id=uid, customer_name="João")
    bill = fin.list_bills(session, "R")[0]
    tx = fin.pay_bill(session, "R", bill.id, D("10"), account_id=fin.default_account(session).id, user_id=uid)
    with pytest.raises(ValidationError):
        ss.cancel_sale(session, s.id, "erro", uid)
    fin.reverse_payment(session, tx.id, "recebimento lançado errado", uid)
    assert bill.status == BillStatus.ABERTA and bill.paid_amount == 0
    ss.cancel_sale(session, s.id, "erro", uid)
    assert p.quantity_on_hand == D("10")


def test_devolucao_parcial_com_retorno_ao_estoque(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("4"))], [ss.PaymentInput(PM.PIX, D("40"))], seller_id=uid)
    item = s.items[0]
    ss.return_items(session, s.id, [(item.id, D("1"))], "Tamanho errado", uid)
    assert p.quantity_on_hand == D("7") and fin.total_cash_balance(session) == D("30")
    r = fin.result_summary(session, TODAY, TODAY)
    assert (r.gross_revenue, r.returns, r.net_revenue, r.cogs, r.gross_profit) == (D("40"), D("10"), D("30"), D("18"), D("12"))
    with pytest.raises(ValidationError):  # só restam 3
        ss.return_items(session, s.id, [(item.id, D("4"))], "demais", uid)
    with pytest.raises(ValidationError):  # venda com devolução não é cancelada por inteiro
        ss.cancel_sale(session, s.id, "cancelar", uid)
    assert st.verify_consistency(session) == []


def test_devolucao_sem_retorno_ao_estoque_mantem_cmv(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("2"))], [ss.PaymentInput(PM.PIX, D("20"))], seller_id=uid)
    ss.return_items(session, s.id, [(s.items[0].id, D("1"))], "Defeito", uid, restock=False)
    assert p.quantity_on_hand == D("8")
    r = fin.result_summary(session, TODAY, TODAY)
    assert r.cogs == D("12")  # o produto defeituoso não volta ao estoque: o custo permanece


def test_devolucao_de_venda_a_prazo_abate_a_receber(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("3"))], [ss.PaymentInput(PM.A_PRAZO, D("30"), 1, TODAY)],
                         seller_id=uid, customer_name="Ana")
    ss.return_items(session, s.id, [(s.items[0].id, D("1"))], "Não serviu", uid)
    assert fin.open_total(session, "R") == D("20") and fin.total_cash_balance(session) == 0
    ss.return_items(session, s.id, [(s.items[0].id, D("2"))], "Resto", uid)
    assert fin.open_total(session, "R") == 0 and fin.total_cash_balance(session) == 0


def test_comprovante_interno(session, uid):
    p = setup_prod(session, uid)
    s = ss.finalize_sale(session, [ss.CartItem(p.id, D("2"))], [ss.PaymentInput(PM.DINHEIRO, D("50"))],
                         seller_id=uid, customer_name="Carlos")
    txt = ss.receipt_text(session, s.id, "Loja Teste")
    assert "NÃO É DOCUMENTO FISCAL" in txt and "R$ 20,00" in txt and "Troco" in txt and "R$ 30,00" in txt


def test_venda_produto_inativo(session, uid):
    p = setup_prod(session, uid)
    ps.set_active(session, p.id, False)
    with pytest.raises(ValidationError):
        ss.calculate(session, [ss.CartItem(p.id, D("1"))])
