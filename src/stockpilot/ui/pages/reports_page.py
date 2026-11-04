from __future__ import annotations


from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ...domain.enums import BillStatus, MovementType
from ...reports import builders as rb
from ...reports.export import to_pdf, to_xlsx
from ...reports.model import fmt
from ...services import finance_service as fin, product_service, supplier_service
from ..common import SortItem, card, make_table, primary, run_action, title_block
from ..widgets import date_edit, to_date
from .base import Page
from .payroll_page import comp_combo

# chave -> (título, filtros usados)
SPECS = [
    ("estoque_atual", "Estoque atual", {"category", "inactive"}),
    ("estoque_baixo", "Estoque baixo", set()),
    ("movimentacoes", "Movimentações de estoque", {"period", "mtype"}),
    ("compras", "Compras", {"period", "supplier"}),
    ("vendas", "Vendas", {"period"}),
    ("mais_vendidos", "Produtos mais vendidos", {"period"}),
    ("sem_movimentacao", "Produtos sem movimentação", {"days"}),
    ("giro_estoque", "Giro e reposição de estoque", {"days"}),
    ("margem", "Margem estimada por produto", set()),
    ("fluxo_caixa", "Fluxo de caixa", {"period", "account"}),
    ("contas_pagar", "Contas a pagar", {"period_opt", "bill_status"}),
    ("contas_receber", "Contas a receber", {"period_opt", "bill_status"}),
    ("resultado", "Resultado financeiro (estimado)", {"period"}),
    ("estimativas_tributarias", "Estimativas tributárias", set()),
    ("folha", "Folha de pagamento (estimada)", {"competence"}),
    ("custos_funcionarios", "Custos de funcionários (estimado)", {"competence"}),
]


class ReportsPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.report = None
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(10)
        root.addWidget(title_block("Relatórios", "Todos mostram período, data de geração e critérios de cálculo — exportam para Excel e PDF"))
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setFixedWidth(250)
        for key, title, _ in SPECS:
            self.list.addItem(title)
        body.addWidget(self.list)
        right = QVBoxLayout()
        f = card()
        fl = QHBoxLayout(f)
        self.w = {}
        self.w["start"], self.w["end"] = date_edit(date.today().replace(day=1)), date_edit()
        self.w["opt"] = QCheckBox("Filtrar por vencimento")
        self.w["category"], self.w["supplier"], self.w["mtype"] = QComboBox(), QComboBox(), QComboBox()
        self.w["account"], self.w["bill_status"] = QComboBox(), QComboBox()
        self.w["days"] = QSpinBox()
        self.w["days"].setRange(7, 730)
        self.w["days"].setValue(90)
        self.w["days"].setSuffix(" dias")
        self.w["inactive"] = QCheckBox("Incluir inativos")
        self.w["competence"] = comp_combo()
        self.w["competence"].insertItem(0, "Todas as competências", None)
        self.w["competence"].setCurrentIndex(1)
        self.labels = {}
        for name, lab in (("start", "De"), ("end", "Até"), ("opt", ""), ("category", "Categoria"), ("supplier", "Fornecedor"), ("mtype", "Tipo"),
                          ("account", "Conta"), ("bill_status", "Situação"), ("days", "Sem movimento há"), ("inactive", ""), ("competence", "Competência")):
            box = QVBoxLayout()
            if lab:
                l = QLabel(lab)
                l.setObjectName("kpiLabel")
                box.addWidget(l)
                self.labels[name] = l
            box.addWidget(self.w[name])
            fl.addLayout(box)
        fl.addStretch()
        self.b_gen = primary(QPushButton("Gerar relatório"))
        fl.addWidget(self.b_gen, 0, Qt.AlignBottom)
        right.addWidget(f)
        bar = QHBoxLayout()
        self.head = QLabel("")
        self.head.setObjectName("sectionTitle")
        self.b_x, self.b_p = QPushButton("Exportar Excel…"), QPushButton("Exportar PDF…")
        self.b_x.setEnabled(False)
        self.b_p.setEnabled(False)
        bar.addWidget(self.head, 1)
        bar.addWidget(self.b_x)
        bar.addWidget(self.b_p)
        right.addLayout(bar)
        self.meta = QLabel("")
        self.meta.setObjectName("pageSub")
        self.meta.setWordWrap(True)
        right.addWidget(self.meta)
        self.table = make_table(["—"], stretch=(0,))
        self.table.empty_text = "Escolha um relatório na lista e clique em Gerar relatório"
        right.addWidget(self.table, 1)
        self.notes = QLabel("")
        self.notes.setObjectName("hint")
        self.notes.setWordWrap(True)
        self.notes.hide()
        right.addWidget(self.notes)
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        self.list.currentRowChanged.connect(self._select)
        self.b_gen.clicked.connect(self.generate)
        self.b_x.clicked.connect(lambda: self._export("xlsx"))
        self.b_p.clicked.connect(lambda: self._export("pdf"))
        self.w["opt"].toggled.connect(lambda *_: self._sync())
        self.list.setCurrentRow(0)

    def _sync(self) -> None:
        row = self.list.currentRow()
        if row < 0:
            return
        use = SPECS[row][2]
        show = {"start": "period" in use or "period_opt" in use, "end": "period" in use or "period_opt" in use,
                "opt": "period_opt" in use, "category": "category" in use, "supplier": "supplier" in use, "mtype": "mtype" in use,
                "account": "account" in use, "bill_status": "bill_status" in use, "days": "days" in use, "inactive": "inactive" in use,
                "competence": "competence" in use}
        for k, v in show.items():
            self.w[k].setVisible(v)
            if k in self.labels:
                self.labels[k].setVisible(v)
        if "period_opt" in use:
            for k in ("start", "end"):
                self.w[k].setEnabled(self.w["opt"].isChecked())

    def _select(self, *_):
        self.report = None
        self.b_x.setEnabled(False)
        self.b_p.setEnabled(False)
        self._sync()

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            for name, items in (("category", [("Todas", None)] + [(c.name, c.id) for c in product_service.list_categories(s)]),
                                ("supplier", [("Todos", None)] + [(x.name, x.id) for x in supplier_service.list_suppliers(s, only_active=False)]),
                                ("mtype", [("Todos", None)] + [(t.label, t.value) for t in MovementType]),
                                ("account", [("Todas", None)] + [(a.name, a.id) for a in fin.list_accounts(s)]),
                                ("bill_status", [("Todas", None)] + [(t.label, t.value) for t in BillStatus])):
                c = self.w[name]
                keep = c.currentData()
                c.blockSignals(True)
                c.clear()
                for lab, val in items:
                    c.addItem(lab, val)
                c.setCurrentIndex(max(0, c.findData(keep)))
                c.blockSignals(False)
        self._sync()

    def generate(self) -> None:
        key, _title, use = SPECS[self.list.currentRow()]
        a, b = to_date(self.w["start"]), to_date(self.w["end"])

        def work():
            if a > b:
                from ...domain.errors import ValidationError
                raise ValidationError("A data inicial não pode ser maior que a final.")
            uid = self.ctx.current_user_id
            with self.ctx.db.session_scope() as s:
                w = self.w
                opt = (a, b) if w["opt"].isChecked() else (None, None)
                st = BillStatus(w["bill_status"].currentData()) if w["bill_status"].currentData() else None
                comp = w["competence"].currentData()
                self.report = {
                    "estoque_atual": lambda: rb.estoque_atual(s, w["category"].currentData(), w["inactive"].isChecked()),
                    "estoque_baixo": lambda: rb.estoque_baixo(s),
                    "movimentacoes": lambda: rb.movimentacoes(s, a, b, MovementType(w["mtype"].currentData()) if w["mtype"].currentData() else None),
                    "compras": lambda: rb.compras(s, a, b, w["supplier"].currentData()),
                    "vendas": lambda: rb.vendas(s, a, b),
                    "mais_vendidos": lambda: rb.mais_vendidos(s, a, b),
                    "sem_movimentacao": lambda: rb.sem_movimentacao(s, w["days"].value()),
                    "giro_estoque": lambda: rb.giro_estoque(s, w["days"].value()),
                    "margem": lambda: rb.margem(s),
                    "fluxo_caixa": lambda: rb.fluxo_caixa(s, a, b, w["account"].currentData()),
                    "contas_pagar": lambda: rb.contas_pagar(s, st, *opt),
                    "contas_receber": lambda: rb.contas_receber(s, st, *opt),
                    "resultado": lambda: rb.resultado(s, a, b),
                    "estimativas_tributarias": lambda: rb.estimativas_tributarias(s),
                    "folha": lambda: rb.folha(s, uid, comp),
                    "custos_funcionarios": lambda: rb.custos_funcionarios(s, uid, comp),
                }[key]()
        self.report = None
        if not run_action(self, work):
            return
        r = self.report
        self.head.setText(f"{r.title} — {len(r.rows)} linha(s)")
        self.meta.setText(f"Período: {r.period}   •   Gerado em {r.generated_at:%d/%m/%Y %H:%M}   •   Critérios: " + "; ".join(r.criteria))
        t = self.table
        t.setSortingEnabled(False)
        t.setColumnCount(len(r.columns))
        t.setHorizontalHeaderLabels([h for h, _ in r.columns])
        rows = list(r.rows) + ([r.totals] if r.totals else [])
        t.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, ((_, kind), v) in enumerate(zip(r.columns, row)):
                it = SortItem(fmt(v, kind), v if isinstance(v, (int, float)) or hasattr(v, "as_tuple") or isinstance(v, date) else None, kind in ("money", "qty", "pct", "int"))
                if r.totals and i == len(rows) - 1:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                t.setItem(i, j, it)
        t.horizontalHeader().setSectionResizeMode(0, t.horizontalHeader().ResizeMode.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        t.setSortingEnabled(False)
        if r.notes:
            self.notes.setText("\n".join("• " + n for n in r.notes))
            self.notes.show()
        else:
            self.notes.hide()
        self.b_x.setEnabled(True)
        self.b_p.setEnabled(True)

    def _export(self, kind: str) -> None:
        if self.report is None:
            return
        name = f"{self.report.key}_{date.today():%Y%m%d}.{kind}"
        path, _ = QFileDialog.getSaveFileName(self, "Salvar relatório", name, "Excel (*.xlsx)" if kind == "xlsx" else "PDF (*.pdf)")
        if not path:
            return

        def work():
            (to_xlsx if kind == "xlsx" else to_pdf)(self.report, path)
        if run_action(self, work):
            QMessageBox.information(self, "Relatório salvo", f"Arquivo salvo em:\n{path}")
