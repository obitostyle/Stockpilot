from __future__ import annotations


from ..theme import color_negative

from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from ...domain.enums import TaxRegime
from ...domain.errors import ValidationError
from ...domain.formatting import format_brl, format_date, format_percent, parse_decimal_br
from ...services import company_service, tax_rules, tax_service as ts
from ..common import SortItem, card, make_table, primary, read_decimal, run_action, title_block
from ..widgets import date_edit, form_dialog, money_edit, to_date
from .base import Page

DISCLAIMER = ("ESTIMATIVA para apoio à gestão. Não substitui o PGDAS-D/PGMEI nem o seu contador, não emite guia e não "
              "transmite declarações. Confira sempre os valores oficiais antes de pagar.")


def current_competence() -> str:
    t = date.today()
    return ts.comp_str(t.year, t.month)


def comp_label(c: str) -> str:
    return f"{c[5:]}/{c[:4]}"


class AssessTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.result = None
        lay = QVBoxLayout(self)
        warn = QLabel(DISCLAIMER)
        warn.setObjectName("hint")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        bar = QHBoxLayout()
        self.comp = QComboBox()
        for i in range(0, 24):
            c = ts.add_comp(current_competence(), -i)
            self.comp.addItem(comp_label(c), c)
        self.mei_act = QComboBox()
        for k, v in (("COMERCIO", "MEI: comércio/indústria"), ("SERVICOS", "MEI: serviços"), ("AMBOS", "MEI: comércio + serviços")):
            self.mei_act.addItem(v, k)
        self.b_calc = primary(QPushButton("Calcular estimativa"))
        self.b_save = QPushButton("Salvar no histórico")
        self.b_save.setEnabled(False)
        bar.addWidget(QLabel("Competência:"))
        bar.addWidget(self.comp)
        bar.addWidget(self.mei_act)
        bar.addStretch()
        bar.addWidget(self.b_save)
        bar.addWidget(self.b_calc)
        lay.addLayout(bar)
        self.head = QLabel("")
        self.head.setObjectName("sectionTitle")
        lay.addWidget(self.head)
        self.table = make_table(["Item", "Valor"], {1: 170}, stretch=(0,))
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.setMaximumHeight(210)
        lay.addWidget(self.table)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        lay.addWidget(self.notes, 1)
        self.b_calc.clicked.connect(self.calc)
        self.b_save.clicked.connect(self.save)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            c = company_service.get_company(s)
            reg = c.tax_regime if c else None
        self.mei_act.setVisible(reg == TaxRegime.MEI)
        if reg is None:
            self.head.setText("Cadastre o regime tributário em Empresa para calcular.")
        elif reg not in (TaxRegime.MEI, TaxRegime.SIMPLES_NACIONAL):
            self.head.setText(f"Regime: {reg.label}. O cálculo de tributos deste regime não está implementado — use os relatórios para o seu contador.")
        else:
            self.head.setText(f"Regime: {reg.label}")

    def calc(self) -> None:
        def work():
            with self.ctx.db.session_scope() as s:
                c = company_service.get_company(s)
                if c is None:
                    raise ValidationError("Cadastre a empresa primeiro.")
                self.result = ts.assess(s, self.comp.currentData(), c, self.mei_act.currentData())
        self.result = None
        self.b_save.setEnabled(False)
        if not run_action(self, work):
            return
        r = self.result
        self.head.setText(f"{r.description} — competência {comp_label(r.competence)}   |   {r.status.label.upper()}")
        rows = [(k, format_brl(v)) for k, v in r.breakdown]
        if r.effective_rate is not None:
            rows.insert(1, ("Alíquota efetiva (estimada)", f"{r.effective_rate:.4f}%".replace(".", ",")))
        rows.append(("Vencimento padrão", format_date(r.due_date)))
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, SortItem(k))
            self.table.setItem(i, 1, SortItem(v, 0, True))
        txt = [r.label, ""]
        if r.missing:
            txt += ["DADOS QUE FALTAM (o valor é INCOMPLETO):"] + [f"  • {m}" for m in r.missing] + [""]
        txt += ["AVISOS:"] + [f"  • {w}" for w in r.warnings]
        self.notes.setPlainText("\n".join(txt))
        self.b_save.setEnabled(True)

    def save(self) -> None:
        if self.result is None:
            return

        def work():
            with self.ctx.db.session_scope() as s:
                ts.save_assessment(s, self.result, self.ctx.current_user_id)
        if run_action(self, work):
            QMessageBox.information(self, "Salvo", "Estimativa salva no histórico e vencimento incluído em Obrigações.")


class RevenueTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        h = QLabel("Faturamento por mês usado nas estimativas. Meses sem vendas no sistema (ex.: antes de usar o StockPilot) devem ser "
                   "informados aqui; o valor informado SUBSTITUI o calculado pelas vendas daquele mês.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)
        bar = QHBoxLayout()
        self.b_set = primary(QPushButton("Informar / corrigir faturamento do mês selecionado"))
        bar.addStretch()
        bar.addWidget(self.b_set)
        lay.addLayout(bar)
        self.table = make_table(["Mês", "Comércio", "Origem", "Serviços (informado)"], {0: 90, 1: 140, 2: 110, 3: 160}, stretch=())
        lay.addWidget(self.table, 1)
        self.b_set.clicked.connect(self._set)

    def refresh(self) -> None:
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(24)
        for i in range(24):
            c = ts.add_comp(current_competence(), -i)
            with self.ctx.db.session_scope() as s:
                a = ts.month_revenue(s, c, "COMERCIO")
                b = ts.month_revenue(s, c, "SERVICOS")
            vals = [(comp_label(c), c), (format_brl(a.amount) if a.has_data else "—", a.amount), (a.source, a.source),
                    (format_brl(b.amount) if b.has_data else "—", b.amount)]
            for j, (txt, k) in enumerate(vals):
                t.setItem(i, j, SortItem(txt, k, j in (1, 3)))
            t.item(i, 0).setData(Qt.UserRole, c)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)

    def _set(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione um mês", "Clique em um mês da lista primeiro.")
            return
        c = self.table.item(r, 0).data(Qt.UserRole)
        act = QComboBox()
        act.addItem("Comércio/indústria", "COMERCIO")
        act.addItem("Serviços", "SERVICOS")
        amt = money_edit("0,00")
        note = QLineEdit()

        def ok():
            with self.ctx.db.session_scope() as s:
                ts.set_revenue(s, c, act.currentData(), read_decimal(amt, "Faturamento", None), note.text() or None,
                               self.ctx.current_user_id)
        if form_dialog(self, f"Faturamento de {comp_label(c)}", [("Atividade", act), ("Faturamento (R$)", amt), ("Observação", note)], ok,
                       hint="Use 0,00 se não houve receita no mês — isso evita o alerta de mês sem dados."):
            self.refresh()


class HistoryTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.b_paid = primary(QPushButton("Registrar pagamento da guia"))
        bar.addStretch()
        bar.addWidget(self.b_paid)
        lay.addLayout(bar)
        self.table = make_table(["Competência", "Tributo", "Valor estimado", "Situação", "Vencimento", "Pago", "Data pgto."],
                                {0: 95, 2: 120, 3: 100, 4: 95, 5: 110, 6: 95}, stretch=(1,))
        lay.addWidget(self.table, 1)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(130)
        lay.addWidget(self.notes)
        self.table.itemSelectionChanged.connect(self._show)
        self.b_paid.clicked.connect(self._paid)
        self._warn = {}

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            rows = []
            for a in ts.list_assessments(s):
                w = ts.assessment_warnings(a)
                self._warn[a.id] = w
                rows.append((a.id, a.competence, a.description, a.amount, a.status.label, a.due_date, a.paid_amount, a.paid_date))
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (aid, c, d, amt, st, due, pa, pd) in enumerate(rows):
            vals = [(comp_label(c), c), (d, d), (format_brl(amt), amt), (st, st), (format_date(due), due),
                    (format_brl(pa) if pa is not None else "", pa or 0), (format_date(pd), pd or date.min)]
            for j, (txt, k) in enumerate(vals):
                t.setItem(i, j, SortItem(txt, k, j in (2, 5)))
            t.item(i, 0).setData(Qt.UserRole, aid)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)

    def _show(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        w = self._warn.get(self.table.item(r, 0).data(Qt.UserRole), {})
        txt = []
        if w.get("faltando"):
            txt += ["DADOS QUE FALTAVAM:"] + [f"  • {m}" for m in w["faltando"]] + [""]
        txt += ["AVISOS:"] + [f"  • {m}" for m in w.get("avisos", [])]
        self.notes.setPlainText("\n".join(txt))

    def _paid(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione uma apuração", "Clique em uma linha primeiro.")
            return
        aid = self.table.item(r, 0).data(Qt.UserRole)
        amt, d, note = money_edit("0,00"), date_edit(), QLineEdit()

        def ok():
            with self.ctx.db.session_scope() as s:
                ts.mark_paid(s, aid, read_decimal(amt, "Valor pago", None), to_date(d), note.text() or None)
        if form_dialog(self, "Registrar pagamento", [("Valor pago (R$) — conforme a guia oficial", amt), ("Data", d), ("Observação", note)], ok,
                       hint="Informe o valor da guia oficial paga (PGDAS-D/PGMEI). Isto só registra o controle; não lança no caixa."):
            self.refresh()


class ObligationsTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        h = QLabel("Obrigações geradas ao salvar uma apuração. Vencimento padrão: dia 20 do mês seguinte — confirme no PGDAS-D/PGMEI.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)
        self.table = make_table(["Obrigação", "Competência", "Vencimento", "Situação"], {1: 100, 2: 100, 3: 100}, stretch=(0,))
        lay.addWidget(self.table, 1)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            rows = [(o.name, o.competence, o.due_date, o.status) for o in ts.list_obligations(s)]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (n, c, d, st) in enumerate(rows):
            late = st == "PENDENTE" and d < date.today()
            for j, (txt, k) in enumerate(((n, n), (comp_label(c), c), (format_date(d), d), ("VENCIDA" if late else st.capitalize(), st))):
                it = SortItem(txt, k)
                t.setItem(i, j, it)
                if late:
                    it.setForeground(color_negative())
        t.setSortingEnabled(True)
        t.sortByColumn(2, Qt.AscendingOrder)


class TablesTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        h = QLabel("Tabelas legais usadas nos cálculos. Cada uma mostra a fonte e a data de conferência. Quando a lei mudar, cadastre uma "
                   "nova versão com a fonte — as versões antigas continuam valendo para competências antigas.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)
        bar = QHBoxLayout()
        self.b_new = primary(QPushButton("Nova versão de tabela…"))
        self.b_par = QPushButton("Novo valor de parâmetro…")
        bar.addStretch()
        bar.addWidget(self.b_par)
        bar.addWidget(self.b_new)
        lay.addLayout(bar)
        self.table = make_table(["Tabela", "Vigência", "Base legal", "Fonte / conferência", "Faixas"],
                                {0: 150, 1: 170, 4: 60}, stretch=(2, 3))
        lay.addWidget(self.table, 1)
        self.params = make_table(["Parâmetro", "Valor", "Vigência", "Fonte"], {0: 190, 1: 100, 2: 170}, stretch=(3,))
        lay.addWidget(self.params, 1)
        self.b_new.clicked.connect(self._new)
        self.b_par.clicked.connect(self._param)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            tabs = [(t.code, f"{format_date(t.valid_from)} a {format_date(t.valid_to) if t.valid_to else 'atual'}", t.legal_basis,
                     f"{t.source} (conferido em {format_date(t.verified_at)})", str(len(t.brackets))) for t in tax_rules.list_tables(s)]
            pars = [(p.key, p.value, f"{format_date(p.valid_from)} a {format_date(p.valid_to) if p.valid_to else 'atual'}",
                     f"{p.source} (conferido em {format_date(p.verified_at)})") for p in tax_rules.list_parameters(s)]
        for t, rows in ((self.table, tabs), (self.params, pars)):
            t.setSortingEnabled(False)
            t.setRowCount(len(rows))
            for i, row in enumerate(rows):
                for j, v in enumerate(row):
                    t.setItem(i, j, SortItem(v))
            t.setSortingEnabled(True)

    def _new(self) -> None:
        code = QLineEdit()
        code.setPlaceholderText("Ex.: IRRF_MENSAL, INSS_EMPREGADO, SIMPLES_ANEXO_I")
        desc, basis, src = QLineEdit(), QLineEdit(), QLineEdit()
        start = date_edit()
        rows = QPlainTextEdit()
        rows.setPlaceholderText("Uma faixa por linha: limite;alíquota%;parcela a deduzir\nExemplo: 2428,80;0;0\nÚltima faixa sem teto: deixe o limite vazio → ;27,5;908,73")
        rows.setFixedHeight(130)

        def ok():
            parsed = []
            for ln in rows.toPlainText().splitlines():
                if not ln.strip():
                    continue
                parts = [x.strip() for x in ln.split(";")]
                if len(parts) != 3:
                    raise ValidationError(f"Linha inválida: '{ln}'. Use limite;alíquota;dedução.")
                try:
                    parsed.append((parse_decimal_br(parts[0]) if parts[0] else None, parse_decimal_br(parts[1]), parse_decimal_br(parts[2])))
                except ValueError:
                    raise ValidationError(f"Número inválido na linha: '{ln}'.")
            with self.ctx.db.session_scope() as s:
                tax_rules.add_table_version(s, code=code.text().strip().upper(), description=desc.text().strip() or code.text(),
                                            valid_from=to_date(start), legal_basis=basis.text(), source=src.text(), rows=parsed)
        if form_dialog(self, "Nova versão de tabela", [("Código *", code), ("Descrição", desc), ("Início da vigência", start),
                                                        ("Base legal *", basis), ("Fonte da conferência *", src), ("Faixas *", rows)], ok,
                       hint="Confira os valores em fonte oficial (Receita Federal, Planalto, Portaria) ou com seu contador. A versão anterior é encerrada na véspera.",
                       min_width=620):
            self.refresh()

    def _param(self) -> None:
        key, val, src = QLineEdit(), QLineEdit(), QLineEdit()
        start = date_edit()
        key.setPlaceholderText("Ex.: salario_minimo")

        def ok():
            try:
                v = str(parse_decimal_br(val.text()))
            except ValueError:
                raise ValidationError("Valor inválido.")
            with self.ctx.db.session_scope() as s:
                tax_rules.set_parameter(s, key.text().strip(), v, to_date(start), src.text())
        if form_dialog(self, "Novo valor de parâmetro", [("Chave *", key), ("Valor *", val), ("Início da vigência", start), ("Fonte *", src)], ok):
            self.refresh()


class TaxPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(10)
        root.addWidget(title_block("Tributário", "Estimativa de impostos para MEI e Simples Nacional — com avisos do que falta"))
        self.tabs = QTabWidget()
        self.parts = [("Apuração estimada", AssessTab(ctx)), ("Faturamento", RevenueTab(ctx)), ("Histórico", HistoryTab(ctx)),
                      ("Obrigações", ObligationsTab(ctx)), ("Tabelas legais", TablesTab(ctx))]
        for n, w in self.parts:
            self.tabs.addTab(w, n)
        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda *_: self.refresh())

    def refresh(self) -> None:
        self.parts[self.tabs.currentIndex()][1].refresh()
