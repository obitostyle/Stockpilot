from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..domain.enums import MovementOrigin
from ..domain.errors import DuplicateError, NotFoundError, ValidationError
from ..models import Category, Product, StockMovement, Supplier, utcnow
from . import stock_service
from .schemas import ProductInput

_SORTS = {
    "name": Product.name, "code": Product.internal_code, "quantity": Product.quantity_on_hand,
    "sale_price": Product.sale_price, "cost_price": Product.cost_price,
}


def get_or_create_category(session: Session, name: str | None) -> Category | None:
    if not name:
        return None
    cat = session.scalar(select(Category).where(func.lower(Category.name) == name.lower()))
    if cat is None:
        cat = Category(name=name)
        session.add(cat)
        session.flush()
    return cat


def list_categories(session: Session) -> list[Category]:
    return list(session.scalars(select(Category).order_by(Category.name)))


def list_suppliers(session: Session) -> list[Supplier]:
    return list(session.scalars(select(Supplier).where(Supplier.active.is_(True)).order_by(Supplier.name)))


def _next_code(session: Session) -> str:
    n = (session.scalar(select(func.max(Product.id))) or 0) + 1
    while True:
        code = f"P{n:06d}"
        if not session.scalar(select(Product.id).where(Product.internal_code == code)):
            return code
        n += 1


def _check_duplicates(session: Session, data: ProductInput, code: str, exclude_id: int | None) -> None:
    checks = [("internal_code", code, "Já existe um produto com o código interno"),
              ("sku", data.sku, "Já existe um produto com o SKU"),
              ("barcode", data.barcode, "Já existe um produto com o código de barras")]
    for column, value, msg in checks:
        if not value:
            continue
        stmt = select(Product.name).where(getattr(Product, column) == value)
        if exclude_id:
            stmt = stmt.where(Product.id != exclude_id)
        other = session.scalar(stmt)
        if other:
            raise DuplicateError(f"{msg} '{value}' (produto: {other}).")


def _apply(session: Session, product: Product, data: ProductInput) -> None:
    if data.supplier_id and not session.get(Supplier, data.supplier_id):
        raise ValidationError("Fornecedor não encontrado.")
    cat = get_or_create_category(session, data.category_name)
    product.name = data.name
    product.sku = data.sku
    product.barcode = data.barcode
    product.category_id = cat.id if cat else None
    product.brand = data.brand
    product.description = data.description
    product.unit = data.unit
    product.allows_fraction = (
        data.allows_fraction if data.allows_fraction is not None else data.unit.fractional_by_default
    )
    product.cost_price = data.cost_price
    product.sale_price = data.sale_price
    product.min_stock = data.min_stock
    product.location = data.location
    product.supplier_id = data.supplier_id
    product.active = data.active


def create_product(
    session: Session, data: ProductInput, initial_quantity: Decimal = Decimal("0"),
    user_id: int | None = None,
) -> Product:
    code = data.internal_code or _next_code(session)
    _check_duplicates(session, data, code, None)
    product = Product(internal_code=code, name=data.name)
    _apply(session, product, data)
    session.add(product)
    try:
        session.flush()
    except IntegrityError as exc:  # corrida improvável; mensagem amigável mesmo assim
        raise DuplicateError("Código, SKU ou código de barras já cadastrado.") from exc
    if initial_quantity and initial_quantity > 0:
        stock_service.register_entry(
            session, product.id, initial_quantity, product.cost_price, reason="Saldo inicial",
            origin=MovementOrigin.CADASTRO, user_id=user_id,
        )
    return product


def update_product(session: Session, product_id: int, data: ProductInput) -> Product:
    """Edita dados cadastrais. O saldo só muda por movimentação de estoque."""
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Produto não encontrado.")
    code = data.internal_code or product.internal_code
    _check_duplicates(session, data, code, product_id)
    new_fraction = (data.allows_fraction if data.allows_fraction is not None
                    else data.unit.fractional_by_default)
    if not new_fraction and product.quantity_on_hand != product.quantity_on_hand.to_integral_value():
        raise ValidationError("O saldo atual tem fração; ajuste o estoque antes de tornar o produto unitário.")
    product.internal_code = code
    _apply(session, product, data)
    session.flush()
    return product


def set_active(session: Session, product_id: int, active: bool) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Produto não encontrado.")
    product.active = active
    return product


class ProductUsage:
    """Quantos registros históricos apontam para o produto (movimentações, itens de venda e de compra)."""

    def __init__(self, movements: int, sales: int, purchases: int):
        self.movements, self.sales, self.purchases = movements, sales, purchases

    @property
    def has_history(self) -> bool:
        return bool(self.movements or self.sales or self.purchases)

    def describe(self) -> str:
        parts = []
        if self.movements:
            parts.append(f"{self.movements} movimentação(ões) de estoque")
        if self.sales:
            parts.append(f"{self.sales} item(ns) de venda")
        if self.purchases:
            parts.append(f"{self.purchases} item(ns) de compra")
        return ", ".join(parts)


