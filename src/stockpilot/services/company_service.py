from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Company, CompanyCnae
from .schemas import CompanyInput


def get_company(session: Session) -> Company | None:
    return session.scalar(select(Company).order_by(Company.id).limit(1))


def save_company(session: Session, data: CompanyInput) -> Company:
    company = get_company(session)
    if company is None:
        company = Company(legal_name=data.legal_name, cnpj=data.cnpj)
        session.add(company)
    company.legal_name = data.legal_name
    company.cnpj = data.cnpj
    for f in ("trade_name", "state_registration", "municipal_registration", "address",
              "phone", "email", "tax_regime", "activity_start_date"):
        setattr(company, f, getattr(data, f))
    company.cnaes.clear()
    session.flush()
    if data.cnae_primary:
        company.cnaes.append(CompanyCnae(code=data.cnae_primary, is_primary=True))
    for code in data.cnae_secondary:
        if code != data.cnae_primary:
            company.cnaes.append(CompanyCnae(code=code, is_primary=False))
    session.flush()
    return company

