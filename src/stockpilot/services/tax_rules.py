"""Tabelas legais VERSIONADAS, com origem, base legal, vigência e data de conferência.

Nada aqui é "atualizado automaticamente": novas versões entram por `add_table_version`/`set_parameter`
(tela Tributário > Tabelas), sempre informando a fonte. Valores abaixo foram conferidos em 01/11/2026
em fontes públicas (ver `source`); a conferência final de cada tabela é do contador responsável.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal as D
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..domain.errors import MissingRuleError, ValidationError
from ..models import TaxBracket, TaxParameter, TaxTable

VERIFIED = date(2026, 11, 1)

SIMPLES_I = [  # LC 123/2006, Anexo I (Comércio), redação da LC 155/2016
    (D("180000"), D("4"), D("0")), (D("360000"), D("7.3"), D("5940")), (D("720000"), D("9.5"), D("13860")),
    (D("1800000"), D("10.7"), D("22500")), (D("3600000"), D("14.3"), D("87300")), (D("4800000"), D("19"), D("378000")),
]
INSS_2026 = [  # Portaria Interministerial MPS/MF nº 13/2026
    (D("1621.00"), D("7.5"), D("0")), (D("2902.84"), D("9"), D("0")),
    (D("4354.27"), D("12"), D("0")), (D("8475.55"), D("14"), D("0")),
]
IRRF_2026 = [  # tabela mensal 2026 (Lei 15.191/2025) — a redução da Lei 15.270/2025 é aplicada à parte
    (D("2428.80"), D("0"), D("0")), (D("2826.65"), D("7.5"), D("182.16")), (D("3751.05"), D("15"), D("394.16")),
    (D("4664.68"), D("22.5"), D("675.49")), (None, D("27.5"), D("908.73")),
]

SRC_SIMPLES = ("LC 123/2006 Anexo I (LC 155/2016). Conferido em e-auditoria.com.br, valorfinal.com.br, "
               "razonet.com.br e agilize.com.br; confirmar em planalto.gov.br")
SRC_INSS = "Portaria Interministerial MPS/MF nº 13/2026. Conferido em triviumcontabil.com.br e planilhadefluxo.com.br"
SRC_IRRF = "Receita Federal / Lei 15.191/2025 e 15.270/2025. Conferido em valorfinal.com.br/tabela-irrf-2026 e caltrab.com"

PARAMS = [
    ("salario_minimo", "1621.00", date(2026, 1, 1), date(2026, 12, 31), "Decreto 12.797/2025 (R$ 1.621,00)"),
    ("irrf_dependent_deduction", "189.59", date(2026, 1, 1), date(2026, 12, 31), SRC_IRRF),
    ("irrf_simplified_discount", "607.20", date(2026, 1, 1), date(2026, 12, 31), SRC_IRRF),
    ("irrf_reduction_full_until", "5000.00", date(2026, 1, 1), date(2026, 12, 31), "Lei 15.270/2025; " + SRC_IRRF),
    ("irrf_reduction_until", "7350.00", date(2026, 1, 1), date(2026, 12, 31), "Lei 15.270/2025; " + SRC_IRRF),
    ("irrf_reduction_a", "978.62", date(2026, 1, 1), date(2026, 12, 31), "Lei 15.270/2025; " + SRC_IRRF),
    ("irrf_reduction_b", "0.133145", date(2026, 1, 1), date(2026, 12, 31), "Lei 15.270/2025; " + SRC_IRRF),
    ("mei_annual_limit", "81000.00", date(2019, 1, 1), None, "LC 123/2006 (R$ 81.000/ano; R$ 6.750 por mês de atividade no 1º ano)"),
    ("mei_monthly_limit", "6750.00", date(2019, 1, 1), None, "Limite proporcional no ano de abertura: R$ 6.750 × meses"),
    ("mei_inss_percent", "5", date(2019, 1, 1), None, "DAS-MEI: 5% do salário mínimo (INSS)"),
    ("mei_icms", "1.00", date(2019, 1, 1), None, "DAS-MEI: R$ 1,00 de ICMS (comércio/indústria)"),
    ("mei_iss", "5.00", date(2019, 1, 1), None, "DAS-MEI: R$ 5,00 de ISS (serviços)"),
    ("simples_annual_limit", "4800000.00", date(2018, 1, 1), None, "LC 123/2006 art. 3º"),
    ("simples_icms_sublimit", "3600000.00", date(2018, 1, 1), None, "LC 123/2006 art. 13-A (sublimite; estados podem adotar menor)"),
]


def seed_tax_rules(session: Session) -> None:
    def ensure(code, desc, vf, vt, basis, src, rows, notes=None):
        if session.scalar(select(TaxTable.id).where(TaxTable.code == code, TaxTable.valid_from == vf)):
            return
        t = TaxTable(code=code, description=desc, valid_from=vf, valid_to=vt, legal_basis=basis, source=src,
                     verified_at=VERIFIED, notes=notes)
        for i, (up, rate, ded) in enumerate(rows):
            t.brackets.append(TaxBracket(position=i, upper_limit=up, rate_percent=rate, deduction=ded))
        session.add(t)

    ensure("SIMPLES_ANEXO_I", "Simples Nacional — Anexo I (Comércio)", date(2018, 1, 1), None,
           "LC 123/2006, Anexo I, redação LC 155/2016", SRC_SIMPLES, SIMPLES_I,
           "Os demais anexos (II a V) não estão carregados: cadastre-os em Tributário > Tabelas.")
    ensure("INSS_EMPREGADO", "INSS — empregado, doméstico e avulso (progressiva)", date(2026, 1, 1), date(2026, 12, 31),
           "Portaria Interministerial MPS/MF nº 13/2026", SRC_INSS, INSS_2026,
           "Cada alíquota incide só sobre a parcela dentro da faixa; teto = limite da última faixa.")
    ensure("IRRF_MENSAL", "IRRF — tabela progressiva mensal 2026", date(2026, 1, 1), date(2026, 12, 31),
           "Lei 15.191/2025; Lei 15.270/2025", SRC_IRRF, IRRF_2026, "Fórmula: base × alíquota − parcela a deduzir.")
    have = {(p.key, p.valid_from) for p in session.scalars(select(TaxParameter))}
    for key, val, vf, vt, src in PARAMS:
        if (key, vf) not in have:
            session.add(TaxParameter(key=key, value=val, valid_from=vf, valid_to=vt, source=src, verified_at=VERIFIED))
    session.flush()


def get_table(session: Session, code: str, ref: date) -> TaxTable:
    t = session.scalar(select(TaxTable).options(joinedload(TaxTable.brackets)).where(
        TaxTable.code == code, TaxTable.valid_from <= ref,
        (TaxTable.valid_to.is_(None)) | (TaxTable.valid_to >= ref)).order_by(TaxTable.valid_from.desc()).limit(1))
    if t is None:
        raise MissingRuleError(f"Não há tabela '{code}' cadastrada para {ref.strftime('%d/%m/%Y')}. "
                               "Cadastre a tabela vigente em Tributário > Tabelas (informando a fonte).")
    return t


def get_param(session: Session, key: str, ref: date) -> D:
    p = session.scalar(select(TaxParameter).where(
        TaxParameter.key == key, TaxParameter.valid_from <= ref,
        (TaxParameter.valid_to.is_(None)) | (TaxParameter.valid_to >= ref)).order_by(TaxParameter.valid_from.desc()).limit(1))
    if p is None:
        raise MissingRuleError(f"Parâmetro legal '{key}' não cadastrado para {ref.strftime('%d/%m/%Y')}.")
    return D(p.value)


def list_tables(session: Session) -> list[TaxTable]:
    return list(session.scalars(select(TaxTable).options(joinedload(TaxTable.brackets))
                                .order_by(TaxTable.code, TaxTable.valid_from.desc())).unique())


def list_parameters(session: Session) -> list[TaxParameter]:
    return list(session.scalars(select(TaxParameter).order_by(TaxParameter.key, TaxParameter.valid_from.desc())))


def add_table_version(session: Session, *, code: str, description: str, valid_from: date, legal_basis: str,
                      source: str, rows: list[tuple[D | None, D, D]], valid_to: date | None = None) -> TaxTable:
    if not (source or "").strip() or not (legal_basis or "").strip():
        raise ValidationError("Informe a base legal e a fonte onde a tabela foi conferida.")
    if not rows:
        raise ValidationError("Informe ao menos uma faixa.")
    last = None
    for up, rate, ded in rows:
        if up is not None and last is not None and up <= last:
            raise ValidationError("Os limites das faixas devem ser crescentes.")
        if rate < 0 or rate > 100 or ded < 0:
            raise ValidationError("Alíquota ou parcela a deduzir inválida.")
        last = up if up is not None else last
    if rows[-1][0] is not None and code.startswith("IRRF"):
        raise ValidationError("A última faixa do IRRF deve ser sem teto.")
    if session.scalar(select(TaxTable.id).where(TaxTable.code == code, TaxTable.valid_from == valid_from)):
        raise ValidationError("Já existe uma versão dessa tabela com o mesmo início de vigência.")
    prev = session.scalar(select(TaxTable).where(TaxTable.code == code, TaxTable.valid_to.is_(None),
                                                 TaxTable.valid_from < valid_from))
    if prev:
        prev.valid_to = valid_from - timedelta(days=1)  # encerra a versão anterior; o histórico é mantido
    t = TaxTable(code=code, description=description, valid_from=valid_from, valid_to=valid_to,
                 legal_basis=legal_basis.strip(), source=source.strip(), verified_at=date.today())
    for i, (up, rate, ded) in enumerate(rows):
        t.brackets.append(TaxBracket(position=i, upper_limit=up, rate_percent=rate, deduction=ded))
    session.add(t)
    session.flush()
    return t


def set_parameter(session: Session, key: str, value: str, valid_from: date, source: str,
                  valid_to: date | None = None) -> TaxParameter:
    if not (source or "").strip():
        raise ValidationError("Informe a fonte do parâmetro.")
    try:
        D(value)
    except Exception:
        raise ValidationError("Valor inválido.")
    prev = session.scalar(select(TaxParameter).where(TaxParameter.key == key, TaxParameter.valid_to.is_(None),
                                                      TaxParameter.valid_from < valid_from))
    if prev:
        prev.valid_to = valid_from - timedelta(days=1)
    p = session.scalar(select(TaxParameter).where(TaxParameter.key == key, TaxParameter.valid_from == valid_from))
    if p is None:
        p = TaxParameter(key=key, value=value, valid_from=valid_from, valid_to=valid_to, source=source.strip(),
                         verified_at=date.today())
        session.add(p)
    else:
        p.value, p.source, p.valid_to, p.verified_at = value, source.strip(), valid_to, date.today()
    session.flush()
    return p
