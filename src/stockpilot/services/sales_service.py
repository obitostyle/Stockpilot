"""Frente de caixa: venda, pagamentos, cancelamento e devoluções — tudo em UMA transação.

Qualquer erro (estoque insuficiente, pagamento incompleto...) desfaz a venda inteira: nunca fica metade registrada.
Comprovante gerado é INTERNO e NÃO é documento fiscal (NFC-e/NF-e exigem integração própria, fora da v1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..domain.enums import BillStatus, FinKind, FinOrigin, MovementOrigin, PaymentMethod, SaleStatus
from ..domain.errors import DiscountNotAuthorizedError, NotFoundError, ValidationError
from ..domain.formatting import format_brl, format_datetime_local, format_qty
from ..models import (
    FinTransaction, Product, Receivable, Sale, SaleItem, SalePayment, SaleReturn, StockMovement, utcnow,
)
from . import finance_service as fin
from . import stock_service
from .settings_service import get_setting

CENT = Decimal("0.01")
INTERNAL_NOTICE = "COMPROVANTE INTERNO — NÃO É DOCUMENTO FISCAL"


def q2(v: Decimal) -> Decimal:
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class CartItem:
    product_id: int
    quantity: Decimal
    discount: Decimal = Decimal("0")  # desconto absoluto do item (R$)


@dataclass
class PaymentInput:
    method: PaymentMethod
    amount: Decimal                      # valor entregue pelo cliente (dinheiro pode exceder => troco)
    installments: int = 1
    due_date: date | None = None         # A_PRAZO
    note: str | None = None              # nome do "outro meio"


@dataclass
class CartTotals:
    subtotal: Decimal
    discount: Decimal
    total: Decimal
    discount_percent: Decimal
    lines: list[tuple[Product, Decimal, Decimal, Decimal]] = field(default_factory=list)  # (produto, qtd, desc, total)


def max_discount_percent(session: Session) -> Decimal:
    return Decimal(get_setting(session, "max_discount_percent") or "10")


def calculate(session: Session, items: list[CartItem], sale_discount: Decimal = Decimal("0")) -> CartTotals:
    if not items:
        raise ValidationError("Adicione ao menos um produto à venda.")
    sale_discount = Decimal(sale_discount)
    if sale_discount < 0:
        raise ValidationError("O desconto não pode ser negativo.")
    seen, rows, subtotal = set(), [], Decimal("0")
    for it in items:
        p = session.get(Product, it.product_id)
        if p is None:
            raise NotFoundError("Produto não encontrado.")
        if not p.active:
            raise ValidationError(f"O produto '{p.name}' está inativo.")
        if it.product_id in seen:
            raise ValidationError(f"O produto '{p.name}' aparece duas vezes no carrinho.")
        seen.add(it.product_id)
        qty = Decimal(it.quantity)
        if not qty.is_finite() or qty <= 0 or -qty.as_tuple().exponent > 3 or qty > Decimal("999999"):
            raise ValidationError(f"Quantidade inválida para '{p.name}'.")
        if not p.allows_fraction and qty != qty.to_integral_value():
            raise ValidationError(f"'{p.name}' é vendido por unidade inteira.")
        gross = q2(qty * p.sale_price)
        disc = Decimal(it.discount)
        if disc < 0 or disc > gross or -disc.as_tuple().exponent > 2:
            raise ValidationError(f"Desconto inválido para '{p.name}'.")
        subtotal += gross
        rows.append([p, qty, disc, gross])
    if sale_discount > subtotal - sum(r[2] for r in rows):
        raise ValidationError("O desconto geral excede o total da venda.")
    # rateia o desconto geral entre os itens (o último absorve os centavos)
    base = sum(r[3] - r[2] for r in rows)
    left = sale_discount
    for i, r in enumerate(rows):
        share = left if i == len(rows) - 1 else q2(sale_discount * (r[3] - r[2]) / base) if base else Decimal("0")
        share = min(share, r[3] - r[2])
        r[2] += share
        left -= share
    total_discount = sum(r[2] for r in rows)
    total = subtotal - total_discount
    pct = (total_discount / subtotal * 100) if subtotal else Decimal("0")
    return CartTotals(subtotal, total_discount, total, pct, [(r[0], r[1], r[2], r[3] - r[2]) for r in rows])


def _next_number(session: Session) -> str:
    return f"V{(session.scalar(select(func.max(Sale.id))) or 0) + 1:06d}"


def finalize_sale(session: Session, items: list[CartItem], payments: list[PaymentInput], *, seller_id: int | None,
                  customer_name: str | None = None, sale_discount: Decimal = Decimal("0"),
                  discount_authorized: bool = False, notes: str | None = None,
                  account_id: int | None = None, sale_date: date | None = None) -> Sale:
    totals = calculate(session, items, sale_discount)
    if totals.discount > 0 and totals.discount_percent > max_discount_percent(session) and not discount_authorized:
        raise DiscountNotAuthorizedError(
            f"Desconto de {totals.discount_percent:.1f}% acima do limite de {max_discount_percent(session):.1f}%. "
            "É necessária autorização.")
    if not payments:
        raise ValidationError("Informe a forma de pagamento.")
    given = Decimal("0")
    cash_given = Decimal("0")
    for pay in payments:
        if pay.amount <= 0 or -pay.amount.as_tuple().exponent > 2:
            raise ValidationError("Valor de pagamento inválido.")
        given += pay.amount
        if pay.method == PaymentMethod.DINHEIRO:
            cash_given += pay.amount
        if pay.method == PaymentMethod.A_PRAZO:
            if not (customer_name or "").strip():
                raise ValidationError("Venda a prazo exige o nome do cliente.")
            if pay.due_date is None:
                raise ValidationError("Informe o vencimento da venda a prazo.")
        if not (1 <= pay.installments <= 24):
            raise ValidationError("Parcelas devem estar entre 1 e 24.")
        if pay.method == PaymentMethod.OUTRO and not (pay.note or "").strip():
            raise ValidationError("Informe qual é o outro meio de pagamento.")
    if given < totals.total:
        raise ValidationError(f"Pagamento insuficiente: faltam {format_brl(totals.total - given)}.")
    change = given - totals.total
    if change > cash_given:
        raise ValidationError("O excesso de pagamento só pode ser devolvido como troco em dinheiro.")

    today = sale_date or date.today()
    sale = Sale(number=_next_number(session), status=SaleStatus.CONCLUIDA, sale_date=today, seller_id=seller_id,
                customer_name=(customer_name or "").strip() or None, subtotal=totals.subtotal,
                discount=totals.discount, total=totals.total, paid_total=given, change=change,
                notes=(notes or "").strip() or None)
    session.add(sale)
    session.flush()
    cogs = Decimal("0")
    for n, (p, qty, disc, net) in enumerate(totals.lines, start=1):
        mov = stock_service.register_exit(session, p.id, qty, reason=f"Venda {sale.number}", origin=MovementOrigin.VENDA,
                                          origin_ref=sale.number, user_id=seller_id,
                                          idempotency_key=f"venda:{sale.number}:{n}")
        unit_cost = mov.unit_cost or Decimal("0")
        cogs += qty * unit_cost
        sale.items.append(SaleItem(product_id=p.id, product_name=p.name, quantity=qty, unit_price=p.sale_price,
                                   discount=disc, total=net, unit_cost=unit_cost, stock_movement_id=mov.id))
    sale.cogs = cogs.quantize(Decimal("0.0001"))
    cat = fin.category_by_name(session, "Vendas")
    acc = account_id or fin.default_account(session).id
    cash_left_for_change = change
    for pay in payments:
        applied = pay.amount
        if pay.method == PaymentMethod.DINHEIRO and cash_left_for_change > 0:
            deduct = min(cash_left_for_change, applied)
            applied -= deduct
            cash_left_for_change -= deduct
        if applied <= 0:
            continue
        sale.payments.append(SalePayment(method=pay.method, method_note=pay.note, amount=applied,
                                         installments=pay.installments, due_date=pay.due_date))
        if pay.method == PaymentMethod.A_PRAZO:
            fin.create_bills(session, "R", description=f"Venda {sale.number} — {sale.customer_name}", total=applied,
                             first_due=pay.due_date, installments=pay.installments, category_id=cat.id,
                             customer_name=sale.customer_name, sale_id=sale.id)
        else:
            fin.post_transaction(session, account_id=acc, tx_date=today, kind=FinKind.ENTRADA, amount=applied,
                                 category_id=cat.id, description=f"Venda {sale.number} ({pay.method.label})",
                                 origin=FinOrigin.VENDA, origin_ref=sale.number, user_id=seller_id)
    session.flush()
    return sale


def _load(session: Session, sale_id: int) -> Sale:
    sale = session.scalar(select(Sale).options(joinedload(Sale.items), joinedload(Sale.payments),
                                               joinedload(Sale.seller)).where(Sale.id == sale_id))
    if sale is None:
        raise NotFoundError("Venda não encontrada.")
    return sale


get_sale = _load


def cancel_sale(session: Session, sale_id: int, reason: str, user_id: int | None) -> Sale:
    sale = _load(session, sale_id)
    if sale.status == SaleStatus.CANCELADA:
        raise ValidationError("A venda já está cancelada.")
    if len((reason or "").strip()) < 3:
        raise ValidationError("Informe a justificativa do cancelamento.")
    if session.scalar(select(func.count()).where(SaleReturn.sale_id == sale.id)):
        raise ValidationError("Esta venda tem devoluções registradas e não pode ser cancelada por inteiro.")
    reason = reason.strip()
    fin.cancel_open_bills_of(session, "R", sale_id=sale.id, reason=f"cancelamento da venda {sale.number}")
    for it in sale.items:
        if it.stock_movement_id and not stock_service.is_reversed(session, it.stock_movement_id):
            stock_service.reverse_movement(session, it.stock_movement_id,
                                           f"Cancelamento da venda {sale.number}: {reason}", user_id)
    for tx in session.scalars(select(FinTransaction).where(FinTransaction.origin == FinOrigin.VENDA,
                                                             FinTransaction.origin_ref == sale.number,
                                                             FinTransaction.reverses_id.is_(None))):
        if not fin.is_reversed(session, tx.id):
            fin._reverse(session, tx, f"cancelamento da venda {sale.number}", user_id)
    sale.status = SaleStatus.CANCELADA
    sale.cancelled_at = utcnow()
    sale.cancel_reason = reason
    session.flush()
    return sale


def returned_quantity(session: Session, sale_item_id: int) -> Decimal:
    return session.scalar(select(func.coalesce(func.sum(SaleReturn.quantity), 0)).where(
        SaleReturn.sale_item_id == sale_item_id)) or Decimal("0")


def return_items(session: Session, sale_id: int, lines: list[tuple[int, Decimal]], reason: str, user_id: int | None,
                 *, restock: bool = True, account_id: int | None = None, return_date: date | None = None) -> list[SaleReturn]:
    """Devolução parcial/total de itens. O valor devolvido abate primeiro contas a receber em aberto; o restante sai do caixa."""
    sale = _load(session, sale_id)
    if sale.status != SaleStatus.CONCLUIDA:
        raise ValidationError("Só é possível devolver itens de venda concluída.")
    if len((reason or "").strip()) < 3:
        raise ValidationError("Informe o motivo da devolução.")
    if not lines:
        raise ValidationError("Selecione os itens devolvidos.")
    by_id = {it.id: it for it in sale.items}
    today = return_date or date.today()
    results: list[SaleReturn] = []
    refund_total = Decimal("0")
    for item_id, qty in lines:
        it = by_id.get(item_id)
        if it is None:
            raise ValidationError("Item não pertence a esta venda.")
        qty = Decimal(qty)
        if qty <= 0 or -qty.as_tuple().exponent > 3:
            raise ValidationError(f"Quantidade de devolução inválida para '{it.product_name}'.")
        if qty > it.quantity - returned_quantity(session, it.id):
            raise ValidationError(f"Quantidade devolvida de '{it.product_name}' excede o que foi vendido.")
        amount = q2(it.total * qty / it.quantity)
        cost = (it.unit_cost * qty).quantize(Decimal("0.0001"))
        if restock:
            stock_service.register_entry(session, it.product_id, qty, None, reason=f"Devolução da venda {sale.number}: {reason}",
                                         origin=MovementOrigin.DEVOLUCAO, origin_ref=sale.number, user_id=user_id)
        ret = SaleReturn(sale_id=sale.id, sale_item_id=it.id, quantity=qty, amount=amount, cost_amount=cost,
                         restock=restock, reason=reason.strip(), return_date=today, user_id=user_id)
        session.add(ret)
        results.append(ret)
        refund_total += amount
    # 1) abate contas a receber em aberto (cliente ainda não pagou essa parte)
    remaining = refund_total
    for bill in session.scalars(select(Receivable).where(Receivable.sale_id == sale.id,
                                                          Receivable.status == BillStatus.ABERTA).order_by(Receivable.due_date.desc())):
        cut = min(remaining, bill.open_amount)
        if cut > 0:
            bill.amount -= cut
            remaining -= cut
            if bill.amount == 0:
                bill.amount = cut  # mantém a restrição amount>0; a conta é cancelada
                bill.paid_amount = Decimal("0")
                bill.status = BillStatus.CANCELADA
                bill.notes = f"Abatida por devolução da venda {sale.number}"
            elif bill.paid_amount == bill.amount:
                bill.status = BillStatus.PAGA
        if remaining <= 0:
            break
    # 2) o restante é devolvido ao cliente (saída de caixa)
    if remaining > 0:
        fin.post_transaction(session, account_id=account_id or fin.default_account(session).id, tx_date=today,
                             kind=FinKind.SAIDA, amount=remaining,
                             category_id=fin.category_by_name(session, "Devoluções de vendas").id,
                             description=f"Devolução da venda {sale.number}", origin=FinOrigin.DEVOLUCAO,
                             origin_ref=sale.number, user_id=user_id)
    session.flush()
    return results


def list_sales(session: Session, *, start: date | None = None, end: date | None = None,
               status: SaleStatus | None = None, text: str | None = None, limit: int = 1000) -> list[Sale]:
    stmt = select(Sale).options(joinedload(Sale.seller)).order_by(Sale.id.desc()).limit(limit)
    if start:
        stmt = stmt.where(Sale.sale_date >= start)
    if end:
        stmt = stmt.where(Sale.sale_date <= end)
    if status:
        stmt = stmt.where(Sale.status == status)
    if text and text.strip():
        t = text.strip()
        stmt = stmt.where(or_(Sale.number.icontains(t, autoescape=True), Sale.customer_name.icontains(t, autoescape=True)))
    return list(session.scalars(stmt).unique())


def totals_for_day(session: Session, day: date) -> tuple[int, Decimal]:
    row = session.execute(select(func.count(), func.coalesce(func.sum(Sale.total), 0)).where(
        Sale.status == SaleStatus.CONCLUIDA, Sale.sale_date == day)).one()
    return row[0], Decimal(row[1])


def receipt_text(session: Session, sale_id: int, company_name: str = "") -> str:
    sale = _load(session, sale_id)
    w = 44
    lines = [(company_name or "StockPilot").center(w), INTERNAL_NOTICE.center(w), "-" * w,
             f"Venda {sale.number}   {format_datetime_local(sale.created_at)}",
             f"Vendedor: {sale.seller.full_name if sale.seller else '-'}"]
    if sale.customer_name:
        lines.append(f"Cliente: {sale.customer_name}")
    if sale.status == SaleStatus.CANCELADA:
        lines.append("*** VENDA CANCELADA ***".center(w))
    lines.append("-" * w)
    for it in sale.items:
        lines.append(it.product_name[:w])
        lines.append(f"  {format_qty(it.quantity)} x {format_brl(it.unit_price)}".ljust(w - 14) + format_brl(it.total).rjust(14))
    lines.append("-" * w)
    lines.append("Subtotal".ljust(w - 14) + format_brl(sale.subtotal).rjust(14))
    if sale.discount:
        lines.append("Desconto".ljust(w - 14) + ("-" + format_brl(sale.discount)).rjust(14))
    lines.append("TOTAL".ljust(w - 14) + format_brl(sale.total).rjust(14))
    for p in sale.payments:
        label = p.method_note if p.method == PaymentMethod.OUTRO and p.method_note else p.method.label
        lines.append(label.ljust(w - 14) + format_brl(p.amount).rjust(14))
    if sale.change:
        lines.append("Troco".ljust(w - 14) + format_brl(sale.change).rjust(14))
    lines += ["-" * w, "Obrigado pela preferência!".center(w)]
    return "\n".join(lines)
