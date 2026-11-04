"""Compras, vendas, devoluções e financeiro (Fases 3 e 4)."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DDL, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..domain.enums import (
    AccountType, BillStatus, FinGroup, FinKind, FinOrigin, PaymentMethod, PurchaseStatus, SaleStatus,
)
from ..infra.types import Money, Quantity
from .base import Base, utcnow
from .entities import Product, Supplier, User, _enum

Z = Decimal("0")


# ------------------------------------------------------------------ financeiro (base)
class FinAccount(Base):
    __tablename__ = "fin_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    type: Mapped[AccountType] = mapped_column(_enum(AccountType), default=AccountType.CAIXA)
    opening_balance: Mapped[Decimal] = mapped_column(Money(), default=Z)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FinCategory(Base):
    __tablename__ = "fin_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    group: Mapped[FinGroup] = mapped_column(_enum(FinGroup))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class CostCenter(Base):
    __tablename__ = "cost_centers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class FinTransaction(Base):
    """Livro-caixa IMUTÁVEL. Correção = lançamento de estorno."""
    __tablename__ = "fin_transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_fin_amount_pos"),
        Index("ix_fin_date", "date"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("fin_accounts.id", ondelete="RESTRICT"))
    date: Mapped[date] = mapped_column(Date)
    kind: Mapped[FinKind] = mapped_column(_enum(FinKind))
    amount: Mapped[Decimal] = mapped_column(Money())
    category_id: Mapped[int] = mapped_column(ForeignKey("fin_categories.id", ondelete="RESTRICT"))
    cost_center_id: Mapped[int | None] = mapped_column(ForeignKey("cost_centers.id", ondelete="RESTRICT"))
    description: Mapped[str | None] = mapped_column(String(300))
    origin: Mapped[FinOrigin] = mapped_column(_enum(FinOrigin), default=FinOrigin.MANUAL)
    origin_ref: Mapped[str | None] = mapped_column(String(60))
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("fin_transactions.id", ondelete="RESTRICT"), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    account: Mapped[FinAccount] = relationship()
    category: Mapped[FinCategory] = relationship()


class Reconciliation(Base):
    """Conciliação manual: marca que o lançamento 'bateu' com o extrato."""
    __tablename__ = "reconciliations"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("fin_transactions.id", ondelete="RESTRICT"), unique=True)
    statement_date: Mapped[date | None] = mapped_column(Date)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class _BillMixin:
    description: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("fin_categories.id", ondelete="RESTRICT"))
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money())
    paid_amount: Mapped[Decimal] = mapped_column(Money(), default=Z)
    status: Mapped[BillStatus] = mapped_column(_enum(BillStatus), default=BillStatus.ABERTA)
    installment_no: Mapped[int] = mapped_column(Integer, default=1)
    installment_total: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    @property
    def open_amount(self) -> Decimal:
        return self.amount - self.paid_amount


class Payable(_BillMixin, Base):
    __tablename__ = "payables"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_pay_amount"),
                      CheckConstraint("paid_amount >= 0 AND paid_amount <= amount", name="ck_pay_paid"))
    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    purchase_id: Mapped[int | None] = mapped_column(ForeignKey("purchases.id", ondelete="RESTRICT"))
    supplier: Mapped[Supplier | None] = relationship()
    category: Mapped[FinCategory | None] = relationship()


class Receivable(_BillMixin, Base):
    __tablename__ = "receivables"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_rec_amount"),
                      CheckConstraint("paid_amount >= 0 AND paid_amount <= amount", name="ck_rec_paid"))
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str | None] = mapped_column(String(150))
    sale_id: Mapped[int | None] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    category: Mapped[FinCategory | None] = relationship()


# ------------------------------------------------------------------ compras
class Purchase(Base):
    __tablename__ = "purchases"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    status: Mapped[PurchaseStatus] = mapped_column(_enum(PurchaseStatus), default=PurchaseStatus.RASCUNHO)
    issue_date: Mapped[date] = mapped_column(Date)
    discount: Mapped[Decimal] = mapped_column(Money(), default=Z)
    extra_expenses: Mapped[Decimal] = mapped_column(Money(), default=Z)
    subtotal: Mapped[Decimal] = mapped_column(Money(), default=Z)
    total: Mapped[Decimal] = mapped_column(Money(), default=Z)
    payment_method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod), default=PaymentMethod.DINHEIRO)
    installments: Mapped[int] = mapped_column(Integer, default=1)
    first_due_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(300))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    supplier: Mapped[Supplier] = relationship()
    items: Mapped[list["PurchaseItem"]] = relationship(back_populates="purchase", cascade="all, delete-orphan",
                                                       order_by="PurchaseItem.id")


class PurchaseItem(Base):
    __tablename__ = "purchase_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_pi_qty"), CheckConstraint("unit_cost >= 0", name="ck_pi_cost"))
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchases.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(Quantity())
    unit_cost: Mapped[Decimal] = mapped_column(Money())
    effective_unit_cost: Mapped[Decimal | None] = mapped_column(Money())  # com rateio de desconto/despesas
    purchase: Mapped[Purchase] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    @property
    def line_total(self) -> Decimal:
        return self.quantity * self.unit_cost


# ------------------------------------------------------------------ vendas
class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str] = mapped_column(String(20), unique=True)
    status: Mapped[SaleStatus] = mapped_column(_enum(SaleStatus), default=SaleStatus.CONCLUIDA)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sale_date: Mapped[date] = mapped_column(Date)  # data local da venda (competência)
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    customer_name: Mapped[str | None] = mapped_column(String(150))
    subtotal: Mapped[Decimal] = mapped_column(Money(), default=Z)
    discount: Mapped[Decimal] = mapped_column(Money(), default=Z)
    total: Mapped[Decimal] = mapped_column(Money(), default=Z)
    paid_total: Mapped[Decimal] = mapped_column(Money(), default=Z)
    change: Mapped[Decimal] = mapped_column(Money(), default=Z)
    cogs: Mapped[Decimal] = mapped_column(Money(), default=Z)  # custo das mercadorias vendidas
    notes: Mapped[str | None] = mapped_column(String(300))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_reason: Mapped[str | None] = mapped_column(String(300))
    seller: Mapped[User | None] = relationship()
    items: Mapped[list["SaleItem"]] = relationship(back_populates="sale", cascade="all, delete-orphan",
                                                   order_by="SaleItem.id")
    payments: Mapped[list["SalePayment"]] = relationship(back_populates="sale", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_sales_date", "sale_date"),)


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_si_qty"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_name: Mapped[str] = mapped_column(String(200))     # snapshot
    quantity: Mapped[Decimal] = mapped_column(Quantity())
    unit_price: Mapped[Decimal] = mapped_column(Money())
    discount: Mapped[Decimal] = mapped_column(Money(), default=Z)
    total: Mapped[Decimal] = mapped_column(Money())
    unit_cost: Mapped[Decimal] = mapped_column(Money(), default=Z)  # custo médio no momento da venda
    stock_movement_id: Mapped[int | None] = mapped_column(ForeignKey("stock_movements.id", ondelete="RESTRICT"))
    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class SalePayment(Base):
    __tablename__ = "sale_payments"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_sp_amount"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="CASCADE"))
    method: Mapped[PaymentMethod] = mapped_column(_enum(PaymentMethod))
    method_note: Mapped[str | None] = mapped_column(String(60))  # nome do "outro meio"
    amount: Mapped[Decimal] = mapped_column(Money())             # valor aplicado à venda (sem troco)
    installments: Mapped[int] = mapped_column(Integer, default=1)
    due_date: Mapped[date | None] = mapped_column(Date)          # só para A_PRAZO
    sale: Mapped[Sale] = relationship(back_populates="payments")


class SaleReturn(Base):
    __tablename__ = "sale_returns"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_sr_qty"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id", ondelete="RESTRICT"))
    sale_item_id: Mapped[int] = mapped_column(ForeignKey("sale_items.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(Quantity())
    amount: Mapped[Decimal] = mapped_column(Money())      # valor devolvido ao cliente
    cost_amount: Mapped[Decimal] = mapped_column(Money())  # custo das mercadorias devolvidas ao estoque
    restock: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(String(300))
    return_date: Mapped[date] = mapped_column(Date)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    sale: Mapped[Sale] = relationship()
    item: Mapped[SaleItem] = relationship()


for _t, _name in (("fin_transactions", "fin_transactions"),):
    for _op, _msg in (("UPDATE", "Lançamentos financeiros são imutáveis: use estorno."),
                      ("DELETE", "Lançamentos financeiros não podem ser apagados: use estorno.")):
        event.listen(FinTransaction.__table__, "after_create", DDL(
            f"CREATE TRIGGER IF NOT EXISTS trg_fin_no_{_op.lower()} BEFORE {_op} ON fin_transactions "
            f"BEGIN SELECT RAISE(ABORT, '{_msg}'); END;"))
