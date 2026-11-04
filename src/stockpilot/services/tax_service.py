"""Apuração tributária ESTIMADA (MEI e Simples Nacional — Anexo I).

Regras de honestidade deste módulo:
* todo resultado é ESTIMATIVA; se faltar dado, o status é INCOMPLETA e a lista do que falta acompanha o valor;
* tabelas vêm de `tax_rules` (dados versionados com fonte); sem tabela vigente => MissingRuleError (nunca um chute);
* não emite guia, não transmite PGDAS-D/DASN; o valor oficial é o do PGDAS-D / PGMEI.
* Lucro Presumido/Real: o sistema guarda dados e faz relatórios, mas NÃO calcula tributos desses regimes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal as D

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain.enums import AssessmentStatus, SaleStatus, TaxRegime
from ..domain.errors import MissingRuleError, ValidationError
from ..models import Company, RevenueEntry, Sale, SaleReturn, TaxAssessment, TaxObligation
from .tax_rules import get_param, get_table

Z = D("0")
ACTIVITIES = ("COMERCIO", "SERVICOS")


def q2(v: D) -> D:
    return v.quantize(D("0.01"), rounding=ROUND_HALF_UP)


def parse_comp(c: str) -> tuple[int, int]:
    try:
        y, m = c.split("-")
        y, m = int(y), int(m)
        assert 1 <= m <= 12 and 2000 <= y <= 2100
        return y, m
    except Exception:
        raise ValidationError("Competência inválida. Use AAAA-MM.")


def comp_str(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}"


def add_comp(c: str, n: int) -> str:
    y, m = parse_comp(c)
    i = y * 12 + (m - 1) + n
    return comp_str(i // 12, i % 12 + 1)


def month_bounds(c: str) -> tuple[date, date]:
    y, m = parse_comp(c)
    start = date(y, m, 1)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, date(ny, nm, 1).fromordinal(date(ny, nm, 1).toordinal() - 1)


def das_due_date(c: str) -> date:
    """Dia 20 do mês seguinte. Regra de dia útil não é aplicada (fontes divergem): o aviso manda conferir."""
    y, m = parse_comp(add_comp(c, 1))
    return date(y, m, 20)


# ---------------------------------------------------------------- faturamento
@dataclass
class MonthRevenue:
    competence: str
    amount: D
    source: str          # 'informado' | 'vendas' | 'sem dados'
    has_data: bool


def month_revenue(session: Session, competence: str, activity: str = "COMERCIO") -> MonthRevenue:
    entry = session.scalar(select(RevenueEntry).where(RevenueEntry.competence == competence,
                                                      RevenueEntry.activity == activity))
    if entry is not None:
        return MonthRevenue(competence, entry.amount, "informado", True)
    if activity != "COMERCIO":
        return MonthRevenue(competence, Z, "sem dados", False)
    start, end = month_bounds(competence)
    n, tot = session.execute(select(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0)).where(
        Sale.status == SaleStatus.CONCLUIDA, Sale.sale_date >= start, Sale.sale_date <= end)).one()
    tot = D(tot)
    ret = sum((r.amount for r in session.scalars(select(SaleReturn).where(
        SaleReturn.return_date >= start, SaleReturn.return_date <= end))), Z)
    if n == 0:
        return MonthRevenue(competence, Z, "sem dados", False)
    return MonthRevenue(competence, max(Z, tot - ret), "vendas", True)


def set_revenue(session: Session, competence: str, activity: str, amount: D, notes: str | None = None,
                user_id: int | None = None) -> RevenueEntry:
    parse_comp(competence)
    if activity not in ACTIVITIES:
        raise ValidationError("Atividade inválida.")
    if not isinstance(amount, D) or amount < 0:
        raise ValidationError("Informe um faturamento válido (zero ou maior).")
    e = session.scalar(select(RevenueEntry).where(RevenueEntry.competence == competence,
                                                  RevenueEntry.activity == activity))
    if e is None:
        e = RevenueEntry(competence=competence, activity=activity, amount=q2(amount), notes=notes, user_id=user_id)
        session.add(e)
    else:
        e.amount, e.notes, e.user_id = q2(amount), notes, user_id
    session.flush()
    return e


# ---------------------------------------------------------------- RBT12
@dataclass
class Rbt12Result:
    value: D
    method: str
    missing_months: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def months_between(a: date, b_comp: str) -> int:
    """Meses completos entre o mês de início (0 = mesmo mês) e a competência."""
    y, m = parse_comp(b_comp)
    return (y * 12 + m) - (a.year * 12 + a.month)


def compute_rbt12(session: Session, competence: str, start_date: date | None, activity: str = "COMERCIO") -> Rbt12Result:
    """Res. CGSN 140, art. 22: 1º mês = receita×12; meses 2–12 = média dos anteriores×12; depois soma dos 12 anteriores."""
    cur = month_revenue(session, competence, activity)
    if start_date is None:
        prev = [month_revenue(session, add_comp(competence, -i), activity) for i in range(1, 13)]
        miss = [p.competence for p in prev if not p.has_data]
        return Rbt12Result(sum((p.amount for p in prev), Z), "soma dos 12 meses anteriores (início da atividade não cadastrado)",
                           miss, ["Data de início da atividade não cadastrada: não foi possível aplicar a regra de início de atividade."])
    n = months_between(start_date, competence)
    if n < 0:
        raise ValidationError("A competência é anterior ao início da atividade da empresa.")
    if n == 0:
        return Rbt12Result(cur.amount * 12, "1º mês de atividade: receita do mês × 12", [], [])
    if n < 12:
        prev = [month_revenue(session, add_comp(competence, -i), activity) for i in range(1, n + 1)]
        miss = [p.competence for p in prev if not p.has_data]
        avg = sum((p.amount for p in prev), Z) / n
        return Rbt12Result(q2(avg * 12), f"média dos {n} meses anteriores × 12", miss, [])
    prev = [month_revenue(session, add_comp(competence, -i), activity) for i in range(1, 13)]
    miss = [p.competence for p in prev if not p.has_data]
    return Rbt12Result(sum((p.amount for p in prev), Z), "soma dos 12 meses anteriores", miss, [])


# ---------------------------------------------------------------- resultado
@dataclass
class AssessmentResult:
    competence: str
    regime: TaxRegime
    description: str
    revenue_month: D
    revenue_source: str
    amount: D
    status: AssessmentStatus
    due_date: date | None
    table_id: int | None = None
    rbt12: D | None = None
    nominal_rate: D | None = None
    deduction: D | None = None
    effective_rate: D | None = None
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    breakdown: list[tuple[str, D]] = field(default_factory=list)
    label: str = "ESTIMATIVA — não substitui o PGDAS-D/PGMEI nem o contador"


def _bracket(table, rbt12: D):
    for b in table.brackets:
        if b.upper_limit is None or rbt12 <= b.upper_limit:
            return b
    return None


def assess_simples(session: Session, competence: str, company: Company) -> AssessmentResult:
    y, _ = parse_comp(competence)
    ref = month_bounds(competence)[0]
    table = get_table(session, "SIMPLES_ANEXO_I", ref)
    rev = month_revenue(session, competence)
    r = compute_rbt12(session, competence, company.activity_start_date)
    warnings = ["Estimativa para atividade de COMÉRCIO (Anexo I). Receitas de serviços/indústria e outros anexos não são calculadas.",
                "Não considera ICMS-ST, monofásico (PIS/COFINS) nem outras segregações de receita que reduzem o DAS: o valor tende a ser MAIOR que o do PGDAS-D se você vende esses produtos.",
                "Vencimento padrão: dia 20 do mês seguinte. Confira no PGDAS-D se há antecipação/prorrogação por dia não útil."]
    missing: list[str] = []
    warnings += r.notes
    if r.missing_months:
        lst = ", ".join(f"{m[5:]}/{m[:4]}" for m in sorted(r.missing_months))
        missing.append(f"Faturamento sem registro nos meses: {lst}. Informe-os em Tributário > Faturamento (use 0 se não houve venda).")
    if not rev.has_data:
        missing.append(f"Sem vendas nem faturamento informado em {competence[5:]}/{y}.")
    if company.activity_start_date is None:
        missing.append("Data de início da atividade (Empresa).")
    if y >= 2027:
        warnings.append("Competência a partir de 01/01/2027: a Res. CGSN 190/2026 altera regras de cálculo da receita acumulada, "
                        "que NÃO estão implementadas aqui. Não use este valor sem conferência do contador.")
        missing.append("Regras vigentes a partir de 2027 (Res. CGSN 190/2026).")
    amount, eff, nominal, ded = Z, None, None, None
    if r.value <= 0:
        warnings.append("RBT12 igual a zero: a alíquota efetiva não pode ser calculada.")
        missing.append("RBT12 (receita bruta acumulada) maior que zero.")
    else:
        if r.value > D("4800000"):
            warnings.append("RBT12 acima de R$ 4.800.000: acima do limite do Simples Nacional. Procure o contador.")
        else:
            b = _bracket(table, r.value)
            nominal, ded = b.rate_percent, b.deduction
            eff = ((r.value * nominal / 100 - ded) / r.value * 100).quantize(D("0.000001"), rounding=ROUND_HALF_UP)
            amount = q2(rev.amount * eff / 100)
            if r.value > D("3600000"):
                warnings.append("RBT12 acima do sublimite de R$ 3.600.000: o ICMS pode ser recolhido fora do DAS conforme o Estado.")
    status = AssessmentStatus.INCOMPLETA if missing else AssessmentStatus.ESTIMATIVA
    return AssessmentResult(
        competence, TaxRegime.SIMPLES_NACIONAL, "DAS — Simples Nacional, Anexo I (comércio)", rev.amount, rev.source,
        amount, status, das_due_date(competence), table.id, r.value, nominal, ded, eff, warnings, missing,
        [("Faturamento do mês", rev.amount), ("RBT12 (" + r.method + ")", r.value), ("DAS estimado", amount)])


def assess_mei(session: Session, competence: str, company: Company, activity: str = "COMERCIO") -> AssessmentResult:
    """DAS-MEI: valor fixo (5% do salário mínimo + ICMS e/ou ISS). Também confere o limite anual de faturamento."""
    if activity not in ("COMERCIO", "SERVICOS", "AMBOS"):
        raise ValidationError("Atividade MEI inválida.")
    ref = month_bounds(competence)[0]
    y, m = parse_comp(competence)
    sm = get_param(session, "salario_minimo", ref)
    inss = q2(sm * get_param(session, "mei_inss_percent", ref) / 100)
    icms, iss = get_param(session, "mei_icms", ref), get_param(session, "mei_iss", ref)
    extra = {"COMERCIO": icms, "SERVICOS": iss, "AMBOS": icms + iss}[activity]
    amount = inss + extra
    limit = get_param(session, "mei_annual_limit", ref)
    monthly = get_param(session, "mei_monthly_limit", ref)
    warnings = ["Valor fixo do DAS-MEI calculado a partir do salário mínimo vigente. A guia oficial é emitida no PGMEI/Portal do Empreendedor.",
                "Vencimento padrão: dia 20 do mês seguinte. Confira no PGMEI."]
    missing: list[str] = []
    start = company.activity_start_date
    open_year = start is not None and start.year == y
    if start is None:
        missing.append("Data de início da atividade (Empresa) para o limite proporcional do ano de abertura.")
    eff_limit = limit
    if open_year:
        eff_limit = monthly * (13 - start.month)
    ytd = Z
    missing_months: list[str] = []
    first = start.month if open_year else 1
    for mm in range(first, m + 1):
        c = comp_str(y, mm)
        tot = Z
        has = False
        for act in ("COMERCIO", "SERVICOS"):
            mr = month_revenue(session, c, act)
            tot += mr.amount
            has = has or mr.has_data
        ytd += tot
        if not has:
            missing_months.append(c)
    if missing_months:
        missing.append("Faturamento sem registro em: " + ", ".join(f"{c[5:]}/{c[:4]}" for c in missing_months) + ".")
    pct = (ytd / eff_limit * 100) if eff_limit > 0 else Z
    if ytd > eff_limit:
        warnings.append(f"ATENÇÃO: faturamento acumulado no ano (R$ {ytd:,.2f}) acima do limite do MEI (R$ {eff_limit:,.2f}). "
                        "Há risco de desenquadramento e tributação adicional; procure o contador.")
    elif pct >= 80:
        warnings.append(f"Faturamento acumulado em {pct:.1f}% do limite anual do MEI (R$ {eff_limit:,.2f}).")
    rev = month_revenue(session, competence, "COMERCIO")
    return AssessmentResult(
        competence, TaxRegime.MEI, "DAS-MEI (valor fixo)", rev.amount, rev.source, amount,
        AssessmentStatus.INCOMPLETA if missing else AssessmentStatus.ESTIMATIVA, das_due_date(competence), None, None,
        None, None, None, warnings, missing,
        [("INSS (5% do salário mínimo)", inss), ("ICMS/ISS fixo", extra), ("Faturamento acumulado no ano", ytd),
         ("Limite anual aplicável", eff_limit)])


REGIMES_NOT_CALCULATED = ("LUCRO_PRESUMIDO", "LUCRO_REAL")


def assess(session: Session, competence: str, company: Company, mei_activity: str = "COMERCIO") -> AssessmentResult:
    if company.tax_regime is None:
        raise MissingRuleError("Regime tributário não cadastrado em Empresa.")
    if company.tax_regime == TaxRegime.MEI:
        return assess_mei(session, competence, company, mei_activity)
    if company.tax_regime == TaxRegime.SIMPLES_NACIONAL:
        return assess_simples(session, competence, company)
    raise MissingRuleError(
        f"O cálculo de tributos do regime {company.tax_regime.label} não está implementado nesta versão. "
        "O sistema fornece faturamento e relatórios para o seu contador; a apuração deve ser feita por ele.")


def save_assessment(session: Session, res: AssessmentResult, user_id: int | None = None) -> TaxAssessment:
    """Grava a estimativa. A anterior da mesma competência/regime (não paga) fica como substituída — nada é apagado."""
    for old in session.scalars(select(TaxAssessment).where(
            TaxAssessment.competence == res.competence, TaxAssessment.regime == res.regime,
            TaxAssessment.superseded.is_(False))):
        old.superseded = True
    a = TaxAssessment(
        competence=res.competence, regime=res.regime, description=res.description, table_id=res.table_id,
        revenue_month=res.revenue_month, rbt12=res.rbt12, nominal_rate=res.nominal_rate, deduction=res.deduction,
        effective_rate=res.effective_rate, amount=res.amount, status=res.status, due_date=res.due_date,
        warnings=json.dumps({"avisos": res.warnings, "faltando": res.missing}, ensure_ascii=False), user_id=user_id)
    session.add(a)
    if res.due_date:
        name = "DAS-MEI" if res.regime == TaxRegime.MEI else "DAS Simples Nacional"
        ob = session.scalar(select(TaxObligation).where(TaxObligation.name == name, TaxObligation.competence == res.competence))
        if ob is None:
            session.add(TaxObligation(name=name, competence=res.competence, due_date=res.due_date))
        elif ob.status != "CUMPRIDA":
            ob.due_date = res.due_date
    session.flush()
    return a


def mark_paid(session: Session, assessment_id: int, amount: D, paid_date: date, notes: str | None = None) -> TaxAssessment:
    a = session.get(TaxAssessment, assessment_id)
    if a is None:
        raise ValidationError("Apuração não encontrada.")
    if not isinstance(amount, D) or amount <= 0:
        raise ValidationError("Informe o valor pago (conforme a guia oficial).")
    a.paid_amount, a.paid_date, a.payment_notes = q2(amount), paid_date, notes
    name = "DAS-MEI" if a.regime == TaxRegime.MEI else "DAS Simples Nacional"
    ob = session.scalar(select(TaxObligation).where(TaxObligation.name == name, TaxObligation.competence == a.competence))
    if ob:
        ob.status, ob.done_at = "CUMPRIDA", paid_date
    session.flush()
    return a


def list_assessments(session: Session, include_superseded: bool = False) -> list[TaxAssessment]:
    q = select(TaxAssessment).order_by(TaxAssessment.competence.desc(), TaxAssessment.id.desc())
    if not include_superseded:
        q = q.where(TaxAssessment.superseded.is_(False))
    return list(session.scalars(q))


def list_obligations(session: Session, only_pending: bool = False) -> list[TaxObligation]:
    q = select(TaxObligation).order_by(TaxObligation.due_date)
    if only_pending:
        q = q.where(TaxObligation.status == "PENDENTE")
    return list(session.scalars(q))


def assessment_warnings(a: TaxAssessment) -> dict:
    try:
        return json.loads(a.warnings)
    except Exception:
        return {"avisos": [], "faltando": []}
