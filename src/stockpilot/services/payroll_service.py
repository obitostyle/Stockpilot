"""Folha de pagamento — SIMULAÇÃO ESTIMADA. Não é folha oficial, não gera eSocial/GFIP/holerite legal.

Princípios:
* tabelas de INSS/IRRF vêm de `tax_rules` (dados com vigência e fonte); faltou tabela => erro explícito;
* cada resultado traz `warnings` (limitações) e `missing` (dados que o usuário precisa informar);
* acesso restrito a ADMIN/GERENTE (dados pessoais e salariais — LGPD);
* o que NÃO está implementado é dito na tela, nunca omitido (ver LIMITATIONS).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..domain.enums import EmployeeStatus, TaxRegime, UserRole
from ..domain.errors import PermissionDeniedError, ValidationError
from ..domain.validators import only_digits, validate_cpf
from ..models import (Company, Employee, EmployeeBenefit, PayrollSimulation, PayrollSlip, SalaryHistory, User)
from .settings_service import get_setting
from .tax_rules import get_param, get_table

Z = D("0")
LIMITATIONS = [
    "Simulação estimada: não substitui a folha oficial nem o contador; não gera eSocial, GFIP/FGTS Digital ou holerite legal.",
    "Hora noturna reduzida (52min30s), insalubridade/periculosidade, comissões, pensão alimentícia e reflexos não são calculados; use 'outros proventos/descontos'.",
    "Desconto de DSR por faltas injustificadas não é calculado.",
    "Convenção coletiva da categoria pode alterar percentuais e pisos: confira.",
]


def q2(v: D) -> D:
    return v.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def guard(session: Session, user_id: int | None) -> None:
    u = session.get(User, user_id) if user_id else None
    if u is None or not u.active or u.role not in (UserRole.ADMIN, UserRole.GERENTE):
        raise PermissionDeniedError("Apenas Administrador ou Gerente acessam Funcionários e Folha.")


# ------------------------------------------------------------------ cadastro
@dataclass
class EmployeeData:
    name: str
    cpf: str
    admission_date: date
    base_salary: D
    job_title: str | None = None
    weekly_hours: int = 44
    dependents: int = 0
    overtime_pct: D = D("50")
    overtime_sunday_pct: D = D("100")
    night_pct: D = D("20")
    vt_enabled: bool = False
    vt_monthly_cost: D = Z
    contract_notes: str | None = None


def _check(d: EmployeeData) -> str:
    if not d.name.strip():
        raise ValidationError("Informe o nome.")
    cpf = only_digits(d.cpf)
    if not validate_cpf(cpf):
        raise ValidationError("CPF inválido.")
    if not isinstance(d.base_salary, D) or d.base_salary <= 0:
        raise ValidationError("Informe um salário base maior que zero.")
    if not 1 <= d.weekly_hours <= 44:
        raise ValidationError("Jornada semanal deve estar entre 1 e 44 horas.")
    if d.dependents < 0:
        raise ValidationError("Número de dependentes inválido.")
    if d.overtime_pct < 50 or d.overtime_sunday_pct < 50:
        raise ValidationError("Hora extra tem adicional mínimo de 50% (CF art. 7º, XVI).")
    if d.night_pct < 20:
        raise ValidationError("Adicional noturno mínimo é 20% (CLT art. 73).")
    if d.vt_enabled and d.vt_monthly_cost < 0:
        raise ValidationError("Custo do vale-transporte inválido.")
    return cpf


def save_employee(session: Session, user_id: int, data: EmployeeData, employee_id: int | None = None,
                  salary_reason: str | None = None) -> Employee:
    guard(session, user_id)
    cpf = _check(data)
    dup = session.scalar(select(Employee).where(Employee.cpf == cpf))
    if dup is not None and dup.id != employee_id:
        raise ValidationError("Já existe funcionário com este CPF.")
    if employee_id is None:
        e = Employee(cpf=cpf, name=data.name.strip(), admission_date=data.admission_date, base_salary=data.base_salary)
        session.add(e)
        session.flush()
        session.add(SalaryHistory(employee_id=e.id, effective_date=data.admission_date, salary=data.base_salary,
                                  reason="Admissão", user_id=user_id))
    else:
        e = session.get(Employee, employee_id)
        if e is None:
            raise ValidationError("Funcionário não encontrado.")
        if e.base_salary != data.base_salary:
            session.add(SalaryHistory(employee_id=e.id, effective_date=date.today(), salary=data.base_salary,
                                      reason=salary_reason or "Alteração de salário", user_id=user_id))
        e.cpf, e.name, e.admission_date, e.base_salary = cpf, data.name.strip(), data.admission_date, data.base_salary
    for f in ("job_title", "weekly_hours", "dependents", "overtime_pct", "overtime_sunday_pct", "night_pct",
              "vt_enabled", "vt_monthly_cost", "contract_notes"):
        setattr(e, f, getattr(data, f))
    session.flush()
    return e


def set_status(session: Session, user_id: int, employee_id: int, status: EmployeeStatus,
               termination_date: date | None = None) -> Employee:
    guard(session, user_id)
    e = session.get(Employee, employee_id)
    if e is None:
        raise ValidationError("Funcionário não encontrado.")
    if status == EmployeeStatus.DESLIGADO:
        if termination_date is None or termination_date < e.admission_date:
            raise ValidationError("Informe a data de desligamento (não pode ser anterior à admissão).")
        e.termination_date = termination_date
    else:
        e.termination_date = None
    e.status = status
    session.flush()
    return e


def list_employees(session: Session, user_id: int, include_terminated: bool = True) -> list[Employee]:
    guard(session, user_id)
    q = select(Employee).order_by(Employee.name)
    if not include_terminated:
        q = q.where(Employee.status != EmployeeStatus.DESLIGADO)
    return list(session.scalars(q))


def get_employee(session: Session, user_id: int, employee_id: int) -> Employee:
    guard(session, user_id)
    e = session.scalar(select(Employee).options(joinedload(Employee.benefits), joinedload(Employee.salary_history))
                       .where(Employee.id == employee_id))
    if e is None:
        raise ValidationError("Funcionário não encontrado.")
    return e


def add_benefit(session: Session, user_id: int, employee_id: int, name: str, monthly_value: D,
                employee_discount: D = Z) -> EmployeeBenefit:
    guard(session, user_id)
    if not name.strip() or monthly_value < 0 or employee_discount < 0 or employee_discount > monthly_value:
        raise ValidationError("Benefício inválido: informe nome e valores (desconto não pode exceder o custo).")
    b = EmployeeBenefit(employee_id=employee_id, name=name.strip(), monthly_value=monthly_value,
                        employee_discount=employee_discount)
    session.add(b)
    session.flush()
    return b


def remove_benefit(session: Session, user_id: int, benefit_id: int) -> None:
    guard(session, user_id)
    b = session.get(EmployeeBenefit, benefit_id)
    if b:
        session.delete(b)
        session.flush()


# ------------------------------------------------------------------ INSS / IRRF
def inss_employee(session: Session, base: D, ref: date) -> D:
    """INSS progressivo: cada alíquota só sobre a parcela da faixa; base limitada ao teto da última faixa."""
    t = get_table(session, "INSS_EMPREGADO", ref)
    total, lower = Z, Z
    for b in sorted(t.brackets, key=lambda x: x.position):
        top = b.upper_limit
        if base <= lower:
            break
        part = (min(base, top) if top is not None else base) - lower
        total += part * b.rate_percent / 100
        if top is None:
            break
        lower = top
    return q2(total)


def _irrf_tax(table, base: D) -> D:
    if base <= 0:
        return Z
    for b in sorted(table.brackets, key=lambda x: x.position):
        if b.upper_limit is None or base <= b.upper_limit:
            return max(Z, base * b.rate_percent / 100 - b.deduction)
    return Z


def irrf_reduction(session: Session, taxable_gross: D, ref: date) -> D:
    """Redução mensal da Lei 15.270/2025 (parâmetros com vigência em `tax_parameters`)."""
    full = get_param(session, "irrf_reduction_full_until", ref)
    upto = get_param(session, "irrf_reduction_until", ref)
    if taxable_gross <= full:
        return D("Infinity")  # imposto zerado
    if taxable_gross > upto:
        return Z
    return max(Z, get_param(session, "irrf_reduction_a", ref) - get_param(session, "irrf_reduction_b", ref) * taxable_gross)


def irrf_monthly(session: Session, taxable_gross: D, inss: D, dependents: int, ref: date,
                 apply_reduction: bool = True) -> tuple[D, str]:
    """Retorna (IRRF estimado, descrição do método). Usa a opção (legal × simplificado) que gera MENOS imposto."""
    t = get_table(session, "IRRF_MENSAL", ref)
    dep = get_param(session, "irrf_dependent_deduction", ref) * dependents
    simp = get_param(session, "irrf_simplified_discount", ref)
    tax_legal = _irrf_tax(t, taxable_gross - inss - dep)
    tax_simp = _irrf_tax(t, taxable_gross - simp)
    tax, how = (tax_legal, "deduções legais (INSS + dependentes)") if tax_legal <= tax_simp else (tax_simp, "desconto simplificado")
    if apply_reduction:
        red = irrf_reduction(session, taxable_gross, ref)
        if red == D("Infinity"):
            return Z, how + "; zerado pela redução da Lei 15.270/2025"
        if red > 0:
            tax = max(Z, tax - red)
            how += f"; redução Lei 15.270/2025 de R$ {q2(red)}"
    return q2(tax), how


# ------------------------------------------------------------------ folha mensal
@dataclass
class PayrollInputs:
    overtime_hours: D = Z            # horas extras dias úteis (adicional do cadastro)
    overtime_sunday_hours: D = Z     # domingos/feriados
    night_hours: D = Z               # horas em período noturno (adicional)
    absence_days: D = Z              # faltas injustificadas
    late_minutes: D = Z
    other_earnings: D = Z            # proventos tributáveis (comissão etc.), informados pelo usuário
    other_discounts: D = Z           # descontos (adiantamento etc.)
    dsr_days_off: int | None = None  # domingos+feriados do mês (p/ reflexo de HE no DSR)
    dsr_workdays: int | None = None  # dias úteis do mês


@dataclass
class Line:
    code: str
    description: str
    kind: str   # 'P' provento | 'D' desconto | 'I' informativo (custo empresa)
    value: D


@dataclass
class PayslipResult:
    employee_id: int
    competence: str
    lines: list[Line] = field(default_factory=list)
    gross: D = Z
    inss: D = Z
    irrf: D = Z
    other_deductions: D = Z
    net: D = Z
    fgts: D = Z
    patronal: D | None = None
    employer_charges: D | None = None
    benefits_cost: D = Z
    total_cost: D | None = None
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    rules: dict = field(default_factory=dict)
    label: str = "ESTIMATIVA — simulação, não é folha oficial"


def hourly_rate(e: Employee) -> D:
    return e.base_salary / (D(e.weekly_hours) * 5)  # 44h -> 220 h/mês


def calculate_payslip(session: Session, user_id: int, employee_id: int, competence: str,
                      inp: PayrollInputs | None = None) -> PayslipResult:
    guard(session, user_id)
    inp = inp or PayrollInputs()
    e = session.scalar(select(Employee).options(joinedload(Employee.benefits)).where(Employee.id == employee_id))
    if e is None:
        raise ValidationError("Funcionário não encontrado.")
    y, m = int(competence[:4]), int(competence[5:7])
    ref = date(y, m, 1)
    for v in (inp.overtime_hours, inp.overtime_sunday_hours, inp.night_hours, inp.absence_days, inp.late_minutes,
              inp.other_earnings, inp.other_discounts):
        if not isinstance(v, D) or v < 0:
            raise ValidationError("Lançamentos do mês devem ser números zero ou positivos.")
    if inp.absence_days > 30:
        raise ValidationError("Faltas não podem passar de 30 dias.")
    res = PayslipResult(e.id, competence)
    res.warnings += LIMITATIONS
    rate = hourly_rate(e)
    L = res.lines
    L.append(Line("SAL", "Salário base", "P", q2(e.base_salary)))
    he = q2(inp.overtime_hours * rate * (1 + e.overtime_pct / 100))
    hes = q2(inp.overtime_sunday_hours * rate * (1 + e.overtime_sunday_pct / 100))
    if he:
        L.append(Line("HE", f"Horas extras ({e.overtime_pct}%)", "P", he))
    if hes:
        L.append(Line("HE100", f"Horas extras domingo/feriado ({e.overtime_sunday_pct}%)", "P", hes))
    if he or hes:
        if inp.dsr_days_off is not None and inp.dsr_workdays:
            dsr = q2((he + hes) / inp.dsr_workdays * inp.dsr_days_off)
            L.append(Line("DSR", "Reflexo das horas extras no DSR", "P", dsr))
        else:
            res.missing.append("Dias úteis e domingos/feriados do mês, para o reflexo das horas extras no DSR (não incluído).")
    night = q2(inp.night_hours * rate * e.night_pct / 100)
    if night:
        L.append(Line("ADN", f"Adicional noturno ({e.night_pct}%)", "P", night))
    if inp.other_earnings:
        L.append(Line("OUT", "Outros proventos tributáveis (informados)", "P", q2(inp.other_earnings)))
    ab = q2(inp.absence_days * e.base_salary / 30)
    if ab:
        L.append(Line("FALTA", "Faltas injustificadas", "D", ab))
    late = q2(inp.late_minutes / 60 * rate)
    if late:
        L.append(Line("ATRASO", "Atrasos", "D", late))
    gross = sum((l.value for l in L if l.kind == "P"), Z) - ab - late
    res.gross = q2(gross)
    res.inss = inss_employee(session, res.gross, ref)
    L.append(Line("INSS", "INSS (tabela progressiva)", "D", res.inss))
    res.irrf, how = irrf_monthly(session, res.gross, res.inss, e.dependents, ref)
    if res.irrf:
        L.append(Line("IRRF", f"IRRF ({how})", "D", res.irrf))
    else:
        res.warnings.append(f"IRRF zero ({how}).")
    other = inp.other_discounts
    if e.vt_enabled:
        vt = min(q2(e.base_salary * D("0.06")), e.vt_monthly_cost) if e.vt_monthly_cost > 0 else q2(e.base_salary * D("0.06"))
        if e.vt_monthly_cost <= 0:
            res.missing.append("Custo mensal do vale-transporte (usado o teto de 6% do salário base).")
        L.append(Line("VT", "Vale-transporte (até 6% do salário base)", "D", vt))
        other += vt
    for b in e.benefits:
        if b.employee_discount:
            L.append(Line("BEN", f"Coparticipação — {b.name}", "D", b.employee_discount))
            other += b.employee_discount
    if inp.other_discounts:
        L.append(Line("DESC", "Outros descontos (informados)", "D", q2(inp.other_discounts)))
    res.other_deductions = q2(other)
    res.net = q2(res.gross - res.inss - res.irrf - res.other_deductions)
    # custos do empregador
    res.fgts = q2(res.gross * D("0.08"))
    L.append(Line("FGTS", "FGTS 8% (depósito do empregador)", "I", res.fgts))
    res.benefits_cost = q2(sum((b.monthly_value for b in e.benefits), Z))
    res.rules = {"INSS": _ver(session, "INSS_EMPREGADO", ref), "IRRF": _ver(session, "IRRF_MENSAL", ref)}
    c = session.scalar(select(Company))
    regime = c.tax_regime if c else None
    patronal = None
    if regime is None:
        res.missing.append("Regime tributário da empresa (define a contribuição patronal).")
    elif regime == TaxRegime.SIMPLES_NACIONAL:
        patronal = Z
        res.warnings.append("Simples Nacional (Anexos I, II, III e V): a contribuição patronal (CPP) está incluída no DAS; não é somada aqui. Confirme seu anexo com o contador.")
    elif regime == TaxRegime.MEI:
        res.missing.append("Contribuição patronal do MEI com empregado: regra não implementada — confirmar com o contador.")
    else:
        rat, terc = get_setting(session, "rat_percent"), get_setting(session, "terceiros_percent")
        if not rat or not terc:
            res.missing.append("RAT/FAP e alíquota de terceiros (Sistema S) da empresa — informe em Configurações. INSS patronal-base: 20%.")
        else:
            try:
                patronal = q2(res.gross * (D("20") + D(rat) + D(terc)) / 100)
            except Exception:
                res.missing.append("RAT/terceiros inválidos em Configurações.")
    res.patronal = patronal
    if patronal is not None:
        res.employer_charges = q2(res.fgts + patronal)
        res.total_cost = q2(res.gross + res.employer_charges + res.benefits_cost)
    return res


def _ver(session: Session, code: str, ref: date) -> str:
    t = get_table(session, code, ref)
    return f"{t.code} vigência {t.valid_from:%d/%m/%Y}, fonte: {t.source}"


def save_payslip(session: Session, user_id: int, r: PayslipResult, inp: PayrollInputs | None = None) -> PayrollSlip:
    guard(session, user_id)
    for old in session.scalars(select(PayrollSlip).where(PayrollSlip.employee_id == r.employee_id,
                                                         PayrollSlip.competence == r.competence,
                                                         PayrollSlip.superseded.is_(False))):
        old.superseded = True
    s = PayrollSlip(
        employee_id=r.employee_id, competence=r.competence,
        inputs=json.dumps(inp.__dict__ if inp else {}, default=str, ensure_ascii=False),
        lines=json.dumps([(l.code, l.description, l.kind, str(l.value)) for l in r.lines], ensure_ascii=False),
        gross=r.gross, inss=r.inss, irrf=r.irrf, other_deductions=r.other_deductions, net=r.net, fgts=r.fgts,
        employer_charges=r.employer_charges, benefits_cost=r.benefits_cost, total_cost=r.total_cost,
        warnings=json.dumps(r.warnings, ensure_ascii=False), missing=json.dumps(r.missing, ensure_ascii=False),
        rules=json.dumps(r.rules, ensure_ascii=False), user_id=user_id)
    session.add(s)
    session.flush()
    return s


def payroll_history(session: Session, user_id: int, competence: str | None = None) -> list[PayrollSlip]:
    guard(session, user_id)
    q = select(PayrollSlip).options(joinedload(PayrollSlip.employee)).where(PayrollSlip.superseded.is_(False)) \
        .order_by(PayrollSlip.competence.desc(), PayrollSlip.id.desc())
    if competence:
        q = q.where(PayrollSlip.competence == competence)
    return list(session.scalars(q).unique())


# ------------------------------------------------------------------ simulações
@dataclass
class SimResult:
    kind: str
    title: str
    items: list[tuple[str, D]] = field(default_factory=list)   # proventos
    deductions: list[tuple[str, D]] = field(default_factory=list)
    total: D = Z
    net: D = Z
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    label: str = "ESTIMATIVA — simulação, não é cálculo oficial"


def _avos(start: date, end: date) -> int:
    """Meses (avos) do ano de `end`: cada mês com ≥15 dias trabalhados conta 1 avo."""
    first = max(start, date(end.year, 1, 1))
    n = 0
    for mm in range(first.month, end.month + 1):
        a = first if mm == first.month else date(end.year, mm, 1)
        nxt = date(end.year + (mm == 12), mm % 12 + 1, 1)
        last_day = min(end, date.fromordinal(nxt.toordinal() - 1))
        if (last_day - a).days + 1 >= 15:
            n += 1
    return n


def _inss_irrf_plain(session, base, deps, ref):
    inss = inss_employee(session, base, ref)
    t = get_table(session, "IRRF_MENSAL", ref)
    dep = get_param(session, "irrf_dependent_deduction", ref) * deps
    return inss, q2(_irrf_tax(t, base - inss - dep))


def simulate_13th(session: Session, user_id: int, employee_id: int, year: int,
                  until: date | None = None) -> SimResult:
    guard(session, user_id)
    e = session.get(Employee, employee_id)
    if e is None:
        raise ValidationError("Funcionário não encontrado.")
    end = until or date(year, 12, 31)
    avos = _avos(e.admission_date, end)
    total = q2(e.base_salary / 12 * avos)
    ref = date(year, 12, 1)
    inss, irrf = _inss_irrf_plain(session, total, e.dependents, ref)
    first = q2(total / 2)
    r = SimResult("DECIMO_TERCEIRO", f"13º salário {year} — {avos}/12 avos")
    r.items = [("13º proporcional (salário base ÷ 12 × avos)", total)]
    r.deductions = [("INSS sobre o 13º (2ª parcela)", inss), ("IRRF sobre o 13º (2ª parcela)", irrf)]
    r.total, r.net = total, q2(total - inss - irrf)
    r.items.append((f"1ª parcela (50%, sem descontos, até 30/11)", first))
    r.items.append((f"2ª parcela líquida (até 20/12)", q2(total - first - inss - irrf)))
    r.warnings = LIMITATIONS[:1] + [
        "Médias de horas extras/comissões no 13º não são incluídas (informe em 'outros proventos' se houver).",
        "O IRRF do 13º é calculado com a tabela progressiva e deduções legais, SEM a redução da Lei 15.270/2025: regra de aplicação ao 13º NÃO verificada — confira com o contador."]
    return r


def simulate_vacation(session: Session, user_id: int, employee_id: int, start: date, days: int = 30,
                      sell_days: int = 0) -> SimResult:
    guard(session, user_id)
    e = session.get(Employee, employee_id)
    if e is None:
        raise ValidationError("Funcionário não encontrado.")
    if days not in range(5, 31) or sell_days < 0 or sell_days > 10 or days + sell_days > 30:
        raise ValidationError("Dias de férias inválidos (mín. 5; abono de até 10 dias; total máximo 30).")
    daily = e.base_salary / 30
    pay = q2(daily * days)
    third = q2(pay / 3)
    abono = q2(daily * sell_days)
    abono3 = q2(abono / 3)
    base = pay + third
    ref = date(start.year, start.month, 1)
    inss, irrf = _inss_irrf_plain(session, base, e.dependents, ref)
    r = SimResult("FERIAS", f"Férias de {days} dias a partir de {start:%d/%m/%Y}")
    r.items = [("Férias", pay), ("1/3 constitucional", third)]
    if sell_days:
        r.items += [(f"Abono pecuniário ({sell_days} dias)", abono), ("1/3 do abono", abono3)]
    r.deductions = [("INSS sobre férias + 1/3", inss), ("IRRF sobre férias + 1/3", irrf)]
    r.total = q2(sum((v for _, v in r.items), Z))
    r.net = q2(r.total - inss - irrf)
    r.warnings = LIMITATIONS[:1] + [
        "Abono pecuniário tratado como não tributável (verbas indenizatórias): confirme com o contador.",
        "Férias pagas até 2 dias antes do início; média de horas extras/comissões não incluída.",
        "IRRF sem a redução da Lei 15.270/2025 (aplicação a férias NÃO verificada) — confira."]
    return r


REASONS = {"SEM_JUSTA_CAUSA": "Dispensa sem justa causa", "PEDIDO_DEMISSAO": "Pedido de demissão",
           "ACORDO": "Acordo (CLT art. 484-A)", "JUSTA_CAUSA": "Dispensa por justa causa"}


def simulate_termination(session: Session, user_id: int, employee_id: int, reason: str, termination: date,
                         vacation_due_periods: int = 0, fgts_balance: D | None = None,
                         notice_worked: bool = False) -> SimResult:
    guard(session, user_id)
    e = session.get(Employee, employee_id)
    if e is None:
        raise ValidationError("Funcionário não encontrado.")
    if reason not in REASONS:
        raise ValidationError("Motivo inválido.")
    if termination < e.admission_date:
        raise ValidationError("Data de desligamento anterior à admissão.")
    daily = e.base_salary / 30
    r = SimResult("RESCISAO", f"Rescisão — {REASONS[reason]} em {termination:%d/%m/%Y}")
    r.items.append((f"Saldo de salário ({termination.day} dias)", q2(daily * min(termination.day, 30))))
    years = (termination - e.admission_date).days // 365
    notice_days = min(90, 30 + 3 * years)
    projected = termination
    if reason == "SEM_JUSTA_CAUSA" and not notice_worked:
        r.items.append((f"Aviso prévio indenizado ({notice_days} dias — Lei 12.506)", q2(daily * notice_days)))
        projected = date.fromordinal(termination.toordinal() + notice_days)
    elif reason == "ACORDO" and not notice_worked:
        r.items.append((f"Aviso prévio indenizado, 50% ({notice_days} dias)", q2(daily * notice_days / 2)))
        projected = date.fromordinal(termination.toordinal() + notice_days)
    elif reason == "PEDIDO_DEMISSAO":
        r.warnings.append("Pedido de demissão: se o aviso prévio não for cumprido, a empresa pode descontar o valor — não calculado.")
    if reason != "JUSTA_CAUSA":
        avos13 = _avos(e.admission_date, projected if reason in ("SEM_JUSTA_CAUSA", "ACORDO") else termination)
        r.items.append((f"13º proporcional ({avos13}/12)", q2(e.base_salary / 12 * avos13)))
        # férias proporcionais: meses do período aquisitivo corrente
        months = 0
        a = e.admission_date
        while True:
            nxt = date(a.year + (a.month == 12), a.month % 12 + 1, min(a.day, 28))
            if nxt > termination:
                break
            a = nxt
            months += 1
        months = months % 12
        extra = 1 if (termination - a).days >= 14 else 0
        mp = min(12, months + extra)
        prop = q2(e.base_salary / 12 * mp)
        r.items.append((f"Férias proporcionais ({mp}/12)", prop))
        r.items.append(("1/3 sobre férias proporcionais", q2(prop / 3)))
    if vacation_due_periods > 0:
        v = q2(e.base_salary * vacation_due_periods)
        r.items.append((f"Férias vencidas ({vacation_due_periods} período(s))", v))
        r.items.append(("1/3 sobre férias vencidas", q2(v / 3)))
    else:
        r.missing.append("Períodos de férias vencidas não gozadas (informe, se houver).")
    if reason in ("SEM_JUSTA_CAUSA", "ACORDO"):
        if fgts_balance is None:
            r.missing.append("Saldo do FGTS (extrato da Caixa) para calcular a multa de 40%/20%.")
        else:
            pct = D("0.40") if reason == "SEM_JUSTA_CAUSA" else D("0.20")
            r.items.append((f"Multa do FGTS ({int(pct * 100)}% do saldo informado)", q2(fgts_balance * pct)))
    r.total = q2(sum((v for _, v in r.items), Z))
    r.net = r.total
    r.warnings = LIMITATIONS[:1] + [
        "INSS/IRRF sobre saldo de salário, 13º e férias NÃO são calculados nesta simulação: o líquido mostrado é BRUTO.",
        "FGTS sobre as verbas rescisórias e a baixa no eSocial/TRCT não são tratados.",
        "Estabilidades, feriados, médias de variáveis e convenção coletiva não considerados."] + r.warnings
    r.deductions = [("INSS/IRRF da rescisão — não calculados", Z)]
    return r


def save_simulation(session: Session, user_id: int, employee_id: int, ref_date: date, r: SimResult) -> PayrollSimulation:
    guard(session, user_id)
    payload = {"title": r.title, "items": [(a, str(b)) for a, b in r.items], "deductions": [(a, str(b)) for a, b in r.deductions],
               "total": str(r.total), "net": str(r.net), "warnings": r.warnings, "missing": r.missing}
    s = PayrollSimulation(employee_id=employee_id, kind=r.kind, reference_date=ref_date,
                          result=json.dumps(payload, ensure_ascii=False), user_id=user_id)
    session.add(s)
    session.flush()
    return s
