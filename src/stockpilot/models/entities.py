"""Modelo de dados da Fase 2. Ver docs/FASE1_PLANEJAMENTO.md para o modelo completo."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    DDL, Boolean, CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..domain.enums import MovementOrigin, MovementType, TaxRegime, UnitOfMeasure, UserRole
from ..infra.types import Money, Quantity
from .base import Base, utcnow


def _enum(cls):
    return Enum(cls, native_enum=False, length=30, create_constraint=True, validate_strings=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(_enum(UserRole), default=UserRole.OPERADOR)
    password_hash: Mapped[str | None] = mapped_column(String(300))  # scrypt; nunca texto puro
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Company(Base):
    __tablename__ = "company"
    id: Mapped[int] = mapped_column(primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str | None] = mapped_column(String(200))
    cnpj: Mapped[str] = mapped_column(String(14))  # normalizado (sem máscara)
    state_registration: Mapped[str | None] = mapped_column(String(30))
    municipal_registration: Mapped[str | None] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    tax_regime: Mapped[TaxRegime | None] = mapped_column(_enum(TaxRegime))
    activity_start_date: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    cnaes: Mapped[list["CompanyCnae"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", order_by="CompanyCnae.id"
    )


class CompanyCnae(Base):
    __tablename__ = "company_cnaes"
    __table_args__ = (UniqueConstraint("company_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("company.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(7))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    company: Mapped[Company] = relationship(back_populates="cnaes")


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    document: Mapped[str | None] = mapped_column(String(14), unique=True)  # CPF/CNPJ normalizado
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(String(300))
    notes: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("cost_price >= 0", name="ck_product_cost"),
        CheckConstraint("sale_price >= 0", name="ck_product_sale"),
        CheckConstraint("min_stock >= 0", name="ck_product_min"),
        Index("ix_products_name", "name"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    internal_code: Mapped[str] = mapped_column(String(30), unique=True)
    sku: Mapped[str | None] = mapped_column(String(60), unique=True)
    barcode: Mapped[str | None] = mapped_column(String(14), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    brand: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[UnitOfMeasure] = mapped_column(_enum(UnitOfMeasure), default=UnitOfMeasure.UN)
    allows_fraction: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_price: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"))  # custo médio ponderado atual
    sale_price: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"))
    quantity_on_hand: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"))
    min_stock: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"))
    location: Mapped[str | None] = mapped_column(String(80))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    category: Mapped[Category | None] = relationship()
    supplier: Mapped[Supplier | None] = relationship()

    @property
    def margin_percent(self) -> Decimal | None:
        """Margem estimada = (venda - custo) / venda. None se preço de venda = 0."""
        if not self.sale_price:
            return None
        return (self.sale_price - self.cost_price) / self.sale_price * 100

    @property
    def is_low_stock(self) -> bool:
        return self.min_stock > 0 and self.quantity_on_hand <= self.min_stock


class StockMovement(Base):
    """Livro-razão de estoque: IMUTÁVEL (triggers abaixo bloqueiam UPDATE/DELETE)."""
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity_delta <> 0", name="ck_mov_nonzero"),
        Index("ix_mov_product_date", "product_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    movement_type: Mapped[MovementType] = mapped_column(_enum(MovementType))
    quantity_delta: Mapped[Decimal] = mapped_column(Quantity())      # + entra, - sai
    balance_after: Mapped[Decimal] = mapped_column(Quantity())
    unit_cost: Mapped[Decimal | None] = mapped_column(Money())
    reason: Mapped[str | None] = mapped_column(String(300))
    origin: Mapped[MovementOrigin] = mapped_column(_enum(MovementOrigin), default=MovementOrigin.MANUAL)
    origin_ref: Mapped[str | None] = mapped_column(String(60))       # ex.: nº da compra/venda
    reverses_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="RESTRICT"), unique=True  # 1 estorno por movimentação
    )
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    product: Mapped[Product] = relationship()
    user: Mapped[User | None] = relationship()


_IMMUTABLE = [
    DDL("CREATE TRIGGER IF NOT EXISTS trg_stock_movements_no_update BEFORE UPDATE ON stock_movements "
        "BEGIN SELECT RAISE(ABORT, 'Movimentações de estoque são imutáveis: use estorno ou ajuste.'); END;"),
    DDL("CREATE TRIGGER IF NOT EXISTS trg_stock_movements_no_delete BEFORE DELETE ON stock_movements "
        "BEGIN SELECT RAISE(ABORT, 'Movimentações de estoque não podem ser apagadas: use estorno.'); END;"),
]
for _ddl in _IMMUTABLE:
    event.listen(StockMovement.__table__, "after_create", _ddl)
