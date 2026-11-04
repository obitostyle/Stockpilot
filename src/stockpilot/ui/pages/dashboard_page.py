from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...services import dashboard_service, product_service
from ...domain.formatting import format_brl, format_qty
from ..charts import BarChart
from ..delegates import LEVEL_ROLE
from ..common import scroll_body, SortItem, card, make_table, title_block
from .base import Page


class KpiCard:
    """Uma célula de indicador dentro de uma faixa (rótulo, valor, observação)."""

    def __init__(self, label: str, hero: bool = False):
        self.frame = QFrame()
        self.frame.setObjectName("kpiCell")
        lay = QVBoxLayout(self.frame)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(4)
        self.label = QLabel(label)
        self.label.setObjectName("kpiLabel")
        self.value = QLabel("0")
        self.value.setObjectName("kpiValue")
        self.value.setProperty("hero", hero)
        self.note = QLabel("")
        self.note.setObjectName("kpiNote")
        self.note.setWordWrap(True)
        lay.addWidget(self.label)
        lay.addWidget(self.value)
        lay.addWidget(self.note)
        lay.addStretch()

    def set(self, value: str, note: str = "", tone: str = "", note_tone: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)
        for w, t in ((self.value, tone), (self.note, note_tone)):
            if w.property("tone") != t:
                w.setProperty("tone", t)
                w.style().unpolish(w)
                w.style().polish(w)


def kpi_strip(title: str, note: str, cards: list[KpiCard]) -> QWidget:
    """Faixa de indicadores: título discreto + um painel dividido por fios verticais."""
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    head = QHBoxLayout()
    t = QLabel(title)
    t.setObjectName("sectionTitle")
    n = QLabel(note)
    n.setObjectName("sectionNote")
    head.addWidget(t)
    head.addStretch()
    head.addWidget(n)
    v.addLayout(head)
    strip = QFrame()
    strip.setObjectName("strip")
    h = QHBoxLayout(strip)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(0)
    for i, c in enumerate(cards):
        if i:
            div = QFrame()
            div.setObjectName("stripDivider")
            div.setFrameShape(QFrame.VLine)
            h.addWidget(div)
        h.addWidget(c.frame, 1)
    v.addWidget(strip)
    return box


class DashboardPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(scroll_body(self))
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(20)
        root.addWidget(title_block("Painel inicial", "Resumo calculado a partir dos dados reais do seu banco de dados"))

        self.hint = QLabel()
        self.hint.setObjectName("hint")
        self.hint.setWordWrap(True)
        root.addWidget(self.hint)

        self.k_today = KpiCard("Vendas de hoje", hero=True)
        self.k_month = KpiCard("Vendas do mês (líquidas)", hero=True)
        self.k_profit = KpiCard("Lucro bruto do mês")
        self.k_result = KpiCard("Resultado do mês — estimado")
        self.k_cash = KpiCard("Saldo em caixa e contas")
        self.k_rec = KpiCard("A receber")
        self.k_pay = KpiCard("A pagar")
        self.k_value = KpiCard("Valor do estoque (custo médio)")
        root.addWidget(kpi_strip("Vendas e resultado", "Mês atual",
                                 [self.k_today, self.k_month, self.k_profit, self.k_result]))
        root.addWidget(kpi_strip("Posição financeira e estoque", "Hoje",
                                 [self.k_cash, self.k_rec, self.k_pay, self.k_value]))

        mid = QHBoxLayout()
        mid.setSpacing(14)
        c1 = card()
        l1 = QVBoxLayout(c1)
        l1.setContentsMargins(18, 16, 18, 14)
        l1.setSpacing(10)
        t1 = QLabel("Vendas por dia, últimos 30 dias")
        t1.setObjectName("sectionTitle")
        l1.addWidget(t1)
        self.chart = BarChart()
        l1.addWidget(self.chart, 1)
        c1.setMinimumHeight(260)
        mid.addWidget(c1, 3)
        c2 = card()
        l2 = QVBoxLayout(c2)
        l2.setContentsMargins(18, 16, 18, 14)
        l2.setSpacing(8)
        lbl = QLabel("Reposição de estoque")
        lbl.setObjectName("sectionTitle")
        l2.addWidget(lbl)
        self.k_low = KpiCard("")
        self.low_note = QLabel("")
        self.low_note.setObjectName("kpiNote")
        l2.addWidget(self.low_note)
        self.table = make_table(["Produto", "Estoque", "Mínimo"], {1: 104, 2: 64}, stretch=(0,))
        self.table.empty_text = "Nenhum produto abaixo do mínimo"
        l2.addWidget(self.table, 1)
        mid.addWidget(c2, 2)
        root.addLayout(mid, 1)

        self.foot = QLabel("")
        self.foot.setObjectName("pageSub")
        self.foot.setWordWrap(True)
        root.addWidget(self.foot)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            d = dashboard_service.load_dashboard(s)
            low = product_service.search_products(s, low_stock_only=True, order_by="quantity")[:15]
            low_rows = [(p.internal_code, p.name, p.quantity_on_hand, p.min_stock, p.allows_fraction) for p in low]

        if not d.has_company:
            self.hint.setText("Bem-vindo! Comece em <b>Empresa</b> cadastrando os dados do seu negócio, "
                              "depois cadastre seus produtos em <b>Produtos</b>.")
            self.hint.show()
        elif d.total_products == 0:
            self.hint.setText("Nenhum produto cadastrado ainda. Vá em <b>Produtos</b> e clique em "
                              "<b>Novo produto</b> (atalho Ctrl+N) para começar.")
            self.hint.show()
        else:
            self.hint.hide()

        self.k_today.set(format_brl(d.sales_today_total), f"{d.sales_today_count} venda(s) concluída(s) hoje")
        self.k_month.set(format_brl(d.sales_month_total), "Vendas concluídas menos devoluções")
        self.k_profit.set(format_brl(d.month_gross_profit), "Receita líquida − custo médio das mercadorias",
                          tone="negative" if d.month_gross_profit < 0 else "")
        self.k_result.set(format_brl(d.month_result), f"Após despesas pagas de {format_brl(d.month_expenses)} — estimativa",
                          tone="negative" if d.month_result < 0 else "")
        self.k_cash.set(format_brl(d.cash_balance), "Soma de todas as contas ativas",
                        tone="negative" if d.cash_balance < 0 else "")
        self.k_rec.set(format_brl(d.receivable_open), f"Vencido: {format_brl(d.receivable_overdue)}",
                       note_tone="warn" if d.receivable_overdue > 0 else "")
        self.k_pay.set(format_brl(d.payable_open), f"Vencido: {format_brl(d.payable_overdue)}",
                       note_tone="warn" if d.payable_overdue > 0 else "")
        self.k_value.set(format_brl(d.stock_value_at_cost), f"{d.total_products} produtos ativos")
        self.chart.set_data(d.daily_sales)
        self.low_note.setText(f"{d.low_stock_count} produto(s) em estoque baixo, {d.out_of_stock_count} sem estoque")
        self.foot.setText("Todos os valores vêm do seu banco de dados. Resultado e lucro são estimativas gerenciais, "
                          "não substituem a contabilidade.")

        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(low_rows))
        for r, (code, name, qty, mn, frac) in enumerate(low_rows):
            t.setItem(r, 0, SortItem(f"{code} — {name}"))
            it = SortItem(format_qty(qty, frac), qty, True)
            it.setData(LEVEL_ROLE, (float(qty), float(mn)))
            t.setItem(r, 1, it)
            t.setItem(r, 2, SortItem(format_qty(mn, frac), mn, True))
        t.setSortingEnabled(True)
