"""Financeiro: livro-caixa imutável, contas a pagar/receber, fluxo de caixa e resultado.

PREMISSAS DA APURAÇÃO (exibidas nos relatórios):
* Faturamento = vendas concluídas (regime de competência, pela data da venda), sem as canceladas.
* Recebimentos = dinheiro efetivamente lançado no caixa/contas (venda à vista, cartão no ato, recebimento de fiado).
  Cartão de crédito é lançado no ato da venda (prazo de repasse da operadora NÃO é modelado).
* CMV = custo médio ponderado vigente no momento de cada venda; devolução com retorno ao estoque devolve o custo.
* Compra de mercadorias NÃO é despesa (vira estoque e chega ao resultado pelo CMV).
* Despesas = saídas pagas (regime de caixa) nas categorias de despesa fixa/variável.
* Resultado operacional estimado = lucro bruto + outras receitas − despesas. Não inclui impostos sobre o lucro,
  depreciação, juros de cartão nem pró-labore, salvo se lançados como despesa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.enums import AccountType, BillStatus, FinGroup, FinKind, FinOrigin, SaleStatus
from ..domain.errors import NotFoundError, ValidationError
from ..models import (
    CostCenter, FinAccount, FinCategory, FinTransaction, Payable, Receivable, Reconciliation, Sale,
    SaleReturn,
)

CENT = Decimal("0.01")
INCOME_GROUPS = (FinGroup.RECEITA_VENDAS, FinGroup.OUTRA_RECEITA)

SEED_CATEGORIES = [
    ("Vendas", FinGroup.RECEITA_VENDAS), ("Outras receitas", FinGroup.OUTRA_RECEITA),
    ("Aluguel", FinGroup.DESPESA_FIXA), ("Salários e encargos", FinGroup.DESPESA_FIXA),
    ("Internet e telefone", FinGroup.DESPESA_FIXA), ("Contabilidade", FinGroup.DESPESA_FIXA),
    ("Energia elétrica", FinGroup.DESPESA_VARIAVEL), ("Água", FinGroup.DESPESA_VARIAVEL),
    ("Impostos e taxas", FinGroup.DESPESA_VARIAVEL), ("Marketing", FinGroup.DESPESA_VARIAVEL),
    ("Manutenção", FinGroup.DESPESA_VARIAVEL), ("Outras despesas", FinGroup.DESPESA_VARIAVEL),
    ("Compra de mercadorias", FinGroup.COMPRA_MERCADORIA),
    ("Devoluções de vendas", FinGroup.DEVOLUCAO_VENDA),
]


def q2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def seed_finance(session: Session) -> None:
    if not session.scalar(select(FinAccount.id).limit(1)):
        session.add(FinAccount(name="Caixa", type=AccountType.CAIXA))
    have = set(session.scalars(select(FinCategory.name)))
    for name, group in SEED_CATEGORIES:
        if name not in have:
            session.add(FinCategory(name=name, group=group))
    session.flush()


def default_account(session: Session) -> FinAccount:
    acc = session.scalar(select(FinAccount).where(FinAccount.active.is_(True)).order_by(FinAccount.id).limit(1))
    if acc is None:
        raise ValidationError("Cadastre ao menos uma conta (Caixa ou banco) no Financeiro.")
    return acc


def category_by_name(session: Session, name: str) -> FinCategory:
    cat = session.scalar(select(FinCategory).where(FinCategory.name == name))
    if cat is None:
        raise NotFoundError(f"Categoria financeira '{name}' não encontrada.")
    return cat


def list_accounts(session: Session, only_active: bool = True) -> list[FinAccount]:
    stmt = select(FinAccount).order_by(FinAccount.name)
    if only_active:
        stmt = stmt.where(FinAccount.active.is_(True))
    return list(session.scalars(stmt))


def list_categories(session: Session, groups: tuple[FinGroup, ...] | None = None) -> list[FinCategory]:
    stmt = select(FinCategory).where(FinCategory.active.is_(True)).order_by(FinCategory.group, FinCategory.name)
    if groups:
        stmt = stmt.where(FinCategory.group.in_(groups))
    return list(session.scalars(stmt))


def list_cost_centers(session: Session) -> list[CostCenter]:
    return list(session.scalars(select(CostCenter).order_by(CostCenter.name)))


def save_account(session: Session, name: str, type_: AccountType, opening_balance: Decimal,
                 account_id: int | None = None) -> FinAccount:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Informe o nome da conta.")
    dup = session.scalar(select(FinAccount.id).where(FinAccount.name == name, FinAccount.id != (account_id or 0)))
    if dup:
        raise ValidationError("Já existe uma conta com esse nome.")
    if account_id:
        acc = session.get(FinAccount, account_id)
        if acc is None:
            raise NotFoundError("Conta não encontrada.")
        has_tx = session.scalar(select(func.count()).where(FinTransaction.account_id == account_id))
        if has_tx and acc.opening_balance != opening_balance:
            raise ValidationError("O saldo inicial não pode ser alterado depois de haver lançamentos. "
                                  "Registre um lançamento de ajuste.")
        acc.name, acc.type, acc.opening_balance = name, type_, opening_balance
    else:
        acc = FinAccount(name=name, type=type_, opening_balance=opening_balance)
        session.add(acc)
    session.flush()
    return acc


def save_category(session: Session, name: str, group: FinGroup) -> FinCategory:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Informe o nome da categoria.")
    if session.scalar(select(FinCategory.id).where(FinCategory.name == name)):
        raise ValidationError("Já existe uma categoria com esse nome.")
    cat = FinCategory(name=name, group=group)
    session.add(cat)
    session.flush()
    return cat


def save_cost_center(session: Session, name: str) -> CostCenter:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Informe o nome do centro de custo.")
    if session.scalar(select(CostCenter.id).where(CostCenter.name == name)):
        raise ValidationError("Já existe um centro de custo com esse nome.")
    cc = CostCenter(name=name)
    session.add(cc)
    session.flush()
    return cc


# ------------------------------------------------------------------ lançamentos
def post_transaction(
    session: Session, *, account_id: int, tx_date: date, kind: FinKind, amount: Decimal, category_id: int,
    description: str | None = None, origin: FinOrigin = FinOrigin.MANUAL, origin_ref: str | None = None,
    cost_center_id: int | None = None, user_id: int | None = None, reverses_id: int | None = None,
) -> FinTransaction:
    amount = Decimal(amount)
    if not amount.is_finite() or amount <= 0:
        raise ValidationError("O valor do lançamento deve ser maior que zero.")
    if -amount.as_tuple().exponent > 4 or amount > Decimal("999999999"):
        raise ValidationError("Valor inválido ou acima do limite.")
    if session.get(FinAccount, account_id) is None:
        raise NotFoundError("Conta não encontrada.")
    tx = FinTransaction(account_id=account_id, date=tx_date, kind=kind, amount=amount, category_id=category_id,
                        description=(description or "").strip() or None, origin=origin, origin_ref=origin_ref,
                        cost_center_id=cost_center_id, user_id=user_id, reverses_id=reverses_id)
    session.add(tx)
    session.flush()
    return tx


def add_manual_transaction(session: Session, *, account_id: int, tx_date: date, kind: FinKind, amount: Decimal,
                           category_id: int, description: str, user_id: int | None,
                           cost_center_id: int | None = None) -> FinTransaction:
    cat = session.get(FinCategory, category_id)
    if cat is None:
        raise NotFoundError("Categoria não encontrada.")
    if not (description or "").strip():
        raise ValidationError("Informe uma descrição para o lançamento.")
    if cat.group in INCOME_GROUPS and kind != FinKind.ENTRADA:
        raise ValidationError("Categoria de receita só aceita lançamento de entrada.")
    if cat.group not in INCOME_GROUPS and kind != FinKind.SAIDA:
        raise ValidationError("Categoria de despesa só aceita lançamento de saída.")
    return post_transaction(session, account_id=account_id, tx_date=tx_date, kind=kind, amount=amount,
                            category_id=category_id, description=description, cost_center_id=cost_center_id,
                            user_id=user_id)


def is_reversed(session: Session, tx_id: int) -> bool:
    return bool(session.scalar(select(func.count()).where(FinTransaction.reverses_id == tx_id)))


def _reverse(session: Session, tx: FinTransaction, reason: str, user_id: int | None) -> FinTransaction:
    if is_reversed(session, tx.id):
        raise ValidationError("Este lançamento já foi estornado.")
    if tx.reverses_id:
        raise ValidationError("Um estorno não pode ser estornado.")
    return post_transaction(
        session, account_id=tx.account_id, tx_date=date.today(),
        kind=FinKind.SAIDA if tx.kind == FinKind.ENTRADA else FinKind.ENTRADA, amount=tx.amount,
        category_id=tx.category_id, description=f"Estorno do lançamento #{tx.id}: {reason}",
        origin=FinOrigin.ESTORNO, origin_ref=tx.origin_ref, cost_center_id=tx.cost_center_id,
        user_id=user_id, reverses_id=tx.id)


def reverse_manual_transaction(session: Session, tx_id: int, reason: str, user_id: int | None) -> FinTransaction:
    tx = session.get(FinTransaction, tx_id)
    if tx is None:
        raise NotFoundError("Lançamento não encontrado.")
    if len((reason or "").strip()) < 3:
        raise ValidationError("Informe o motivo do estorno.")
    if tx.origin != FinOrigin.MANUAL:
        raise ValidationError("Este lançamento veio de outra operação (venda, compra, pagamento...). "
                              "Cancele ou estorne a operação de origem.")
    return _reverse(session, tx, reason.strip(), user_id)


# ------------------------------------------------------------------ contas a pagar / receber
def _split(total: Decimal, n: int) -> list[Decimal]:
    base = (total / n).quantize(CENT, rounding=ROUND_HALF_UP)
    parts = [base] * n
    parts[-1] = total - base * (n - 1)  # a última parcela absorve a diferença de centavos
    return parts


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last))


def create_bills(session: Session, kind: str, *, description: str, total: Decimal, first_due: date,
                 installments: int = 1, category_id: int | None = None, supplier_id: int | None = None,
                 purchase_id: int | None = None, customer_name: str | None = None, sale_id: int | None = None,
                 notes: str | None = None) -> list:
    if kind not in ("P", "R"):
        raise ValueError("kind deve ser 'P' ou 'R'")
    total = Decimal(total)
    if total <= 0:
        raise ValidationError("O valor deve ser maior que zero.")
    if not (1 <= installments <= 60):
        raise ValidationError("O número de parcelas deve estar entre 1 e 60.")
    if not (description or "").strip():
        raise ValidationError("Informe a descrição.")
    bills = []
    for i, part in enumerate(_split(total, installments), start=1):
        common = dict(description=description.strip(), category_id=category_id, due_date=add_months(first_due, i - 1),
                      amount=part, installment_no=i, installment_total=installments, notes=notes)
        bills.append(Payable(supplier_id=supplier_id, purchase_id=purchase_id, **common) if kind == "P"
                     else Receivable(customer_name=customer_name, sale_id=sale_id, **common))
    session.add_all(bills)
    session.flush()
    return bills


def _bill(session: Session, kind: str, bill_id: int):
    bill = session.get(Payable if kind == "P" else Receivable, bill_id)
    if bill is None:
        raise NotFoundError("Conta não encontrada.")
    return bill


def pay_bill(session: Session, kind: str, bill_id: int, amount: Decimal, *, account_id: int,
             pay_date: date | None = None, user_id: int | None = None) -> FinTransaction:
    bill = _bill(session, kind, bill_id)
    if bill.status != BillStatus.ABERTA:
        raise ValidationError("Esta conta não está em aberto.")
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("O valor deve ser maior que zero.")
    if amount > bill.open_amount:
        raise ValidationError(f"O valor excede o saldo em aberto da conta ({bill.open_amount:.2f}).")
    if kind == "P":
        cat_id = bill.category_id or category_by_name(session, "Outras despesas").id
        fk, origin, ref = FinKind.SAIDA, FinOrigin.PAGAMENTO, f"CP:{bill.id}"
    else:
        cat_id = bill.category_id or category_by_name(session, "Outras receitas" if bill.sale_id is None else "Vendas").id
        fk, origin, ref = FinKind.ENTRADA, FinOrigin.RECEBIMENTO, f"CR:{bill.id}"
    tx = post_transaction(session, account_id=account_id, tx_date=pay_date or date.today(), kind=fk, amount=amount,
                          category_id=cat_id, description=bill.description, origin=origin, origin_ref=ref,
                          user_id=user_id)
    bill.paid_amount += amount
    if bill.paid_amount == bill.amount:
        bill.status = BillStatus.PAGA
    return tx


def reverse_payment(session: Session, tx_id: int, reason: str, user_id: int | None) -> FinTransaction:
    tx = session.get(FinTransaction, tx_id)
    if tx is None or tx.origin not in (FinOrigin.PAGAMENTO, FinOrigin.RECEBIMENTO):
        raise ValidationError("Selecione um lançamento de pagamento ou recebimento.")
    if len((reason or "").strip()) < 3:
        raise ValidationError("Informe o motivo do estorno.")
    kind, bid = tx.origin_ref.split(":")
    bill = _bill(session, "P" if kind == "CP" else "R", int(bid))
    rev = _reverse(session, tx, reason.strip(), user_id)
    bill.paid_amount -= tx.amount
    if bill.status == BillStatus.PAGA:
        bill.status = BillStatus.ABERTA
    return rev


def bill_payments(session: Session, kind: str, bill_id: int) -> list[FinTransaction]:
    ref = f"{'CP' if kind == 'P' else 'CR'}:{bill_id}"
    return list(session.scalars(select(FinTransaction).where(
        FinTransaction.origin_ref == ref, FinTransaction.origin.in_((FinOrigin.PAGAMENTO, FinOrigin.RECEBIMENTO)))
        .order_by(FinTransaction.id)))


def cancel_bill(session: Session, kind: str, bill_id: int, reason: str) -> None:
    bill = _bill(session, kind, bill_id)
    if bill.status == BillStatus.CANCELADA:
        raise ValidationError("A conta já está cancelada.")
    if bill.paid_amount > 0:
        raise ValidationError("A conta tem pagamentos/recebimentos. Estorne-os antes de cancelar.")
    if len((reason or "").strip()) < 3:
        raise ValidationError("Informe o motivo do cancelamento.")
    bill.status = BillStatus.CANCELADA
    bill.notes = f"Cancelada: {reason.strip()}"


def cancel_open_bills_of(session: Session, kind: str, *, purchase_id: int | None = None,
                         sale_id: int | None = None, reason: str) -> None:
    model = Payable if kind == "P" else Receivable
    col = model.purchase_id if kind == "P" else model.sale_id
    key = purchase_id if kind == "P" else sale_id
    for bill in session.scalars(select(model).where(col == key, model.status != BillStatus.CANCELADA)):
        if bill.paid_amount > 0:
            raise ValidationError("Há pagamentos/recebimentos vinculados. Estorne-os em Financeiro antes de cancelar.")
        bill.status = BillStatus.CANCELADA
        bill.notes = f"Cancelada: {reason}"


def list_bills(session: Session, kind: str, *, status: BillStatus | None = None, start: date | None = None,
               end: date | None = None, only_overdue: bool = False, today: date | None = None) -> list:
    model = Payable if kind == "P" else Receivable
    stmt = select(model).order_by(model.due_date, model.id)
    if status:
        stmt = stmt.where(model.status == status)
    if start:
        stmt = stmt.where(model.due_date >= start)
    if end:
        stmt = stmt.where(model.due_date <= end)
    if only_overdue:
        stmt = stmt.where(model.status == BillStatus.ABERTA, model.due_date < (today or date.today()))
    return list(session.scalars(stmt))


def open_total(session: Session, kind: str, *, due_until: date | None = None) -> Decimal:
    model = Payable if kind == "P" else Receivable
    stmt = select(model).where(model.status == BillStatus.ABERTA)
    if due_until:
        stmt = stmt.where(model.due_date <= due_until)
    return sum((b.open_amount for b in session.scalars(stmt)), Decimal("0"))


# ------------------------------------------------------------------ conciliação manual
def reconcile(session: Session, tx_id: int, statement_date: date | None, user_id: int | None) -> None:
    if session.get(FinTransaction, tx_id) is None:
        raise NotFoundError("Lançamento não encontrado.")
    if session.scalar(select(Reconciliation.id).where(Reconciliation.transaction_id == tx_id)):
        raise ValidationError("Lançamento já conciliado.")
    session.add(Reconciliation(transaction_id=tx_id, statement_date=statement_date, user_id=user_id))


def unreconcile(session: Session, tx_id: int) -> None:
    rec = session.scalar(select(Reconciliation).where(Reconciliation.transaction_id == tx_id))
    if rec is None:
        raise ValidationError("Lançamento não está conciliado.")
    session.delete(rec)


def reconciled_ids(session: Session) -> set[int]:
    return set(session.scalars(select(Reconciliation.transaction_id)))


# ------------------------------------------------------------------ consultas
def list_transactions(session: Session, *, start: date | None = None, end: date | None = None,
                      account_id: int | None = None, limit: int = 2000) -> list[FinTransaction]:
    stmt = select(FinTransaction).order_by(FinTransaction.date.desc(), FinTransaction.id.desc()).limit(limit)
    if start:
        stmt = stmt.where(FinTransaction.date >= start)
    if end:
        stmt = stmt.where(FinTransaction.date <= end)
    if account_id:
        stmt = stmt.where(FinTransaction.account_id == account_id)
    return list(session.scalars(stmt))


def account_balance(session: Session, account_id: int, until: date | None = None) -> Decimal:
    acc = session.get(FinAccount, account_id)
    if acc is None:
        raise NotFoundError("Conta não encontrada.")
    stmt = select(FinTransaction.kind, func.sum(FinTransaction.amount)).where(
        FinTransaction.account_id == account_id).group_by(FinTransaction.kind)
    if until:
        stmt = stmt.where(FinTransaction.date <= until)
    bal = acc.opening_balance
    for kind, total in session.execute(stmt):
        bal += total if kind == FinKind.ENTRADA else -total
    return bal


def total_cash_balance(session: Session, until: date | None = None) -> Decimal:
    return sum((account_balance(session, a.id, until) for a in list_accounts(session, only_active=False)), Decimal("0"))


@dataclass
class CashFlowRow:
    day: date
    inflow: Decimal
    outflow: Decimal
    balance: Decimal


def cash_flow(session: Session, start: date, end: date, account_id: int | None = None) -> tuple[Decimal, list[CashFlowRow]]:
    """Retorna (saldo de abertura, linhas diárias)."""
    accounts = [account_id] if account_id else [a.id for a in list_accounts(session, only_active=False)]
    opening = sum((account_balance(session, a, start - timedelta(days=1)) for a in accounts), Decimal("0"))
    stmt = (select(FinTransaction.date, FinTransaction.kind, func.sum(FinTransaction.amount))
            .where(FinTransaction.date >= start, FinTransaction.date <= end, FinTransaction.account_id.in_(accounts))
            .group_by(FinTransaction.date, FinTransaction.kind).order_by(FinTransaction.date))
    days: dict[date, list[Decimal]] = {}
    for d, kind, total in session.execute(stmt):
        days.setdefault(d, [Decimal("0"), Decimal("0")])[0 if kind == FinKind.ENTRADA else 1] += total
    rows, bal = [], opening
    for d in sorted(days):
        inflow, outflow = days[d]
        bal += inflow - outflow
        rows.append(CashFlowRow(d, inflow, outflow, bal))
    return opening, rows


def group_net(session: Session, start: date, end: date) -> dict[FinGroup, Decimal]:
    """Valor líquido por grupo (estornos já abatidos): receitas = entradas − saídas; demais = saídas − entradas."""
    stmt = (select(FinCategory.group, FinTransaction.kind, func.sum(FinTransaction.amount))
            .join(FinCategory, FinCategory.id == FinTransaction.category_id)
            .where(FinTransaction.date >= start, FinTransaction.date <= end)
            .group_by(FinCategory.group, FinTransaction.kind))
    out = {g: Decimal("0") for g in FinGroup}
    for group, kind, total in session.execute(stmt):
        pos = FinKind.ENTRADA if group in INCOME_GROUPS else FinKind.SAIDA
        out[group] += total if kind == pos else -total
    return out


def category_totals(session: Session, start: date, end: date) -> list[tuple[str, FinGroup, Decimal]]:
    stmt = (select(FinCategory.name, FinCategory.group, FinTransaction.kind, func.sum(FinTransaction.amount))
            .join(FinCategory, FinCategory.id == FinTransaction.category_id)
            .where(FinTransaction.date >= start, FinTransaction.date <= end)
            .group_by(FinCategory.name, FinCategory.group, FinTransaction.kind))
    acc: dict[tuple[str, FinGroup], Decimal] = {}
    for name, group, kind, total in session.execute(stmt):
        pos = FinKind.ENTRADA if group in INCOME_GROUPS else FinKind.SAIDA
        acc[(name, group)] = acc.get((name, group), Decimal("0")) + (total if kind == pos else -total)
    return sorted(((n, g, v) for (n, g), v in acc.items()), key=lambda r: (r[1].value, r[0]))


@dataclass
class ResultSummary:
    start: date
    end: date
    gross_revenue: Decimal = Decimal("0")       # faturamento (competência)
    returns: Decimal = Decimal("0")
    net_revenue: Decimal = Decimal("0")
    cogs: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    other_income: Decimal = Decimal("0")
    expenses: Decimal = Decimal("0")
    operating_result: Decimal = Decimal("0")
    receipts: Decimal = Decimal("0")            # recebimentos de vendas (caixa)
    merchandise_paid: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")
    receivable_open: Decimal = Decimal("0")
    payable_open: Decimal = Decimal("0")
    assumptions: list[str] = field(default_factory=lambda: [
        "Faturamento: vendas concluídas na data da venda (competência), sem as canceladas.",
        "Recebimentos: valores efetivamente lançados em caixa/contas; cartão é lançado no ato da venda.",
        "CMV: custo médio ponderado no momento de cada venda; devolução com retorno ao estoque devolve o custo.",
        "Compra de mercadorias não é despesa: entra no estoque e chega ao resultado pelo CMV.",
        "Despesas: saídas pagas (regime de caixa) em categorias de despesa fixa/variável.",
        "Resultado operacional ESTIMADO: não inclui impostos sobre lucro, depreciação nem juros de operadoras.",
    ])


def result_summary(session: Session, start: date, end: date) -> ResultSummary:
    r = ResultSummary(start, end)
    sales = session.execute(select(func.coalesce(func.sum(Sale.total), 0), func.coalesce(func.sum(Sale.cogs), 0))
                            .where(Sale.status == SaleStatus.CONCLUIDA, Sale.sale_date >= start,
                                   Sale.sale_date <= end)).one()
    r.gross_revenue, cogs = Decimal(sales[0]), Decimal(sales[1])
    ret_amount = Decimal("0")
    ret_cost = Decimal("0")
    for ret in session.scalars(select(SaleReturn).where(SaleReturn.return_date >= start, SaleReturn.return_date <= end)):
        ret_amount += ret.amount
        if ret.restock:
            ret_cost += ret.cost_amount
    r.returns = ret_amount
    r.net_revenue = r.gross_revenue - ret_amount
    r.cogs = cogs - ret_cost
    r.gross_profit = r.net_revenue - r.cogs
    g = group_net(session, start, end)
    r.other_income = g[FinGroup.OUTRA_RECEITA]
    r.expenses = g[FinGroup.DESPESA_FIXA] + g[FinGroup.DESPESA_VARIAVEL]
    r.operating_result = r.gross_profit + r.other_income - r.expenses
    r.receipts = g[FinGroup.RECEITA_VENDAS] - g[FinGroup.DEVOLUCAO_VENDA]
    r.merchandise_paid = g[FinGroup.COMPRA_MERCADORIA]
    r.cash_balance = total_cash_balance(session, end)
    r.receivable_open = open_total(session, "R")
    r.payable_open = open_total(session, "P")
    return r
