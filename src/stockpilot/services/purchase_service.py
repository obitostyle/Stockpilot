"""Compras. Confirmar uma compra é IDEMPOTENTE: só RASCUNHO pode ser confirmado e cada item usa
chave de idempotência do estoque (`compra:<id>:<item>`), logo cliques repetidos nunca duplicam a entrada."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from ..domain.enums import FinKind, FinOrigin, MovementOrigin, PaymentMethod, PurchaseStatus
from ..domain.errors import NotFoundError, ValidationError
from ..models import Product, Purchase, PurchaseItem, Supplier, utcnow
from . import finance_service as fin
from . import stock_service


@dataclass
class PurchaseLine:
    product_id: int
    quantity: Decimal
    unit_cost: Decimal


def _next_number(session: Session) -> str:
    return f"C{(session.scalar(select(func.max(Purchase.id))) or 0) + 1:06d}"


def save_purchase(session: Session, *, supplier_id: int, lines: list[PurchaseLine], issue_date: date | None = None,
                  discount: Decimal = Decimal("0"), extra_expenses: Decimal = Decimal("0"),
                  payment_method: PaymentMethod = PaymentMethod.DINHEIRO, installments: int = 1,
                  first_due_date: date | None = None, notes: str | None = None, user_id: int | None = None,
                  purchase_id: int | None = None) -> Purchase:
    """Cria (ou substitui o conteúdo de) um RASCUNHO de compra. Não mexe no estoque."""
    if session.get(Supplier, supplier_id) is None:
        raise ValidationError("Selecione o fornecedor.")
    if not lines:
        raise ValidationError("Adicione ao menos um produto à compra.")
    discount, extra_expenses = Decimal(discount), Decimal(extra_expenses)
    if discount < 0 or extra_expenses < 0:
        raise ValidationError("Desconto e despesas adicionais não podem ser negativos.")
    seen = set()
    subtotal = Decimal("0")
    for ln in lines:
        p = session.get(Product, ln.product_id)
        if p is None:
            raise NotFoundError("Produto não encontrado na compra.")
        if ln.product_id in seen:
            raise ValidationError(f"O produto '{p.name}' aparece mais de uma vez. Some as quantidades.")
        seen.add(ln.product_id)
        if ln.quantity <= 0 or -ln.quantity.as_tuple().exponent > 3:
            raise ValidationError(f"Quantidade inválida para '{p.name}'.")
        if not p.allows_fraction and ln.quantity != ln.quantity.to_integral_value():
            raise ValidationError(f"'{p.name}' é controlado por unidade inteira.")
        if ln.unit_cost < 0 or -ln.unit_cost.as_tuple().exponent > 4:
            raise ValidationError(f"Custo unitário inválido para '{p.name}'.")
        subtotal += ln.quantity * ln.unit_cost
    if discount > subtotal:
        raise ValidationError("O desconto não pode ser maior que o total dos itens.")
    if not (1 <= installments <= 60):
        raise ValidationError("Parcelas devem estar entre 1 e 60.")
    prazo = payment_method == PaymentMethod.A_PRAZO or installments > 1
    if prazo and first_due_date is None:
        raise ValidationError("Informe o vencimento da primeira parcela.")
    if purchase_id:
        purchase = session.get(Purchase, purchase_id)
        if purchase is None:
            raise NotFoundError("Compra não encontrada.")
        if purchase.status != PurchaseStatus.RASCUNHO:
            raise ValidationError("Só é possível editar uma compra em rascunho.")
        purchase.items.clear()
        session.flush()
    else:
        purchase = Purchase(number=_next_number(session), supplier_id=supplier_id)
        session.add(purchase)
    purchase.supplier_id = supplier_id
    purchase.issue_date = issue_date or date.today()
    purchase.discount, purchase.extra_expenses = discount, extra_expenses
    purchase.subtotal = subtotal
    purchase.total = subtotal - discount + extra_expenses
    purchase.payment_method, purchase.installments = payment_method, installments
    purchase.first_due_date = first_due_date if prazo else None
    purchase.notes = (notes or "").strip() or None
    purchase.user_id = user_id
    for ln in lines:
        purchase.items.append(PurchaseItem(product_id=ln.product_id, quantity=ln.quantity, unit_cost=ln.unit_cost))
    session.flush()
    return purchase


def _effective_costs(purchase: Purchase) -> list[Decimal]:
    """Rateia desconto e despesas adicionais proporcionalmente ao valor de cada item (custo de aquisição)."""
    sub = purchase.subtotal
    out = []
    for it in purchase.items:
        line = it.quantity * it.unit_cost
        share = (line / sub) if sub > 0 else Decimal("0")
        adj = line - purchase.discount * share + purchase.extra_expenses * share
        out.append((adj / it.quantity).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
    return out


def confirm_purchase(session: Session, purchase_id: int, user_id: int | None, account_id: int | None = None) -> Purchase:
    purchase = session.scalar(select(Purchase).options(joinedload(Purchase.items)).where(Purchase.id == purchase_id))
    if purchase is None:
        raise NotFoundError("Compra não encontrada.")
    if purchase.status != PurchaseStatus.RASCUNHO:
        raise ValidationError(f"A compra {purchase.number} já foi {purchase.status.label.lower()}; "
                              "o estoque não será atualizado novamente.")
    for it, eff in zip(purchase.items, _effective_costs(purchase)):
        it.effective_unit_cost = eff
        stock_service.register_entry(session, it.product_id, it.quantity, eff, reason=f"Compra {purchase.number}",
                                     origin=MovementOrigin.COMPRA, origin_ref=purchase.number, user_id=user_id,
                                     idempotency_key=f"compra:{purchase.id}:{it.id}")
    cat = fin.category_by_name(session, "Compra de mercadorias")
    if purchase.total > 0:
        if purchase.first_due_date is not None:  # a prazo / parcelada
            fin.create_bills(session, "P", description=f"Compra {purchase.number} — {purchase.supplier.name}",
                             total=purchase.total, first_due=purchase.first_due_date,
                             installments=purchase.installments, category_id=cat.id,
                             supplier_id=purchase.supplier_id, purchase_id=purchase.id)
        else:  # à vista: saída de caixa imediata
            acc = account_id or fin.default_account(session).id
            fin.post_transaction(session, account_id=acc, tx_date=purchase.issue_date, kind=FinKind.SAIDA,
                                 amount=purchase.total, category_id=cat.id,
                                 description=f"Compra {purchase.number} — {purchase.supplier.name}",
                                 origin=FinOrigin.COMPRA, origin_ref=purchase.number, user_id=user_id)
    purchase.status = PurchaseStatus.CONFIRMADA
    purchase.confirmed_at = utcnow()
    session.flush()
    return purchase


def cancel_purchase(session: Session, purchase_id: int, reason: str, user_id: int | None) -> Purchase:
    purchase = session.scalar(select(Purchase).options(joinedload(Purchase.items)).where(Purchase.id == purchase_id))
    if purchase is None:
        raise NotFoundError("Compra não encontrada.")
    if purchase.status == PurchaseStatus.CANCELADA:
        raise ValidationError("A compra já está cancelada.")
    if len((reason or "").strip()) < 3:
        raise ValidationError("Informe o motivo do cancelamento.")
    if purchase.status == PurchaseStatus.CONFIRMADA:
        # tudo ou nada: se faltar saldo (mercadoria já vendida), a transação inteira é desfeita
        for it in purchase.items:
            mov = stock_service.history_for_key(session, f"compra:{purchase.id}:{it.id}")
            if mov is not None:
                stock_service.reverse_movement(session, mov.id, f"Cancelamento da compra {purchase.number}: {reason}", user_id)
        fin.cancel_open_bills_of(session, "P", purchase_id=purchase.id, reason=reason.strip())
        from ..models import FinTransaction
        tx = session.scalar(select(FinTransaction).where(FinTransaction.origin == FinOrigin.COMPRA,
                                                          FinTransaction.origin_ref == purchase.number,
                                                          FinTransaction.reverses_id.is_(None)))
        if tx and not fin.is_reversed(session, tx.id):
            fin._reverse(session, tx, f"cancelamento da compra {purchase.number}", user_id)
    purchase.status = PurchaseStatus.CANCELADA
    purchase.cancelled_at = utcnow()
    purchase.cancel_reason = reason.strip()
    session.flush()
    return purchase


def get_purchase(session: Session, purchase_id: int) -> Purchase:
    p = session.scalar(select(Purchase).options(joinedload(Purchase.items).joinedload(PurchaseItem.product),
                                                 joinedload(Purchase.supplier)).where(Purchase.id == purchase_id))
    if p is None:
        raise NotFoundError("Compra não encontrada.")
    return p


def list_purchases(session: Session, *, start: date | None = None, end: date | None = None,
                   supplier_id: int | None = None, status: PurchaseStatus | None = None) -> list[Purchase]:
    stmt = select(Purchase).options(joinedload(Purchase.supplier)).order_by(Purchase.id.desc())
    if start:
        stmt = stmt.where(Purchase.issue_date >= start)
    if end:
        stmt = stmt.where(Purchase.issue_date <= end)
    if supplier_id:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)
    if status:
        stmt = stmt.where(Purchase.status == status)
    return list(session.scalars(stmt))
