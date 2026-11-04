from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from stockpilot.domain.enums import AccountType, BillStatus, FinGroup, FinKind
from stockpilot.domain.errors import ValidationError
from stockpilot.services import finance_service as fin
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

TODAY = date.today()


def cat(session, name):
    return fin.category_by_name(session, name)


def test_seed_inicial(session):
    assert [a.name for a in fin.list_accounts(session)] == ["Caixa"]
    assert cat(session, "Aluguel").group == FinGroup.DESPESA_FIXA
    assert cat(session, "Energia elétrica").group == FinGroup.DESPESA_VARIAVEL


def test_conta_a_pagar_pagamento_parcial_e_total(session, uid):
    acc = fin.default_account(session)
    bills = fin.create_bills(session, "P", description="Aluguel nov", total=D("1000"), first_due=TODAY,
                             category_id=cat(session, "Aluguel").id)
    b = bills[0]
    fin.pay_bill(session, "P", b.id, D("400"), account_id=acc.id, user_id=uid)
    assert b.status == BillStatus.ABERTA and b.open_amount == D("600")
    with pytest.raises(ValidationError):
        fin.pay_bill(session, "P", b.id, D("600.01"), account_id=acc.id)
    fin.pay_bill(session, "P", b.id, D("600"), account_id=acc.id, user_id=uid)
    assert b.status == BillStatus.PAGA and fin.total_cash_balance(session) == D("-1000")
    with pytest.raises(ValidationError):
        fin.pay_bill(session, "P", b.id, D("1"), account_id=acc.id)


def test_estorno_de_pagamento_reabre_conta(session, uid):
    acc = fin.default_account(session)
    b = fin.create_bills(session, "P", description="Luz", total=D("200"), first_due=TODAY)[0]
    tx = fin.pay_bill(session, "P", b.id, D("200"), account_id=acc.id, user_id=uid)
    rev = fin.reverse_payment(session, tx.id, "pago em duplicidade", uid)
    assert b.status == BillStatus.ABERTA and b.paid_amount == 0 and rev.reverses_id == tx.id
    assert fin.total_cash_balance(session) == 0
    with pytest.raises(ValidationError):
        fin.reverse_payment(session, tx.id, "de novo", uid)
    with pytest.raises(ValidationError):  # estorno também é bloqueado pela rota manual
        fin.reverse_manual_transaction(session, tx.id, "tentativa", uid)


def test_cancelar_conta_somente_sem_pagamentos(session, uid):
    acc = fin.default_account(session)
    b = fin.create_bills(session, "P", description="X", total=D("50"), first_due=TODAY)[0]
    fin.pay_bill(session, "P", b.id, D("10"), account_id=acc.id)
    with pytest.raises(ValidationError):
        fin.cancel_bill(session, "P", b.id, "erro")
    b2 = fin.create_bills(session, "P", description="Y", total=D("50"), first_due=TODAY)[0]
    fin.cancel_bill(session, "P", b2.id, "lançada sem querer")
    assert b2.status == BillStatus.CANCELADA and fin.open_total(session, "P") == D("40")


def test_lancamento_manual_regras_de_categoria(session, uid):
    acc = fin.default_account(session)
    fin.add_manual_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("80"),
                               category_id=cat(session, "Internet e telefone").id, description="Fibra", user_id=uid)
    with pytest.raises(ValidationError):   # despesa não pode ser "entrada"
        fin.add_manual_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.ENTRADA, amount=D("1"),
                                   category_id=cat(session, "Aluguel").id, description="x", user_id=uid)
    with pytest.raises(ValidationError):
        fin.add_manual_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("0"),
                                   category_id=cat(session, "Aluguel").id, description="x", user_id=uid)


def test_ledger_financeiro_e_imutavel(ctx, uid):
    with ctx.db.session_scope() as s:
        acc = fin.default_account(s)
        tx = fin.add_manual_transaction(s, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("5"),
                                        category_id=cat(s, "Água").id, description="Conta", user_id=uid)
        tid = tx.id
    for sql in (f"UPDATE fin_transactions SET amount=1 WHERE id={tid}", f"DELETE FROM fin_transactions WHERE id={tid}"):
        with pytest.raises(DBAPIError):
            with ctx.db.engine.begin() as c:
                c.execute(text(sql))


