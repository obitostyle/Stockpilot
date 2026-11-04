"""Tributário (tabelas versionadas com origem/vigência) e folha de pagamento."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..domain.enums import AssessmentStatus, EmployeeStatus, TaxRegime
from ..infra.types import Money, ScaledDecimal
from .base import Base, utcnow
from .entities import _enum

Z = Decimal("0")


class TaxParameter(Base):
    """Parâmetro legal com vigência (ex.: salário mínimo, dedução por dependente)."""
    __tablename__ = "tax_parameters"
    __table_args__ = (UniqueConstraint("key", "valid_from"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(String(40))          # texto: preserva casas decimais exatas
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(400))
    verified_at: Mapped[date] = mapped_column(Date)


class TaxTable(Base):
    __tablename__ = "tax_tables"
    __table_args__ = (UniqueConstraint("code", "valid_from"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40))            # SIMPLES_ANEXO_I, INSS_EMPREGADO, IRRF_MENSAL...
    description: Mapped[str] = mapped_column(String(200))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    legal_basis: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(500))         # onde a tabela foi conferida
    verified_at: Mapped[date] = mapped_column(Date)           # data da última conferência/atualização
    notes: Mapped[str | None] = mapped_column(String(400))
    brackets: Mapped[list["TaxBracket"]] = relationship(back_populates="table", cascade="all, delete-orphan",
                                                         order_by="TaxBracket.position")


class TaxBracket(Base):
    __tablename__ = "tax_brackets"
    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("tax_tables.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    upper_limit: Mapped[Decimal | None] = mapped_column(Money())   # None = sem teto
    rate_percent: Mapped[Decimal] = mapped_column(ScaledDecimal(4))
    deduction: Mapped[Decimal] = mapped_column(Money(), default=Z)
    table: Mapped[TaxTable] = relationship(back_populates="brackets")


class RevenueEntry(Base):
    """Faturamento informado manualmente. Para COMÉRCIO, substitui o valor calculado das vendas daquele mês."""
    __tablename__ = "revenue_entries"
    __table_args__ = (UniqueConstraint("competence", "activity"), CheckConstraint("amount >= 0", name="ck_rev_amt"))
    id: Mapped[int] = mapped_column(primary_key=True)
    competence: Mapped[str] = mapped_column(String(7))        # AAAA-MM
    activity: Mapped[str] = mapped_column(String(12))         # COMERCIO | INDUSTRIA | SERVICOS
    amount: Mapped[Decimal] = mapped_column(Money())
    notes: Mapped[str | None] = mapped_column(String(300))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaxAssessment(Base):
    """Histórico de estimativas. Nunca apagado: uma nova apuração da mesma competência marca a anterior como substituída."""
    __tablename__ = "tax_assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    competence: Mapped[str] = mapped_column(String(7))
    regime: Mapped[TaxRegime] = mapped_column(_enum(TaxRegime))
    description: Mapped[str] = mapped_column(String(200))
    table_id: Mapped[int | None] = mapped_column(ForeignKey("tax_tables.id", ondelete="RESTRICT"))
    revenue_month: Mapped[Decimal] = mapped_column(Money(), default=Z)
    rbt12: Mapped[Decimal | None] = mapped_column(Money())
    nominal_rate: Mapped[Decimal | None] = mapped_column(ScaledDecimal(4))
    deduction: Mapped[Decimal | None] = mapped_column(Money())
    effective_rate: Mapped[Decimal | None] = mapped_column(ScaledDecimal(6))   # em %
    amount: Mapped[Decimal] = mapped_column(Money(), default=Z)
    status: Mapped[AssessmentStatus] = mapped_column(_enum(AssessmentStatus), default=AssessmentStatus.ESTIMATIVA)
    due_date: Mapped[date | None] = mapped_column(Date)
    warnings: Mapped[str] = mapped_column(Text, default="[]")  # JSON
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_amount: Mapped[Decimal | None] = mapped_column(Money())
    paid_date: Mapped[date | None] = mapped_column(Date)
    payment_notes: Mapped[str | None] = mapped_column(String(300))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaxObligation(Base):
    __tablename__ = "tax_obligations"
    __table_args__ = (UniqueConstraint("name", "competence"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    competence: Mapped[str] = mapped_column(String(7))
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="PENDENTE")  # PENDENTE | CUMPRIDA
    notes: Mapped[str | None] = mapped_column(String(300))
    done_at: Mapped[date | None] = mapped_column(Date)


# ------------------------------------------------------------------ folha
class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (CheckConstraint("base_salary >= 0", name="ck_emp_sal"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    cpf: Mapped[str] = mapped_column(String(11), unique=True)
    job_title: Mapped[str | None] = mapped_column(String(100))
    admission_date: Mapped[date] = mapped_column(Date)
    termination_date: Mapped[date | None] = mapped_column(Date)
    base_salary: Mapped[Decimal] = mapped_column(Money())
    weekly_hours: Mapped[int] = mapped_column(Integer, default=44)
    dependents: Mapped[int] = mapped_column(Integer, default=0)
    overtime_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(2), default=Decimal("50"))
    overtime_sunday_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(2), default=Decimal("100"))
    night_pct: Mapped[Decimal] = mapped_column(ScaledDecimal(2), default=Decimal("20"))
    vt_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    vt_monthly_cost: Mapped[Decimal] = mapped_column(Money(), default=Z)
    status: Mapped[EmployeeStatus] = mapped_column(_enum(EmployeeStatus), default=EmployeeStatus.ATIVO)
    contract_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    benefits: Mapped[list["EmployeeBenefit"]] = relationship(back_populates="employee", cascade="all, delete-orphan")
    salary_history: Mapped[list["SalaryHistory"]] = relationship(back_populates="employee", cascade="all, delete-orphan",
                                                                 order_by="SalaryHistory.effective_date")


class SalaryHistory(Base):
    __tablename__ = "salary_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    effective_date: Mapped[date] = mapped_column(Date)
    salary: Mapped[Decimal] = mapped_column(Money())
    reason: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    employee: Mapped[Employee] = relationship(back_populates="salary_history")


class EmployeeBenefit(Base):
    __tablename__ = "employee_benefits"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    monthly_value: Mapped[Decimal] = mapped_column(Money())          # custo para a empresa
    employee_discount: Mapped[Decimal] = mapped_column(Money(), default=Z)  # coparticipação descontada do funcionário
    employee: Mapped[Employee] = relationship(back_populates="benefits")


class PayrollSlip(Base):
    """Demonstrativo ESTIMADO. Não é folha oficial nem fechamento."""
    __tablename__ = "payroll_slips"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    competence: Mapped[str] = mapped_column(String(7))
    inputs: Mapped[str] = mapped_column(Text)        # JSON dos lançamentos do mês
    lines: Mapped[str] = mapped_column(Text)         # JSON das linhas do demonstrativo
    gross: Mapped[Decimal] = mapped_column(Money())
    inss: Mapped[Decimal] = mapped_column(Money())
    irrf: Mapped[Decimal] = mapped_column(Money())
    other_deductions: Mapped[Decimal] = mapped_column(Money())
    net: Mapped[Decimal] = mapped_column(Money())
    fgts: Mapped[Decimal] = mapped_column(Money())
    employer_charges: Mapped[Decimal | None] = mapped_column(Money())
    benefits_cost: Mapped[Decimal] = mapped_column(Money(), default=Z)
    total_cost: Mapped[Decimal | None] = mapped_column(Money())
    warnings: Mapped[str] = mapped_column(Text, default="[]")
    missing: Mapped[str] = mapped_column(Text, default="[]")
    rules: Mapped[str] = mapped_column(Text, default="{}")           # versões das tabelas usadas
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    employee: Mapped[Employee] = relationship()


class PayrollSimulation(Base):
    __tablename__ = "payroll_simulations"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(20))    # FERIAS | DECIMO_TERCEIRO | RESCISAO
    reference_date: Mapped[date] = mapped_column(Date)
    result: Mapped[str] = mapped_column(Text)        # JSON
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    employee: Mapped[Employee] = relationship()
