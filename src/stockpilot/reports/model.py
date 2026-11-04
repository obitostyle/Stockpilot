"""Estrutura comum de relatório: dados + metadados exigidos (período, geração, critérios)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from ..domain.formatting import format_brl, format_date, format_percent, format_qty

# tipos de coluna: text, money, qty, int, pct, date
Column = tuple[str, str]


@dataclass
class ReportData:
    key: str
    title: str
    period: str                      # texto do período, ex.: "01/10/2026 a 31/10/2026" ou "Posição em 01/11/2026"
    criteria: list[str]              # filtros e regras de cálculo usados
    columns: list[Column]
    rows: list[list] = field(default_factory=list)
    totals: list | None = None       # linha de totais (mesmo nº de colunas; None = sem total naquela coluna)
    notes: list[str] = field(default_factory=list)   # avisos (estimativa, dados faltantes...)
    generated_at: datetime = field(default_factory=datetime.now)
    company: str = ""


def fmt(value, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return format_brl(Decimal(value))
    if kind == "qty":
        return format_qty(Decimal(value), Decimal(value) != Decimal(value).to_integral_value())
    if kind == "pct":
        return format_percent(Decimal(value))
    if kind == "date":
        return format_date(value) if isinstance(value, (date, datetime)) else str(value)
    if kind == "int":
        return f"{int(value):,}".replace(",", ".")
    return str(value)
