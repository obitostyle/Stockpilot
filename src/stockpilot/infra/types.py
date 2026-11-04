"""Tipos de coluna para dinheiro e quantidades SEM ponto flutuante.

SQLite não possui DECIMAL real (o tipo NUMERIC do SQLAlchemy vira float).
Guardamos inteiros "escalados": valor * 10**scale. Assim somas e comparações
em SQL são exatas e o Python sempre recebe Decimal.
"""
from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from sqlalchemy import Integer
from sqlalchemy.types import TypeDecorator


class ScaledDecimal(TypeDecorator):
    impl = Integer
    cache_ok = True

    def __init__(self, scale: int):
        super().__init__()
        self.scale = scale

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("float não é permitido em valores monetários/quantidades; use Decimal")
        d = value if isinstance(value, Decimal) else Decimal(str(value))
        return int((d.scaleb(self.scale)).to_integral_value(rounding=ROUND_HALF_EVEN))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return Decimal(value).scaleb(-self.scale)


def Money() -> ScaledDecimal:      # 4 casas: custo médio precisa de precisão maior que centavos
    return ScaledDecimal(4)


def Quantity() -> ScaledDecimal:   # 3 casas: kg, litros, metros
    return ScaledDecimal(3)
