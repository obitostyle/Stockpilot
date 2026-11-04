"""Visão gerencial do estoque: indicadores, giro (saídas por produto) e reposição sugerida.

Tudo é calculado a partir do livro de movimentações e do cadastro — nenhum dado é estimado
fora disso. Os critérios estão descritos em CRITERIOS para aparecerem na interface.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..domain.enums import MovementType
from ..models import Product, StockMovement, utcnow

STALE_DAYS = 90

CRITERIOS = (
    "Giro = saídas registradas no período (vendas e saídas manuais), menos os estornos dessas saídas. "
    "Média diária = giro ÷ dias do período. Cobertura = saldo ÷ média diária. "
    "Entra na reposição o produto ativo com saldo no mínimo ou abaixo, ou com cobertura menor que 7 dias. "
    "Quantidade sugerida = o necessário para chegar ao maior valor entre 2× o estoque mínimo e a média diária × "
    "os dias de cobertura desejados. É uma sugestão: confira antes de comprar."
)


@dataclass
class StockOverview:
    active_products: int
    value_at_cost: Decimal
    below_min: int
    out_of_stock: int
    stale: int  # ativos com saldo e sem nenhuma movimentação há STALE_DAYS dias


@dataclass
class ProductTurnover:
    product_id: int
    code: str
    name: str
    unit: str
    allows_fraction: bool
    quantity: Decimal
    min_stock: Decimal
    cost_price: Decimal
    exits: Decimal            # saídas líquidas no período
    entries: Decimal          # entradas no período
    avg_daily: Decimal
    cover_days: Decimal | None  # None = sem saídas no período
    last_movement: datetime | None


@dataclass
class Suggestion:
    item: ProductTurnover
    suggested: Decimal
    reason: str


def overview(session: Session) -> StockOverview:
    active = Product.active.is_(True)
    # valor calculado em Python: quantidades e valores são inteiros escalonados no banco (não multiplicar em SQL)
    rows = session.execute(select(Product.quantity_on_hand, Product.cost_price).where(active)).all()
    n = len(rows)
    value = sum((q * c for q, c in rows if q > 0), Decimal("0"))
    below = session.scalar(select(func.count()).select_from(Product).where(active, Product.min_stock > 0,
                                                      Product.quantity_on_hand <= Product.min_stock,
                                                      Product.quantity_on_hand > 0))
    zero = session.scalar(select(func.count()).select_from(Product).where(active, Product.quantity_on_hand <= 0))
    cutoff = utcnow() - timedelta(days=STALE_DAYS)
    recent = select(StockMovement.product_id).where(StockMovement.created_at >= cutoff)
    stale = session.scalar(select(func.count()).select_from(Product).where(active, Product.quantity_on_hand > 0,
                                                      Product.id.not_in(recent)))
    return StockOverview(n, value.quantize(Decimal("0.01")),
                         int(below or 0), int(zero or 0), int(stale or 0))


def turnover(session: Session, days: int = 30, only_active: bool = True) -> list[ProductTurnover]:
    """Giro por produto no período (uma consulta agregada — rápido mesmo com muitos produtos)."""
    days = max(1, int(days))
    cutoff = utcnow() - timedelta(days=days)
    m = StockMovement
    exits_ = func.sum(case((m.movement_type == MovementType.SAIDA, -m.quantity_delta), else_=0))
    # estornos de saída (cancelamento/devolução de venda) devolvem quantidade: descontam do giro
    reversed_exit = select(m.id).where(m.movement_type == MovementType.SAIDA).scalar_subquery()
    rev = func.sum(case(((m.movement_type == MovementType.ESTORNO) & m.reverses_movement_id.in_(reversed_exit),
                         m.quantity_delta), else_=0))
    entries_ = func.sum(case((m.movement_type == MovementType.ENTRADA, m.quantity_delta), else_=0))
    period = (select(m.product_id, exits_.label("ex"), rev.label("rv"), entries_.label("en"))
              .where(m.created_at >= cutoff).group_by(m.product_id).subquery())
    last = select(m.product_id, func.max(m.created_at).label("last")).group_by(m.product_id).subquery()
    q = (select(Product, period.c.ex, period.c.rv, period.c.en, last.c.last)
         .outerjoin(period, period.c.product_id == Product.id)
         .outerjoin(last, last.c.product_id == Product.id))
    if only_active:
        q = q.where(Product.active.is_(True))
    out = []
    for p, ex, rv, en, last_at in session.execute(q):
        exits = max(Decimal("0"), Decimal(str(ex or 0)) - Decimal(str(rv or 0)))
        avg = (exits / days).quantize(Decimal("0.001"))
        cover = (p.quantity_on_hand / avg).quantize(Decimal("0.1")) if avg > 0 else None
        out.append(ProductTurnover(p.id, p.internal_code, p.name, p.unit.value, p.allows_fraction,
                                   p.quantity_on_hand, p.min_stock, p.cost_price, exits,
                                   Decimal(str(en or 0)), avg, cover, last_at))
    return out


def _round_up(q: Decimal, frac: bool) -> Decimal:
    return q.quantize(Decimal("0.001"), ROUND_CEILING) if frac else q.to_integral_value(ROUND_CEILING)


def replenishment(session: Session, days: int = 30, cover_days: int = 30) -> list[Suggestion]:
    """Produtos que precisam de reposição, do mais urgente para o menos urgente."""
    res = []
    for t in turnover(session, days):
        low = t.min_stock > 0 and t.quantity <= t.min_stock
        short = t.cover_days is not None and t.cover_days < 7
        if not (low or short or t.quantity <= 0 < t.exits):
            continue
        target = max(t.min_stock * 2, t.exits * cover_days / max(1, int(days)))  # sem o arredondamento da média
        sug = _round_up(max(Decimal("0"), target - max(t.quantity, Decimal("0"))), t.allows_fraction)
        if sug <= 0:
            continue
        if t.quantity <= 0:
            why = "Sem saldo"
        elif low:
            why = "Abaixo do mínimo"
        else:
            why = f"Cobertura de {t.cover_days} dia(s)"
        res.append(Suggestion(t, sug, why))
    res.sort(key=lambda s: (s.item.quantity > 0, s.item.cover_days if s.item.cover_days is not None else Decimal(10**9),
                            s.item.name.lower()))
    return res
