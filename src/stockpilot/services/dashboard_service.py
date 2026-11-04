from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.enums import SaleStatus
from ..models import Company, Product, Sale, StockMovement
from . import finance_service as fin


@dataclass(frozen=True)
class DashboardData:
    has_company: bool
    total_products: int
    low_stock_count: int
    out_of_stock_count: int
    stock_value_at_cost: Decimal
    movements_count: int
    sales_today_count: int = 0
    sales_today_total: Decimal = Decimal("0")
    sales_month_total: Decimal = Decimal("0")
    month_gross_profit: Decimal = Decimal("0")
    month_expenses: Decimal = Decimal("0")
    month_result: Decimal = Decimal("0")
    receivable_open: Decimal = Decimal("0")
    receivable_overdue: Decimal = Decimal("0")
    payable_open: Decimal = Decimal("0")
    payable_overdue: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")
    daily_sales: list = field(default_factory=list)   # [(data, total)] últimos 30 dias


def load_dashboard(session: Session) -> DashboardData:
    """Todos os números vêm do banco; sem dados => zeros."""
    active = Product.active.is_(True)
    total = session.scalar(select(func.count()).select_from(Product).where(active)) or 0
    low = session.scalar(select(func.count()).select_from(Product).where(
        active, Product.min_stock > 0, Product.quantity_on_hand <= Product.min_stock)) or 0
    out = session.scalar(select(func.count()).select_from(Product).where(
        active, Product.quantity_on_hand <= 0)) or 0
    value = Decimal("0")
    for qty, cost in session.execute(
        select(Product.quantity_on_hand, Product.cost_price).where(active, Product.quantity_on_hand > 0)
    ):
        value += qty * cost
    movs = session.scalar(select(func.count()).select_from(StockMovement)) or 0
    has_company = session.scalar(select(func.count()).select_from(Company)) > 0
    today = date.today()
    cnt, tot = session.execute(select(func.count(), func.coalesce(func.sum(Sale.total), 0)).where(
        Sale.status == SaleStatus.CONCLUIDA, Sale.sale_date == today)).one()
    start30 = today - timedelta(days=29)
    by_day = {d: Decimal(t) for d, t in session.execute(
        select(Sale.sale_date, func.sum(Sale.total)).where(
            Sale.status == SaleStatus.CONCLUIDA, Sale.sale_date >= start30).group_by(Sale.sale_date))}
    daily = [(start30 + timedelta(days=i), by_day.get(start30 + timedelta(days=i), Decimal("0"))) for i in range(30)]
    r = fin.result_summary(session, today.replace(day=1), today)
    return DashboardData(
        has_company, total, low, out, value, movs, cnt, Decimal(tot), r.gross_revenue - r.returns,
        r.gross_profit, r.expenses, r.operating_result, fin.open_total(session, "R"),
        fin.open_total(session, "R", due_until=today - timedelta(days=1)), fin.open_total(session, "P"),
        fin.open_total(session, "P", due_until=today - timedelta(days=1)), fin.total_cash_balance(session), daily)
