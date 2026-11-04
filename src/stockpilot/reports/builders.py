"""Construção dos 15 relatórios. Cada função devolve um ReportData; nenhuma escreve arquivo."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..domain.enums import AssessmentStatus, BillStatus, MovementType, SaleStatus
from ..domain.formatting import format_date
from ..models import (Product, PurchaseItem, Sale, SaleItem, SaleReturn, StockMovement, TaxAssessment)
from ..services import (company_service, finance_service as fin, payroll_service as pr, product_service,
                        purchase_service, sales_service, stock_service)
from .model import ReportData

Z = Decimal("0")


def _period(a: date | None, b: date | None) -> str:
    if a and b:
        return f"{format_date(a)} a {format_date(b)}"
    if a:
        return f"A partir de {format_date(a)}"
    if b:
        return f"Até {format_date(b)}"
    return "Todo o período"


def _base(s: Session, key: str, title: str, period: str, criteria: list[str], columns, notes=None) -> ReportData:
    c = company_service.get_company(s)
    return ReportData(key, title, period, criteria, columns, notes=notes or [], company=(c.trade_name or c.legal_name) if c else "")


def _day_bounds(a: date | None, b: date | None):
    return (datetime.combine(a, time.min) if a else None, datetime.combine(b, time.max) if b else None)


# ---------------------------------------------------------------- estoque
def estoque_atual(s: Session, category_id: int | None = None, include_inactive: bool = False) -> ReportData:
    cat_name = "Todas"
    prods = product_service.search_products(s, category_id=category_id, only_active=not include_inactive)
    if category_id and prods:
        cat_name = prods[0].category.name if prods[0].category else "Todas"
    r = _base(s, "estoque_atual", "Estoque atual", f"Posição em {format_date(date.today())}",
              [f"Categoria: {cat_name}", "Produtos inativos: " + ("incluídos" if include_inactive else "excluídos"),
               "Valor do estoque = quantidade × custo médio ponderado (CMP)"],
              [("Código", "text"), ("Produto", "text"), ("Categoria", "text"), ("Un.", "text"), ("Estoque", "qty"),
               ("Custo médio", "money"), ("Valor em estoque", "money"), ("Preço venda", "money")])
    tot = Z
    for p in prods:
        v = p.quantity_on_hand * p.cost_price
        tot += v
        r.rows.append([p.internal_code, p.name, p.category.name if p.category else "", p.unit.value, p.quantity_on_hand,
                       p.cost_price, v, p.sale_price])
    r.totals = ["TOTAL", None, None, None, None, None, tot, None]
    return r


def estoque_baixo(s: Session) -> ReportData:
    r = _base(s, "estoque_baixo", "Estoque baixo", f"Posição em {format_date(date.today())}",
              ["Produtos ativos com estoque mínimo definido e saldo ≤ mínimo"],
              [("Código", "text"), ("Produto", "text"), ("Estoque", "qty"), ("Mínimo", "qty"), ("Sugestão de reposição", "qty")])
    for p in product_service.search_products(s, low_stock_only=True, order_by="quantity"):
        r.rows.append([p.internal_code, p.name, p.quantity_on_hand, p.min_stock, max(Z, p.min_stock * 2 - p.quantity_on_hand)])
    r.notes.append("Sugestão de reposição = (2 × mínimo) − saldo atual. É apenas um ponto de partida; ajuste ao seu giro de vendas.")
    return r


def movimentacoes(s: Session, start: date, end: date, mtype: MovementType | None = None) -> ReportData:
    a, b = _day_bounds(start, end)
    movs = stock_service.history(s, start=a, end=b, types=[mtype] if mtype else None, limit=50000)
    r = _base(s, "movimentacoes", "Movimentações de estoque", _period(start, end),
              [f"Tipo: {mtype.label if mtype else 'Todos'}", "Datas em horário local"],
              [("Data/hora", "text"), ("Produto", "text"), ("Tipo", "text"), ("Quantidade", "qty"), ("Saldo após", "qty"),
               ("Custo unit.", "money"), ("Origem", "text"), ("Motivo", "text"), ("Usuário", "text")])
    from ..domain.formatting import format_datetime_local
    for m in reversed(movs):
        r.rows.append([format_datetime_local(m.created_at), f"{m.product.internal_code} — {m.product.name}", m.movement_type.label,
                       m.quantity_delta, m.balance_after, m.unit_cost, m.origin.label, m.reason or "", m.user.full_name if m.user else ""])
    return r


# ---------------------------------------------------------------- compras / vendas
def compras(s: Session, start: date, end: date, supplier_id: int | None = None) -> ReportData:
    r = _base(s, "compras", "Compras por período", _period(start, end),
              ["Compras canceladas aparecem na lista mas NÃO entram no total", "Data = data da compra"],
              [("Número", "text"), ("Data", "date"), ("Fornecedor", "text"), ("Itens", "money"), ("Desconto", "money"),
               ("Despesas", "money"), ("Total", "money"), ("Pagamento", "text"), ("Situação", "text")])
    tot = Z
    for p in purchase_service.list_purchases(s, start=start, end=end, supplier_id=supplier_id):
        if p.status.value == "CONFIRMADA":
            tot += p.total
        r.rows.append([p.number, p.issue_date, p.supplier.name, p.subtotal, p.discount, p.extra_expenses, p.total,
                       p.payment_method.label + (f" {p.installments}x" if p.installments > 1 else ""), p.status.label])
    r.totals = ["TOTAL CONFIRMADAS", None, None, None, None, None, tot, None, None]
    r.notes.append("Rascunhos ainda não atualizaram o estoque e também não entram no total.")
    return r


def vendas(s: Session, start: date, end: date) -> ReportData:
    sales = sales_service.list_sales(s, start=start, end=end, limit=100000)
    r = _base(s, "vendas", "Vendas por período", _period(start, end),
              ["Canceladas listadas mas fora dos totais", "Total = valor da venda; devoluções mostradas à parte"],
              [("Número", "text"), ("Data", "date"), ("Cliente", "text"), ("Subtotal", "money"), ("Desconto", "money"),
               ("Total", "money"), ("Custo (CMV)", "money"), ("Pagamento", "text"), ("Situação", "text")])
    tot = disc = cogs = Z
    for x in reversed(sales):
        ok = x.status == SaleStatus.CONCLUIDA
        if ok:
            tot, disc, cogs = tot + x.total, disc + x.discount, cogs + x.cogs
        r.rows.append([x.number, x.sale_date, x.customer_name or "", x.subtotal, x.discount, x.total, x.cogs,
                       ", ".join(sorted({p.method.label for p in x.payments})), x.status.label])
    r.totals = ["TOTAL CONCLUÍDAS", None, None, None, disc, tot, cogs, None, None]
    ret = sum((x.amount for x in s.scalars(select(SaleReturn).where(SaleReturn.return_date >= start, SaleReturn.return_date <= end))), Z)
    r.notes.append(f"Devoluções no período: R$ {ret:,.2f} (abatem a receita líquida; veja o Resultado financeiro).".replace(",", "X").replace(".", ",").replace("X", "."))
    return r


def _sold_by_product(s: Session, start: date, end: date):
    items = s.scalars(select(SaleItem).join(Sale).options(joinedload(SaleItem.product)).where(
        Sale.status == SaleStatus.CONCLUIDA, Sale.sale_date >= start, Sale.sale_date <= end)).unique().all()
    returned = defaultdict(lambda: (Z, Z))
    for rt in s.scalars(select(SaleReturn).where(SaleReturn.sale_id.in_({i.sale_id for i in items}) if items else False)):
        q, v = returned[rt.sale_item_id]
        returned[rt.sale_item_id] = (q + rt.quantity, v + rt.amount)
    agg = {}
    for it in items:
        rq, rv = returned[it.id]
        d = agg.setdefault(it.product_id, dict(p=it.product, qty=Z, rev=Z, cost=Z))
        d["qty"] += it.quantity - rq
        d["rev"] += it.total - rv
        d["cost"] += (it.quantity - rq) * it.unit_cost
    return agg


def mais_vendidos(s: Session, start: date, end: date, limit: int = 50) -> ReportData:
    agg = sorted(_sold_by_product(s, start, end).values(), key=lambda d: (d["qty"], d["rev"]), reverse=True)[:limit]
    r = _base(s, "mais_vendidos", "Produtos mais vendidos", _period(start, end),
              [f"Top {limit} por quantidade vendida", "Quantidade e receita já descontam devoluções", "Somente vendas concluídas"],
              [("#", "int"), ("Produto", "text"), ("Quantidade", "qty"), ("Receita", "money"), ("Custo (CMV)", "money"), ("Lucro bruto", "money")])
    for i, d in enumerate(agg, 1):
        r.rows.append([i, f"{d['p'].internal_code} — {d['p'].name}", d["qty"], d["rev"], d["cost"], d["rev"] - d["cost"]])
    return r


def sem_movimentacao(s: Session, days: int = 90) -> ReportData:
    r = _base(s, "sem_movimentacao", "Produtos sem movimentação", f"Últimos {days} dias até {format_date(date.today())}",
              [f"Produtos ativos sem nenhuma movimentação de estoque há {days} dias ou mais"],
              [("Código", "text"), ("Produto", "text"), ("Estoque", "qty"), ("Custo médio", "money"), ("Capital parado", "money")])
    tot = Z
    for p in product_service.products_without_movement(s, days):
        v = p.quantity_on_hand * p.cost_price
        tot += v
        r.rows.append([p.internal_code, p.name, p.quantity_on_hand, p.cost_price, v])
    r.totals = ["TOTAL", None, None, None, tot]
    return r


def giro_estoque(s: Session, days: int = 30) -> ReportData:
    from ..services import stock_analytics as sa
    r = _base(s, "giro_estoque", "Giro e reposição de estoque", f"Últimos {days} dias até {format_date(date.today())}",
              [sa.CRITERIOS], [("Código", "text"), ("Produto", "text"), ("Saldo", "qty"), ("Mínimo", "qty"),
                               ("Saídas no período", "qty"), ("Média/dia", "qty"), ("Cobertura (dias)", "qty"),
                               ("Entradas no período", "qty"), ("Reposição sugerida", "qty")])
    sug = {x.item.product_id: x.suggested for x in sa.replenishment(s, days)}
    items = sorted(sa.turnover(s, days), key=lambda t: (-t.exits, t.name.lower()))  # mais movimentados primeiro
    for t in items:
        r.rows.append([t.code, t.name, t.quantity, t.min_stock, t.exits, t.avg_daily, t.cover_days,
                       t.entries, sug.get(t.product_id)])
    r.notes.append("Cobertura vazia = sem saídas no período. Reposição vazia = não precisa repor pelos critérios.")
    return r


def margem(s: Session) -> ReportData:
    r = _base(s, "margem", "Margem estimada por produto", f"Posição em {format_date(date.today())}",
              ["Margem = (preço de venda − custo médio) ÷ preço de venda", "Estimativa: não considera impostos, taxas de cartão nem despesas"],
              [("Código", "text"), ("Produto", "text"), ("Custo médio", "money"), ("Preço venda", "money"), ("Margem R$", "money"), ("Margem %", "pct")])
    for p in product_service.search_products(s, order_by="name"):
        m = p.margin_percent
        r.rows.append([p.internal_code, p.name, p.cost_price, p.sale_price, p.sale_price - p.cost_price, m])
    r.notes.append("Produtos sem custo informado aparecem com margem sem sentido — complete o custo no cadastro.")
    return r


# ---------------------------------------------------------------- financeiro
def fluxo_caixa(s: Session, start: date, end: date, account_id: int | None = None) -> ReportData:
    opening, rows = fin.cash_flow(s, start, end, account_id)
    acc = next((a.name for a in fin.list_accounts(s, only_active=False) if a.id == account_id), "Todas as contas")
    r = _base(s, "fluxo_caixa", "Fluxo de caixa", _period(start, end),
              [f"Conta: {acc}", "Regime de caixa: apenas valores efetivamente lançados", "Estornos entram como lançamentos próprios"],
              [("Dia", "date"), ("Entradas", "money"), ("Saídas", "money"), ("Saldo do dia", "money")])
    for x in rows:
        if x.inflow or x.outflow:
            r.rows.append([x.day, x.inflow, x.outflow, x.balance])
    tin, tout = sum((x.inflow for x in rows), Z), sum((x.outflow for x in rows), Z)
    r.totals = ["TOTAL", tin, tout, opening + tin - tout]
    r.notes.append(f"Saldo inicial do período: R$ {opening:,.2f}; saldo final: R$ {opening + tin - tout:,.2f}.".replace(",", "X").replace(".", ",").replace("X", "."))
    return r


def _bills(s: Session, kind: str, status: BillStatus | None, start: date | None, end: date | None) -> ReportData:
    nm = "pagar" if kind == "P" else "receber"
    r = _base(s, f"contas_{nm}", f"Contas a {nm}", _period(start, end),
              [f"Situação: {status.label if status else 'Todas'}", "Período filtra o vencimento", "Vencida = em aberto com vencimento anterior a hoje"],
              [("Vencimento", "date"), ("Descrição", "text"), ("Parcela", "text"), ("Valor", "money"), ("Pago", "money"), ("Em aberto", "money"), ("Situação", "text")])
    tot = opn = Z
    for b in fin.list_bills(s, kind, status=status, start=start, end=end):
        late = b.status == BillStatus.ABERTA and b.due_date < date.today()
        tot, opn = tot + b.amount, opn + (b.open_amount if b.status == BillStatus.ABERTA else Z)
        who = getattr(b, "customer_name", None) or ""
        r.rows.append([b.due_date, b.description + (f" — {who}" if who else ""), f"{b.installment_no}/{b.installment_total}", b.amount,
                       b.paid_amount, b.open_amount, "Vencida" if late else b.status.label])
    r.totals = ["TOTAL", None, None, tot, None, opn, None]
    return r


def contas_pagar(s, status=None, start=None, end=None):
    return _bills(s, "P", status, start, end)


def contas_receber(s, status=None, start=None, end=None):
    return _bills(s, "R", status, start, end)


def resultado(s: Session, start: date, end: date) -> ReportData:
    x = fin.result_summary(s, start, end)
    r = _base(s, "resultado", "Resultado financeiro (estimado)", _period(start, end), list(x.assumptions), [("Indicador", "text"), ("Valor", "money")])
    r.rows = [["Faturamento (vendas concluídas)", x.gross_revenue], ["(−) Devoluções", x.returns], ["Receita líquida", x.net_revenue],
              ["(−) CMV", x.cogs], ["Lucro bruto", x.gross_profit], ["(+) Outras receitas", x.other_income], ["(−) Despesas pagas", x.expenses],
              ["RESULTADO OPERACIONAL — ESTIMADO", x.operating_result], ["Recebido de vendas (caixa)", x.receipts],
              ["Compras de mercadoria pagas", x.merchandise_paid], ["Saldo em caixa/contas na data final", x.cash_balance],
              ["Contas a receber em aberto (hoje)", x.receivable_open], ["Contas a pagar em aberto (hoje)", x.payable_open]]
    cats = [c for c in fin.category_totals(s, start, end)]
    if cats:
        r.rows.append(["", None])
        r.rows.append(["— Totais por categoria (caixa) —", None])
        for name, group, val in cats:
            r.rows.append([f"{name} ({group.label})", val])
    return r


# ---------------------------------------------------------------- tributário / folha
def estimativas_tributarias(s: Session) -> ReportData:
    r = _base(s, "estimativas_tributarias", "Estimativas tributárias", f"Histórico até {format_date(date.today())}",
              ["ESTIMATIVAS — não substituem PGDAS-D/PGMEI nem o contador", "Mostra a última estimativa de cada competência/regime",
               "Situação INCOMPLETA = faltavam dados (veja a coluna 'Dados faltantes')"],
              [("Competência", "text"), ("Tributo", "text"), ("Faturamento do mês", "money"), ("RBT12", "money"), ("Alíq. efetiva %", "text"),
               ("Valor estimado", "money"), ("Vencimento", "date"), ("Situação", "text"), ("Pago", "money"), ("Dados faltantes", "text")])
    for a in s.scalars(select(TaxAssessment).where(TaxAssessment.superseded.is_(False)).order_by(TaxAssessment.competence.desc())):
        w = json.loads(a.warnings or "{}")
        r.rows.append([f"{a.competence[5:]}/{a.competence[:4]}", a.description, a.revenue_month, a.rbt12,
                       f"{a.effective_rate:.4f}".replace(".", ",") if a.effective_rate is not None else "", a.amount, a.due_date,
                       a.status.label, a.paid_amount, " | ".join(w.get("faltando", []))])
    r.notes.append("Lucro Presumido e Lucro Real: o sistema não calcula tributos desses regimes; use os relatórios de vendas e resultado para o contador.")
    return r


def folha(s: Session, user_id: int, competence: str | None = None) -> ReportData:
    slips = pr.payroll_history(s, user_id, competence)
    r = _base(s, "folha", "Folha de pagamento (estimada)", f"Competência {competence[5:]}/{competence[:4]}" if competence else "Todas as competências",
              ["SIMULAÇÃO ESTIMADA — não é folha oficial", "INSS e IRRF pelas tabelas vigentes cadastradas (ver Tributário > Tabelas legais)",
               "Última simulação salva de cada funcionário/competência"],
              [("Competência", "text"), ("Funcionário", "text"), ("Bruto", "money"), ("INSS", "money"), ("IRRF", "money"), ("Outros desc.", "money"),
               ("Líquido", "money"), ("FGTS", "money"), ("Obs.", "text")])
    tot = [Z] * 6
    for x in slips:
        vals = [x.gross, x.inss, x.irrf, x.other_deductions, x.net, x.fgts]
        tot = [a + b for a, b in zip(tot, vals)]
        r.rows.append([f"{x.competence[5:]}/{x.competence[:4]}", x.employee.name] + vals + ["INCOMPLETA" if json.loads(x.missing) else "Estimativa"])
    r.totals = ["TOTAL", None] + tot + [None]
    return r


def custos_funcionarios(s: Session, user_id: int, competence: str | None = None) -> ReportData:
    slips = pr.payroll_history(s, user_id, competence)
    r = _base(s, "custos_funcionarios", "Custos de funcionários (estimado)", f"Competência {competence[5:]}/{competence[:4]}" if competence else "Todas as competências",
              ["Custo total = bruto + FGTS + encargos patronais + benefícios", "Custo 'não calculado' = faltam dados (RAT/terceiros, regime etc.); nunca é preenchido com chute"],
              [("Competência", "text"), ("Funcionário", "text"), ("Bruto", "money"), ("FGTS", "money"), ("Encargos (FGTS+patronal)", "money"),
               ("Benefícios", "money"), ("Custo total", "money"), ("Situação", "text")])
    tot = Z
    inc = False
    for x in slips:
        if x.total_cost is not None:
            tot += x.total_cost
        else:
            inc = True
        r.rows.append([f"{x.competence[5:]}/{x.competence[:4]}", x.employee.name, x.gross, x.fgts, x.employer_charges, x.benefits_cost,
                       x.total_cost, "calculado" if x.total_cost is not None else "NÃO CALCULADO (faltam dados)"])
    r.totals = ["TOTAL (apenas calculados)", None, None, None, None, None, tot, None]
    if inc:
        r.notes.append("Há funcionários com custo não calculado: o total acima está SUBESTIMADO.")
    return r