def product_usage(session: Session, product_id: int) -> ProductUsage:
    from ..models import PurchaseItem, SaleItem

    def count(model) -> int:
        return session.scalar(select(func.count()).select_from(model).where(model.product_id == product_id)) or 0
    return ProductUsage(count(StockMovement), count(SaleItem), count(PurchaseItem))


def delete_product(session: Session, product_id: int) -> str:
    """Exclui definitivamente um produto SEM histórico. Retorna o nome do produto excluído.

    Produtos com movimentações, vendas ou compras não são apagados: o livro de estoque é imutável e
    os relatórios dependem desses registros. Nesses casos use a inativação (exclusão lógica)."""
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Produto não encontrado. Ele pode ter sido excluído em outra tela.")
    usage = product_usage(session, product_id)
    if usage.has_history:
        raise ValidationError(
            f"O produto '{product.name}' não pode ser excluído porque possui histórico ({usage.describe()}). "
            "Para tirá-lo das listas sem perder o histórico, use Inativar."
        )
    name = product.name
    session.delete(product)
    try:
        session.flush()
    except IntegrityError:
        raise ValidationError(f"O produto '{name}' está ligado a outros registros e não pode ser excluído. Use Inativar.")
    return name


def get_product(session: Session, product_id: int) -> Product:
    product = session.scalar(
        select(Product).options(joinedload(Product.category)).where(Product.id == product_id)
    )
    if product is None:
        raise NotFoundError("Produto não encontrado.")
    return product


def find_by_barcode(session: Session, barcode: str, include_inactive: bool = False) -> Product | None:
    """Busca EXATA pelo código de barras (leitor). Por padrão só produtos ativos (venda, compra)."""
    q = select(Product).where(Product.barcode == (barcode or "").strip())
    if not include_inactive:
        q = q.where(Product.active.is_(True))
    return session.scalar(q)


def barcode_owner(session: Session, barcode: str, exclude_id: int | None = None) -> Product | None:
    """Produto (ativo ou não) que já usa o código — para evitar duplicidade antes de salvar."""
    q = select(Product).where(Product.barcode == (barcode or "").strip())
    if exclude_id is not None:
        q = q.where(Product.id != exclude_id)
    return session.scalar(q)


def search_products(
    session: Session, text: str | None = None, *, category_id: int | None = None,
    only_active: bool = True, low_stock_only: bool = False, order_by: str = "name",
    descending: bool = False, limit: int | None = None, out_of_stock_only: bool = False,
) -> list[Product]:
    stmt = _filtered(select(Product).options(joinedload(Product.category)), text, category_id, only_active,
                     low_stock_only, out_of_stock_only)
    col = _SORTS.get(order_by, Product.name)
    stmt = stmt.order_by(col.desc() if descending else col.asc(), Product.id)
    if limit:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).unique())


def count_products(session: Session, text: str | None = None, *, category_id: int | None = None,
                   only_active: bool = True, low_stock_only: bool = False, out_of_stock_only: bool = False) -> int:
    stmt = _filtered(select(func.count(Product.id)), text, category_id, only_active, low_stock_only, out_of_stock_only)
    return int(session.scalar(stmt) or 0)


def _filtered(stmt, text, category_id, only_active, low_stock_only, out_of_stock_only):
    if text and text.strip():
        t = text.strip()
        stmt = stmt.where(or_(
            Product.name.icontains(t, autoescape=True), Product.internal_code.icontains(t, autoescape=True),
            Product.sku.icontains(t, autoescape=True), Product.barcode.icontains(t, autoescape=True),
        ))
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if only_active:
        stmt = stmt.where(Product.active.is_(True))
    if low_stock_only:
        stmt = stmt.where(Product.min_stock > 0, Product.quantity_on_hand <= Product.min_stock)
    if out_of_stock_only:
        stmt = stmt.where(Product.quantity_on_hand <= 0)
    return stmt


def products_without_movement(session: Session, days: int = 90) -> list[Product]:
    cutoff = utcnow() - timedelta(days=days)
    recent = exists().where(StockMovement.product_id == Product.id, StockMovement.created_at >= cutoff)
    return list(session.scalars(
        select(Product).where(Product.active.is_(True), ~recent).order_by(Product.name)
    ))


def export_products_xlsx(session: Session, path: Path | str) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Produtos"
    headers = ["Código", "Nome", "SKU", "Código de barras", "Categoria", "Marca", "Unidade",
               "Custo médio (R$)", "Preço de venda (R$)", "Margem (%)", "Estoque", "Estoque mínimo",
               "Localização", "Situação"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for p in search_products(session, only_active=False):
        margin = p.margin_percent
        ws.append([
            p.internal_code, p.name, p.sku, p.barcode, p.category.name if p.category else None,
            p.brand, p.unit.value, float(p.cost_price), float(p.sale_price),  # Excel só guarda float
            float(round(margin, 1)) if margin is not None else None,
            float(p.quantity_on_hand), float(p.min_stock), p.location,
            "Ativo" if p.active else "Inativo",
        ])
    for col, w in zip("ABCDEFGHIJKLMN", [12, 38, 16, 18, 18, 16, 10, 16, 18, 12, 12, 14, 16, 10]):
        ws.column_dimensions[col].width = w
    out = Path(path)
    wb.save(out)
    return out
