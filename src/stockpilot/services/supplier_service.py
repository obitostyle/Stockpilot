from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..domain.errors import DuplicateError, NotFoundError, ValidationError
from ..domain.validators import normalize_cnpj, only_digits, validate_cpf_or_cnpj, validate_email
from ..models import Supplier


def _norm_doc(doc: str | None) -> str | None:
    doc = (doc or "").strip()
    if not doc:
        return None
    if not validate_cpf_or_cnpj(doc):
        raise ValidationError("CPF/CNPJ inválido (confere formato e dígitos; não consulta a Receita Federal).")
    digits = only_digits(doc)
    return digits if len(digits) == 11 and len(normalize_cnpj(doc)) == 11 else normalize_cnpj(doc)


def save_supplier(session: Session, *, name: str, document: str | None = None, phone: str | None = None,
                  email: str | None = None, address: str | None = None, notes: str | None = None,
                  active: bool = True, supplier_id: int | None = None) -> Supplier:
    name = (name or "").strip()
    if not name:
        raise ValidationError("Informe o nome ou razão social do fornecedor.")
    email = (email or "").strip() or None
    if email and not validate_email(email):
        raise ValidationError("E-mail inválido.")
    doc = _norm_doc(document)
    if doc:
        other = session.scalar(select(Supplier).where(Supplier.document == doc, Supplier.id != (supplier_id or 0)))
        if other:
            raise DuplicateError(f"Já existe o fornecedor '{other.name}' com este CPF/CNPJ.")
    if supplier_id:
        sup = session.get(Supplier, supplier_id)
        if sup is None:
            raise NotFoundError("Fornecedor não encontrado.")
    else:
        sup = Supplier(name=name)
        session.add(sup)
    sup.name, sup.document, sup.email, sup.active = name, doc, email, active
    sup.phone = (phone or "").strip() or None
    sup.address = (address or "").strip() or None
    sup.notes = (notes or "").strip() or None
    session.flush()
    return sup


def list_suppliers(session: Session, text: str | None = None, only_active: bool = True) -> list[Supplier]:
    stmt = select(Supplier).order_by(Supplier.name)
    if only_active:
        stmt = stmt.where(Supplier.active.is_(True))
    if text and text.strip():
        t = text.strip()
        stmt = stmt.where(or_(Supplier.name.icontains(t, autoescape=True),
                              Supplier.document.icontains(only_digits(t) or t, autoescape=True)))
    return list(session.scalars(stmt))
