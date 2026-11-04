"""Validação de FORMATO e dígitos verificadores de CPF/CNPJ.

IMPORTANTE: isto NÃO confirma a situação cadastral na Receita Federal.
CNPJ alfanumérico (em vigor desde jul/2026): módulo 11, valor = ASCII - 48
(IN RFB 2.229/2024). A regra também valida o CNPJ numérico tradicional.
"""
from __future__ import annotations

import re

_CNPJ_WEIGHTS_1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_CNPJ_WEIGHTS_2 = [6] + _CNPJ_WEIGHTS_1
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def only_digits(text: str | None) -> str:
    return re.sub(r"\D", "", text or "")


def normalize_cnpj(text: str | None) -> str:
    return re.sub(r"[.\-/\s]", "", (text or "")).upper()


def _cnpj_dv(chars: str, weights: list[int]) -> int:
    total = sum((ord(c) - 48) * w for c, w in zip(chars, weights))
    rest = total % 11
    return 0 if rest < 2 else 11 - rest


def validate_cnpj(text: str | None) -> bool:
    c = normalize_cnpj(text)
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", c):
        return False
    if len(set(c)) == 1:  # 00000000000000, 11111111111111...
        return False
    d1 = _cnpj_dv(c[:12], _CNPJ_WEIGHTS_1)
    d2 = _cnpj_dv(c[:12] + str(d1), _CNPJ_WEIGHTS_2)
    return c[12:] == f"{d1}{d2}"


def format_cnpj(text: str | None) -> str:
    c = normalize_cnpj(text)
    if len(c) != 14:
        return text or ""
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def validate_cpf(text: str | None) -> bool:
    c = only_digits(text)
    if len(c) != 11 or len(set(c)) == 1:
        return False
    for n in (9, 10):
        total = sum(int(c[i]) * (n + 1 - i) for i in range(n))
        dv = (total * 10) % 11 % 10
        if dv != int(c[n]):
            return False
    return True


def format_cpf(text: str | None) -> str:
    c = only_digits(text)
    if len(c) != 11:
        return text or ""
    return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"


def validate_cpf_or_cnpj(text: str | None) -> bool:
    """CPF se tiver 11 dígitos numéricos; senão tenta CNPJ (14 caracteres)."""
    if len(only_digits(text)) == 11 and len(normalize_cnpj(text)) == 11:
        return validate_cpf(text)
    return validate_cnpj(text)


def validate_email(text: str | None) -> bool:
    return bool(_EMAIL.match((text or "").strip()))


def validate_cnae(text: str | None) -> bool:
    """Formato do CNAE: 7 dígitos (aceita 0000-0/00)."""
    return len(only_digits(text)) == 7


def format_cnae(text: str | None) -> str:
    d = only_digits(text)
    return f"{d[:4]}-{d[4]}/{d[5:]}" if len(d) == 7 else (text or "")