def test_saldo_inicial_fluxo_de_caixa_e_resultado(session, uid):
    bank = fin.save_account(session, "Banco X", AccountType.BANCO, D("1000"))
    cx = fin.default_account(session)
    d1, d2 = TODAY - timedelta(days=2), TODAY
    fin.post_transaction(session, account_id=bank.id, tx_date=d1, kind=FinKind.ENTRADA, amount=D("500"),
                         category_id=cat(session, "Outras receitas").id)
    fin.add_manual_transaction(session, account_id=cx.id, tx_date=d2, kind=FinKind.SAIDA, amount=D("200"),
                               category_id=cat(session, "Aluguel").id, description="Aluguel", user_id=uid)
    opening, rows = fin.cash_flow(session, d1, d2)
    assert opening == D("1000") and [(r.inflow, r.outflow, r.balance) for r in rows] == [
        (D("500"), D("0"), D("1500")), (D("0"), D("200"), D("1300"))]
    assert fin.account_balance(session, bank.id) == D("1500") and fin.total_cash_balance(session) == D("1300")
    r = fin.result_summary(session, d1, d2)
    assert (r.other_income, r.expenses, r.operating_result) == (D("500"), D("200"), D("300"))


def test_compra_nao_e_despesa_e_estorno_abate_despesa(session, uid):
    acc = fin.default_account(session)
    fin.post_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("999"),
                         category_id=cat(session, "Compra de mercadorias").id)
    tx = fin.add_manual_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("100"),
                                    category_id=cat(session, "Marketing").id, description="Panfleto", user_id=uid)
    r = fin.result_summary(session, TODAY, TODAY)
    assert r.expenses == D("100") and r.merchandise_paid == D("999") and r.operating_result == D("-100")
    fin.reverse_manual_transaction(session, tx.id, "lançado errado", uid)
    assert fin.result_summary(session, TODAY, TODAY).expenses == 0


def test_categorias_e_centros_de_custo(session):
    c = fin.save_category(session, "Embalagens", FinGroup.DESPESA_VARIAVEL)
    assert c.group == FinGroup.DESPESA_VARIAVEL
    with pytest.raises(ValidationError):
        fin.save_category(session, "Embalagens", FinGroup.DESPESA_FIXA)
    fin.save_cost_center(session, "Loja 1")
    assert [x.name for x in fin.list_cost_centers(session)] == ["Loja 1"]


def test_conciliacao_manual(session, uid):
    acc = fin.default_account(session)
    tx = fin.add_manual_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("9"),
                                    category_id=cat(session, "Água").id, description="a", user_id=uid)
    fin.reconcile(session, tx.id, TODAY, uid)
    assert tx.id in fin.reconciled_ids(session)
    with pytest.raises(ValidationError):
        fin.reconcile(session, tx.id, TODAY, uid)
    fin.unreconcile(session, tx.id)
    assert fin.reconciled_ids(session) == set()


def test_vencidas_e_saldo_inicial_protegido(session, uid):
    fin.create_bills(session, "P", description="Antiga", total=D("10"), first_due=TODAY - timedelta(days=3))
    fin.create_bills(session, "P", description="Futura", total=D("10"), first_due=TODAY + timedelta(days=3))
    assert [b.description for b in fin.list_bills(session, "P", only_overdue=True)] == ["Antiga"]
    acc = fin.default_account(session)
    fin.add_manual_transaction(session, account_id=acc.id, tx_date=TODAY, kind=FinKind.SAIDA, amount=D("1"),
                               category_id=cat(session, "Água").id, description="a", user_id=uid)
    with pytest.raises(ValidationError):
        fin.save_account(session, "Caixa", AccountType.CAIXA, D("50"), account_id=acc.id)
