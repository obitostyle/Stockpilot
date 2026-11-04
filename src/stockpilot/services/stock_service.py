"""Motor de estoque.

Garantias:
* Todo saldo muda SOMENTE por uma movimentação gravada na mesma transação.
* Movimentações são imutáveis (trigger no banco); correção = estorno ou ajuste.
* Estoque negativo bloqueado, salvo configuração explícita.
* Ajuste, inventário e estorno exigem usuário identificado e motivo.
* `idempotency_key` impede duplicar uma operação (ex.: clique repetido em compra).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..domain.enums import MovementOrigin, MovementType
from ..domain.errors import InsufficientStockError, NotFoundError, ValidationError
from ..domain.formatting import format_qty
from ..models import Product, StockMovement, utcnow
from .settings_service import get_bool

log = logging.getLogger("stockpilot.stock")
MAX_QTY = Decimal("999999999")


def _dec(value) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Use Decimal para quantidades e valores")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Produto não encontrado.")
    return product


def _check_quantity(product: Product, qty: Decimal, *, allow_zero: bool = False) -> None:
    if not qty.is_finite() or qty > MAX_QTY:
        raise ValidationError("Quantidade inválida ou acima do limite permitido.")
    if qty < 0 or (qty == 0 and not allow_zero):
        raise ValidationError("A quantidade deve ser maior que zero.")
    if -qty.as_tuple().exponent > 3:
        raise ValidationError("Use no máximo 3 casas decimais na quantidade.")
    if not product.allows_fraction and qty != qty.to_integral_value():
        raise ValidationError(
            f"O produto '{product.name}' é controlado por unidade inteira; informe uma quantidade sem fração."
        )


def _existing_by_key(session: Session, key: str | None) -> StockMovement | None:
    if not key:
        return None
    return session.scalar(select(StockMovement).where(StockMovement.idempotency_key == key))


def _post(
    session: Session, product: Product, delta: Decimal, mtype: MovementType, *,
    origin: MovementOrigin, reason: str | None, origin_ref: str | None, unit_cost: Decimal | None,
    user_id: int | None, idempotency_key: str | None, reverses_id: int | None = None,
) -> StockMovement:
    new_balance = product.quantity_on_hand + delta
    if new_balance < 0 and not get_bool(session, "allow_negative_stock"):
        raise InsufficientStockError(
            f"Estoque insuficiente para '{product.name}': disponível "
            f"{format_qty(product.quantity_on_hand)}, solicitado {format_qty(-delta)}."
        )
    product.quantity_on_hand = new_balance
    mov = StockMovement(
        product_id=product.id, movement_type=mtype, quantity_delta=delta, balance_after=new_balance,
        unit_cost=unit_cost, reason=(reason or "").strip() or None, origin=origin,
        origin_ref=origin_ref, reverses_movement_id=reverses_id, user_id=user_id,
        idempotency_key=idempotency_key,
    )
    session.add(mov)
    session.flush()
    log.info("mov id=%s prod=%s tipo=%s delta=%s saldo=%s user=%s",
             mov.id, product.id, mtype.value, delta, new_balance, user_id)
    return mov


def register_entry(
    session: Session, product_id: int, quantity, unit_cost=None, *, reason: str | None = None,
    origin: MovementOrigin = MovementOrigin.MANUAL, origin_ref: str | None = None,
    user_id: int | None = None, idempotency_key: str | None = None,
) -> StockMovement:
    """Entrada de mercadoria. Com `unit_cost`, recalcula o custo médio ponderado."""
    if (dup := _existing_by_key(session, idempotency_key)):
        return dup
    product = _get_product(session, product_id)
    qty = _dec(quantity)
    _check_quantity(product, qty)
    cost = None
    if unit_cost is not None:
        cost = _dec(unit_cost)
        if cost < 0 or -cost.as_tuple().exponent > 4:
            raise ValidationError("O custo unitário deve ser positivo, com no máximo 4 casas decimais.")
        old = product.quantity_on_hand
        if old > 0:
            avg = (old * product.cost_price + qty * cost) / (old + qty)
        else:
            avg = cost
        product.cost_price = avg.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)
    return _post(session, product, qty, MovementType.ENTRADA, origin=origin, reason=reason,
                 origin_ref=origin_ref, unit_cost=cost, user_id=user_id,
                 idempotency_key=idempotency_key)


def register_exit(
    session: Session, product_id: int, quantity, *, reason: str | None = None,
    origin: MovementOrigin = MovementOrigin.MANUAL, origin_ref: str | None = None,
    user_id: int | None = None, idempotency_key: str | None = None,
) -> StockMovement:
    """Saída de mercadoria. Registra o custo médio vigente (base do CMV na Fase 4)."""
    if (dup := _existing_by_key(session, idempotency_key)):
        return dup
    product = _get_product(session, product_id)
    qty = _dec(quantity)
    _check_quantity(product, qty)
    return _post(session, product, -qty, MovementType.SAIDA, origin=origin, reason=reason,
                 origin_ref=origin_ref, unit_cost=product.cost_price, user_id=user_id,
                 idempotency_key=idempotency_key)


def _require_identified(user_id: int | None, reason: str | None, what: str) -> None:
    if user_id is None:
        raise ValidationError(f"{what} exige um usuário identificado.")
    if not reason or len(reason.strip()) < 3:
        raise ValidationError(f"Informe o motivo do {what.lower()}.")


def adjust(session: Session, product_id: int, delta, reason: str, user_id: int | None) -> StockMovement:
    """Ajuste manual (+/-). Exige motivo e usuário."""
    _require_identified(user_id, reason, "Ajuste")
    product = _get_product(session, product_id)
    d = _dec(delta)
    _check_quantity(product, abs(d))
    return _post(session, product, d, MovementType.AJUSTE, origin=MovementOrigin.MANUAL,
                 reason=reason, origin_ref=None, unit_cost=product.cost_price, user_id=user_id,
                 idempotency_key=None)


def inventory_count(
    session: Session, product_id: int, counted, reason: str, user_id: int | None
) -> StockMovement | None:
    """Acerta o saldo para a contagem física. Retorna None se não houve divergência."""
    _require_identified(user_id, reason, "Inventário")
    product = _get_product(session, product_id)
    qty = _dec(counted)
    _check_quantity(product, qty, allow_zero=True)
    delta = qty - product.quantity_on_hand
    if delta == 0:
        return None
    return _post(session, product, delta, MovementType.INVENTARIO, origin=MovementOrigin.INVENTARIO,
                 reason=reason, origin_ref=None, unit_cost=product.cost_price, user_id=user_id,
                 idempotency_key=None)


def reverse_movement(session: Session, movement_id: int, reason: str, user_id: int | None) -> StockMovement:
    """Estorna uma movimentação criando a movimentação inversa (a original permanece)."""
    _require_identified(user_id, reason, "Estorno")
    original = session.get(StockMovement, movement_id)
    if original is None:
        raise NotFoundError("Movimentação não encontrada.")
    if original.movement_type == MovementType.ESTORNO:
        raise ValidationError("Um estorno não pode ser estornado. Registre uma nova movimentação.")
    already = session.scalar(
        select(StockMovement.id).where(StockMovement.reverses_movement_id == movement_id)
    )
    if already:
        raise ValidationError("Esta movimentação já foi estornada.")
    product = _get_product(session, original.product_id)
    return _post(session, product, -original.quantity_delta, MovementType.ESTORNO,
                 origin=MovementOrigin.ESTORNO, reason=reason, origin_ref=f"mov:{original.id}",
                 unit_cost=original.unit_cost, user_id=user_id, idempotency_key=None,
                 reverses_id=original.id)


def history(
    session: Session, *, product_id: int | None = None, start: datetime | None = None,
    end: datetime | None = None, types: list[MovementType] | None = None,
    text: str | None = None, limit: int = 1000,
) -> list[StockMovement]:
    stmt = (select(StockMovement).join(Product, Product.id == StockMovement.product_id)
            .options(joinedload(StockMovement.product), joinedload(StockMovement.user))
            .order_by(StockMovement.id.desc()).limit(limit))
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if start:
        stmt = stmt.where(StockMovement.created_at >= start)
    if end:
        stmt = stmt.where(StockMovement.created_at <= end)
    if types:
        stmt = stmt.where(StockMovement.movement_type.in_(types))
    if text and text.strip():
        t = text.strip()
        stmt = stmt.where(or_(Product.name.icontains(t, autoescape=True),
                              Product.internal_code.icontains(t, autoescape=True)))
    return list(session.scalars(stmt).unique())


def history_for_key(session: Session, idempotency_key: str) -> StockMovement | None:
    return _existing_by_key(session, idempotency_key)


def is_reversed(session: Session, movement_id: int) -> bool:
    return session.scalar(
        select(func.count()).where(StockMovement.reverses_movement_id == movement_id)
    ) > 0


def verify_consistency(session: Session) -> list[tuple[int, Decimal, Decimal]]:
    """Compara saldo armazenado x soma das movimentações. Lista inconsistências."""
    sums = dict(session.execute(
        select(StockMovement.product_id, func.sum(StockMovement.quantity_delta)).group_by(StockMovement.product_id)
    ).all())
    problems = []
    for p in session.scalars(select(Product)):
        raw = sums.get(p.id)
        computed = Decimal(raw) if raw is not None else Decimal("0")  # sum() já vem convertido pelo tipo
        if computed != p.quantity_on_hand:
            problems.append((p.id, p.quantity_on_hand, computed))
    return problems


def recent_similar(session: Session, product_id: int, movement_type: MovementType, quantity_delta,
                   seconds: int = 120) -> StockMovement | None:
    """Movimentação manual idêntica (mesmo produto, tipo e quantidade) registrada há pouco.

    Usada para avisar o operador antes de lançar algo que parece repetido (ex.: nota digitada duas vezes)."""
    cutoff = utcnow() - timedelta(seconds=seconds)
    return session.scalar(
        select(StockMovement).where(
            StockMovement.product_id == product_id, StockMovement.movement_type == movement_type,
            StockMovement.quantity_delta == _dec(quantity_delta), StockMovement.created_at >= cutoff,
        ).order_by(StockMovement.id.desc()).limit(1))


def batch_move(session: Session, kind: str, lines: dict[int, tuple[Decimal, Decimal | None]], *,
               user_id: int | None, reason: str | None, batch_key: str) -> int:
    """Entrada ou saída de vários produtos de uma vez, TUDO OU NADA (uma única transação).

    `lines`: produto -> (quantidade, custo unitário opcional — só para entrada).
    `batch_key` torna a operação idempotente: reenviar o mesmo lote não duplica nada."""
    if kind not in ("entrada", "saida"):
        raise ValidationError("Tipo de lote inválido.")
    if not lines:
        raise ValidationError("Adicione ao menos um produto ao lote.")
    n = 0
    with session.begin_nested():
        for pid, (qty, cost) in lines.items():
            key = f"lote:{batch_key}:{pid}"
            if kind == "entrada":
                register_entry(session, pid, qty, cost, reason=reason, user_id=user_id, idempotency_key=key)
            else:
                register_exit(session, pid, qty, reason=reason, user_id=user_id, idempotency_key=key)
            n += 1
    return n
