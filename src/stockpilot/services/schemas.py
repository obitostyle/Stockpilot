"""Entradas validadas (Pydantic). Mensagens em português para exibição direta."""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError as PydanticValidationError, field_validator

from ..domain.enums import TaxRegime, UnitOfMeasure
from ..domain.errors import ValidationError
from ..domain.validators import (
    normalize_cnpj, only_digits, validate_cnae, validate_cnpj, validate_email,
)

T = TypeVar("T", bound=BaseModel)

FIELD_LABELS = {
    "legal_name": "Razão social", "cnpj": "CNPJ", "email": "E-mail", "name": "Nome",
    "cost_price": "Preço de custo", "sale_price": "Preço de venda", "min_stock": "Estoque mínimo",
    "barcode": "Código de barras", "tax_regime": "Regime tributário", "cnae_primary": "CNAE principal",
    "cnae_secondary": "CNAE secundário", "unit": "Unidade", "activity_start_date": "Data de início",
}


def build(model: type[T], **data: Any) -> T:
    """Cria o modelo convertendo erros do Pydantic em ValidationError amigável."""
    try:
        return model(**data)
    except PydanticValidationError as exc:
        msgs = []
        for err in exc.errors():
            field = str(err["loc"][0]) if err["loc"] else ""
            label = FIELD_LABELS.get(field, field)
            msg = err["msg"].removeprefix("Value error, ")
            if err["type"] in ("missing", "enum", "decimal_parsing", "decimal_type"):
                msg = "valor ausente ou inválido"
            msgs.append(f"{label}: {msg}" if label else msg)
        raise ValidationError(msgs) from exc


def _to_decimal(v: Any) -> Decimal:
    try:
        d = v if isinstance(v, Decimal) else Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("número inválido")
    if not d.is_finite() or abs(d) > Decimal("999999999"):
        raise ValueError("número inválido ou fora do limite")
    return d


def _blank_to_none(v: Any) -> Any:
    if isinstance(v, str) and not v.strip():
        return None
    return v


class CompanyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    legal_name: str
    cnpj: str
    trade_name: str | None = None
    state_registration: str | None = None
    municipal_registration: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    tax_regime: TaxRegime | None = None
    activity_start_date: date | None = None
    cnae_primary: str | None = None
    cnae_secondary: list[str] = []

    _blank = field_validator(
        "trade_name", "state_registration", "municipal_registration", "address", "phone",
        "email", "tax_regime", "cnae_primary", mode="before",
    )(_blank_to_none)

    @field_validator("legal_name")
    @classmethod
    def _legal(cls, v: str) -> str:
        if not v:
            raise ValueError("informe a razão social")
        return v

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, v: str) -> str:
        if not validate_cnpj(v):
            raise ValueError("formato/dígito verificador inválido (isto não consulta a Receita Federal)")
        return normalize_cnpj(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        if v and not validate_email(v):
            raise ValueError("e-mail inválido")
        return v

    @field_validator("activity_start_date")
    @classmethod
    def _start(cls, v: date | None) -> date | None:
        if v and v > date.today():
            raise ValueError("não pode ser uma data futura")
        return v

    @field_validator("cnae_primary")
    @classmethod
    def _cnae1(cls, v: str | None) -> str | None:
        if v and not validate_cnae(v):
            raise ValueError("deve ter 7 dígitos (ex.: 4781-4/00)")
        return only_digits(v) if v else v

    @field_validator("cnae_secondary")
    @classmethod
    def _cnae2(cls, v: list[str]) -> list[str]:
        out = []
        for item in v:
            if not item.strip():
                continue
            if not validate_cnae(item):
                raise ValueError(f"'{item}' deve ter 7 dígitos")
            out.append(only_digits(item))
        return list(dict.fromkeys(out))


class ProductInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str
    internal_code: str | None = None
    sku: str | None = None
    barcode: str | None = None
    category_name: str | None = None
    brand: str | None = None
    description: str | None = None
    unit: UnitOfMeasure = UnitOfMeasure.UN
    allows_fraction: bool | None = None
    cost_price: Decimal = Decimal("0")
    sale_price: Decimal = Decimal("0")
    min_stock: Decimal = Decimal("0")
    location: str | None = None
    supplier_id: int | None = None
    active: bool = True

    _blank = field_validator(
        "internal_code", "sku", "barcode", "category_name", "brand", "description", "location",
        mode="before",
    )(_blank_to_none)

    @field_validator("cost_price", "sale_price", "min_stock", mode="before")
    @classmethod
    def _dec(cls, v: Any) -> Decimal:
        return _to_decimal(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v:
            raise ValueError("informe o nome do produto")
        return v

    @field_validator("barcode")
    @classmethod
    def _barcode(cls, v: str | None) -> str | None:
        if v and not re.fullmatch(r"\d{4,14}", v):
            raise ValueError("use apenas números (4 a 14 dígitos)")
        return v

    @field_validator("cost_price")
    @classmethod
    def _cost(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("não pode ser negativo")
        if -v.as_tuple().exponent > 4:
            raise ValueError("use no máximo 4 casas decimais")
        return v

    @field_validator("sale_price")
    @classmethod
    def _sale(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("não pode ser negativo")
        if -v.as_tuple().exponent > 2:
            raise ValueError("use no máximo 2 casas decimais (centavos)")
        return v

    @field_validator("min_stock")
    @classmethod
    def _min(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("não pode ser negativo")
        if -v.as_tuple().exponent > 3:
            raise ValueError("use no máximo 3 casas decimais")
        return v
