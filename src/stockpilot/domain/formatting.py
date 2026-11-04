"""Formatação e leitura de valores no padrão brasileiro. Nunca usa float."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_THOUSANDS = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def _group(q: Decimal, places: int) -> str:
    s = f"{q:,.{places}f}"  # 1,234.56
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def format_decimal(value: Decimal, places: int = 2) -> str:
    q = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return _group(q, places)


def format_brl(value: Decimal | int | None, places: int = 2) -> str:
    if value is None:
        return "—"
    q = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    return f"{sign}R$ {_group(abs(q), places)}"


def _cost_places(value: Decimal) -> int:
    """2 casas quando o valor é 'redondo' em centavos; senão 4 (custo médio)."""
    return 2 if value == Decimal(value).quantize(Decimal("0.01")) else 4


def format_cost(value: Decimal | None) -> str:
    return "—" if value is None else format_brl(value, _cost_places(value))


def format_cost_plain(value: Decimal) -> str:
    return format_decimal(value, _cost_places(value))


def format_qty(value: Decimal | None, fractional: bool = True) -> str:
    if value is None:
        return "—"
    d = Decimal(value)
    if not fractional or d == d.to_integral_value():
        return _group(d.quantize(Decimal(1)), 0)
    s = _group(d.quantize(Decimal("0.001")), 3).rstrip("0")
    return s.rstrip(",")


def format_percent(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{format_decimal(value, 1)}%"


def format_date(d: date | datetime | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def utc_to_local(dt: datetime) -> datetime:
    """Datas são guardadas em UTC (naive); converte para o fuso do computador."""
    return dt.replace(tzinfo=timezone.utc).astimezone()


def format_datetime_local(dt: datetime | None) -> str:
    return utc_to_local(dt).strftime("%d/%m/%Y %H:%M") if dt else ""


def parse_decimal_br(text: str) -> Decimal:
    """Aceita '1.234,56', '1234,56', 'R$ 12,50', '1.5', '2'.

    Ponto como separador de milhar só é aceito no padrão 1.234 / 1.234.567;
    caso contrário, um único ponto é tratado como decimal ('1.5' = 1,5).
    """
    t = (text or "").replace("R$", "").replace(" ", "").strip()
    if not t:
        raise ValueError("valor vazio")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif _THOUSANDS.match(t):
        t = t.replace(".", "")
    try:
        d = Decimal(t)
    except InvalidOperation as exc:
        raise ValueError(f"valor inválido: {text!r}") from exc
    if not d.is_finite():
        raise ValueError(f"valor inválido: {text!r}")
    return d


def parse_date_br(text: str) -> date | None:
    t = (text or "").strip()
    if not t or t.replace("/", "").replace("_", "").strip() == "":
        return None
    return datetime.strptime(t, "%d/%m/%Y").date()
