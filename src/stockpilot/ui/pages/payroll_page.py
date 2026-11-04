from __future__ import annotations


import json
from datetime import date
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ...domain.enums import EmployeeStatus
from ...domain.errors import PermissionDeniedError, ValidationError
from ...domain.formatting import format_brl, format_date, parse_decimal_br
from ...domain.validators import format_cpf
from ...services import payroll_service as pr
from ..common import SortItem, confirm, danger, make_table, primary, read_decimal, run_action, title_block
from ..widgets import date_edit, form_dialog, money_edit, to_date
from .base import Page
from .tax_page import comp_label, current_competence

DISCLAIMER = ("SIMULAÇÃO ESTIMADA. Não é folha oficial: não gera eSocial, FGTS Digital, holerite legal nem substitui o contador. "
              "Dados pessoais e salariais — acesso restrito a Administrador e Gerente.")


def pct_text(v: Decimal) -> str:
    return str(v.normalize() if v == v.to_integral_value() else v).replace(".", ",")


def comp_combo(n: int = 24) -> QComboBox:
    c = QComboBox()
    for i in range(n):
        k = _add(current_competence(), -i)
        c.addItem(comp_label(k), k)
    return c


def _add(c: str, n: int) -> str:
    from ...services.tax_service import add_comp
    return add_comp(c, n)


def emp_combo(ctx, include_terminated=False) -> QComboBox:
    c = QComboBox()
    with ctx.db.session_scope() as s:
        for e in pr.list_employees(s, ctx.current_user_id, include_terminated):
            c.addItem(e.name, e.id)
    return c


def show_result_dialog(parent, r: pr.SimResult) -> None:
    d = QDialog(parent)
    d.setWindowTitle(r.title)
    d.setMinimumSize(640, 560)
    lay = QVBoxLayout(d)
    head = QLabel(f"{r.title}   —   {r.label}")
    head.setObjectName("sectionTitle")
    head.setWordWrap(True)
    lay.addWidget(head)
    t = make_table(["Descrição", "Valor"], {1: 130}, stretch=(0,))
    t.setSortingEnabled(False)
    rows = [(k, v) for k, v in r.items] + [(f"(−) {k}", v) for k, v in r.deductions] + [("TOTAL BRUTO", r.total), ("LÍQUIDO ESTIMADO" if r.kind != "RESCISAO" else "TOTAL (BRUTO)", r.net)]
    t.setRowCount(len(rows))
    for i, (k, v) in enumerate(rows):
        t.setItem(i, 0, SortItem(k))
        t.setItem(i, 1, SortItem(format_brl(v), 0, True))
    lay.addWidget(t, 1)
    box = QPlainTextEdit()
    box.setReadOnly(True)
    txt = []
    if r.missing:
        txt += ["DADOS QUE FALTAM:"] + [f"  • {m}" for m in r.missing] + [""]
    txt += ["AVISOS E LIMITAÇÕES:"] + [f"  • {w}" for w in r.warnings]
    box.setPlainText("\n".join(txt))
    box.setMaximumHeight(170)
    lay.addWidget(box)
    b = primary(QPushButton("Fechar"))
    b.clicked.connect(d.accept)
    lay.addWidget(b, 0, Qt.AlignRight)
    d.exec()


class EmployeesTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.show_all = QCheckBox("Mostrar desligados")
        self.b_new = primary(QPushButton("＋ Novo funcionário"))
        self.b_edit = QPushButton("Editar")
        self.b_ben = QPushButton("Benefícios…")
        self.b_hist = QPushButton("Histórico salarial")
        self.b_stat = QPushButton("Situação / desligar…")
        bar.addWidget(self.show_all)
        bar.addStretch()
        for b in (self.b_hist, self.b_ben, self.b_stat, self.b_edit, self.b_new):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = make_table(["Nome", "CPF", "Cargo", "Admissão", "Salário base", "Situação"],
                                {1: 120, 3: 95, 4: 115, 5: 100}, stretch=(0, 2))
        self.table.empty_text = "Nenhum funcionário cadastrado — clique em Novo funcionário"
        lay.addWidget(self.table, 1)
        self.show_all.toggled.connect(self.refresh)
        self.b_new.clicked.connect(lambda: self._edit(None))
        self.b_edit.clicked.connect(lambda: self._edit(self._sel()))
        self.b_ben.clicked.connect(self._benefits)
        self.b_hist.clicked.connect(self._history)
        self.b_stat.clicked.connect(self._status)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            rows = [(e.id, e.name, format_cpf(e.cpf), e.job_title or "", e.admission_date, e.base_salary, e.status.label)
                    for e in pr.list_employees(s, self.ctx.current_user_id, self.show_all.isChecked())]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (eid, n, cpf, job, adm, sal, st) in enumerate(rows):
            for j, (txt, k) in enumerate(((n, n), (cpf, cpf), (job, job), (format_date(adm), adm), (format_brl(sal), sal), (st, st))):
                t.setItem(i, j, SortItem(txt, k, j == 4))
            t.item(i, 0).setData(Qt.UserRole, eid)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.AscendingOrder)

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione um funcionário", "Clique em um funcionário da lista primeiro.")
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _edit(self, eid) -> None:
        if eid is None and self.sender() is self.b_edit:
            return
        name, cpf, job, adm, sal = QLineEdit(), QLineEdit(), QLineEdit(), date_edit(), money_edit("0,00")
        hours, deps = QSpinBox(), QSpinBox()
        hours.setRange(1, 44)
        hours.setValue(44)
        deps.setRange(0, 20)
        he, he100, night = money_edit(text="50"), money_edit(text="100"), money_edit(text="20")
        vt, vtc = QCheckBox("Recebe vale-transporte"), money_edit("Custo mensal do VT")
        reason = QLineEdit()
        reason.setPlaceholderText("Motivo, se o salário mudar (ex.: dissídio)")
        if eid:
            with self.ctx.db.session_scope() as s:
                e = pr.get_employee(s, self.ctx.current_user_id, eid)
                name.setText(e.name)
                cpf.setText(format_cpf(e.cpf))
                job.setText(e.job_title or "")
                from ..widgets import set_date
                set_date(adm, e.admission_date)
                sal.setText(str(e.base_salary).replace(".", ","))
                hours.setValue(e.weekly_hours)
                deps.setValue(e.dependents)
                he.setText(pct_text(e.overtime_pct))
                he100.setText(pct_text(e.overtime_sunday_pct))
                night.setText(pct_text(e.night_pct))
                vt.setChecked(e.vt_enabled)
                vtc.setText(str(e.vt_monthly_cost).replace(".", ","))

        def ok():
            data = pr.EmployeeData(name.text(), cpf.text(), to_date(adm), read_decimal(sal, "Salário", None), job.text() or None,
                                   hours.value(), deps.value(), read_decimal(he, "HE"), read_decimal(he100, "HE domingo"),
                                   read_decimal(night, "Noturno"), vt.isChecked(), read_decimal(vtc, "VT"))
            with self.ctx.db.session_scope() as s:
                pr.save_employee(s, self.ctx.current_user_id, data, eid, reason.text() or None)
        if form_dialog(self, "Funcionário", [("Nome *", name), ("CPF *", cpf), ("Cargo", job), ("Admissão", adm), ("Salário base (R$) *", sal),
                                              ("Jornada semanal (h)", hours), ("Dependentes (IRRF)", deps),
                                              ("Adicional HE dias úteis (%)", he), ("Adicional HE domingo/feriado (%)", he100),
                                              ("Adicional noturno (%)", night), ("", vt), ("Custo mensal do VT (R$)", vtc),
                                              ("Motivo da alteração salarial", reason)], ok, min_width=520):
            self.refresh()

    def _benefits(self) -> None:
        eid = self._sel()
        if eid is None:
            return
        d = QDialog(self)
        d.setWindowTitle("Benefícios")
        d.setMinimumSize(560, 360)
        lay = QVBoxLayout(d)
        t = make_table(["Benefício", "Custo p/ empresa", "Desconto do funcionário"], {1: 140, 2: 170}, stretch=(0,))
        lay.addWidget(t)
        row = QHBoxLayout()
        b_add, b_rm, b_close = primary(QPushButton("＋ Adicionar")), danger(QPushButton("Remover")), QPushButton("Fechar")
        row.addWidget(b_rm)
        row.addStretch()
        row.addWidget(b_close)
        row.addWidget(b_add)
        lay.addLayout(row)

        def load():
            with self.ctx.db.session_scope() as s:
                bens = [(b.id, b.name, b.monthly_value, b.employee_discount) for b in pr.get_employee(s, self.ctx.current_user_id, eid).benefits]
            t.setSortingEnabled(False)
            t.setRowCount(len(bens))
            for i, (bid, n, v, dsc) in enumerate(bens):
                for j, (txt, k) in enumerate(((n, n), (format_brl(v), v), (format_brl(dsc), dsc))):
                    t.setItem(i, j, SortItem(txt, k, j > 0))
                t.item(i, 0).setData(Qt.UserRole, bid)

        def add():
            n, v, dsc = QLineEdit(), money_edit("0,00"), money_edit("0,00", "0")

            def ok():
                with self.ctx.db.session_scope() as s:
                    pr.add_benefit(s, self.ctx.current_user_id, eid, n.text(), read_decimal(v, "Custo", None), read_decimal(dsc, "Desconto"))
            if form_dialog(d, "Novo benefício", [("Nome *", n), ("Custo mensal p/ empresa (R$)", v), ("Desconto do funcionário (R$)", dsc)], ok):
                load()

        def rm():
            r = t.currentRow()
            if r >= 0:
                with self.ctx.db.session_scope() as s:
                    pr.remove_benefit(s, self.ctx.current_user_id, t.item(r, 0).data(Qt.UserRole))
                load()
        b_add.clicked.connect(add)
        b_rm.clicked.connect(rm)
        b_close.clicked.connect(d.accept)
        load()
        d.exec()

    def _history(self) -> None:
        eid = self._sel()
        if eid is None:
            return
        with self.ctx.db.session_scope() as s:
            e = pr.get_employee(s, self.ctx.current_user_id, eid)
            lines = [f"{format_date(h.effective_date)}   {format_brl(h.salary)}   {h.reason or ''}" for h in e.salary_history]
            name = e.name
        QMessageBox.information(self, f"Histórico salarial — {name}", "\n".join(lines) or "Sem registros.")

    def _status(self) -> None:
        eid = self._sel()
        if eid is None:
            return
        st, d = QComboBox(), date_edit()
        for s_ in EmployeeStatus:
            st.addItem(s_.label, s_.value)

        def ok():
            with self.ctx.db.session_scope() as s:
                pr.set_status(s, self.ctx.current_user_id, eid, EmployeeStatus(st.currentData()), to_date(d))
        if form_dialog(self, "Situação do funcionário", [("Situação", st), ("Data de desligamento", d)], ok,
                       hint="A data só é usada se a situação for 'Desligado'. O histórico do funcionário é mantido."):
            self.refresh()


class PayslipTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.res = None
        self.inp = None
        lay = QVBoxLayout(self)
        w = QLabel(DISCLAIMER)
        w.setObjectName("hint")
        w.setWordWrap(True)
        lay.addWidget(w)
        bar = QHBoxLayout()
        self.emp = QComboBox()
        self.comp = comp_combo()
        self.b_calc = primary(QPushButton("Calcular estimativa…"))
        self.b_save = QPushButton("Salvar no histórico")
        self.b_save.setEnabled(False)
        bar.addWidget(self.emp, 1)
        bar.addWidget(self.comp)
        bar.addWidget(self.b_save)
        bar.addWidget(self.b_calc)
        lay.addLayout(bar)
        self.table = make_table(["Descrição", "Proventos", "Descontos", "Informativo (empresa)"], {1: 120, 2: 120, 3: 170}, stretch=(0,))
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        lay.addWidget(self.table, 1)
        self.sum = QLabel("")
        self.sum.setObjectName("sectionTitle")
        lay.addWidget(self.sum)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(150)
        lay.addWidget(self.notes)
        self.b_calc.clicked.connect(self.calc)
        self.b_save.clicked.connect(self.save)

    def refresh(self) -> None:
        keep = self.emp.currentData()
        self.emp.clear()
        with self.ctx.db.session_scope() as s:
            for e in pr.list_employees(s, self.ctx.current_user_id, False):
                self.emp.addItem(e.name, e.id)
        i = self.emp.findData(keep)
        self.emp.setCurrentIndex(max(0, i))

    def calc(self) -> None:
        eid = self.emp.currentData()
        if eid is None:
            QMessageBox.information(self, "Sem funcionário", "Cadastre um funcionário primeiro.")
            return
        f = {k: money_edit("0", "0") for k in ("he", "he100", "night", "abs", "late", "oe", "od")}
        for k in f:
            f[k].setText("0")
        dsr_off, dsr_work = QSpinBox(), QSpinBox()
        dsr_off.setRange(0, 31)
        dsr_work.setRange(0, 31)
        rows = [("Horas extras (dias úteis)", f["he"]), ("Horas extras (domingo/feriado)", f["he100"]), ("Horas em período noturno", f["night"]),
                ("Dias de falta injustificada", f["abs"]), ("Minutos de atraso", f["late"]), ("Outros proventos tributáveis (R$)", f["oe"]),
                ("Outros descontos (R$)", f["od"]), ("Domingos + feriados no mês (DSR)", dsr_off), ("Dias úteis no mês (DSR)", dsr_work)]

        def ok():
            self.inp = pr.PayrollInputs(read_decimal(f["he"], "HE"), read_decimal(f["he100"], "HE dom."), read_decimal(f["night"], "Noturno"),
                                        read_decimal(f["abs"], "Faltas"), read_decimal(f["late"], "Atrasos"), read_decimal(f["oe"], "Proventos"),
                                        read_decimal(f["od"], "Descontos"), dsr_off.value() or None, dsr_work.value() or None)
            with self.ctx.db.session_scope() as s:
                self.res = pr.calculate_payslip(s, self.ctx.current_user_id, eid, self.comp.currentData(), self.inp)
        self.res = None
        if not form_dialog(self, "Lançamentos do mês", rows, ok, ok_text="Calcular",
                           hint="Deixe 0 no que não houve. Para reflexo de horas extras no DSR, informe os dias do mês."):
            return
        r = self.res
        t = self.table
        t.setRowCount(len(r.lines))
        for i, l in enumerate(r.lines):
            t.setItem(i, 0, SortItem(l.description))
            for j, kind in enumerate(("P", "D", "I"), start=1):
                t.setItem(i, j, SortItem(format_brl(l.value) if l.kind == kind else "", 0, True))
        tc = format_brl(r.total_cost) if r.total_cost is not None else "não calculado (faltam dados)"
        self.sum.setText(f"Bruto {format_brl(r.gross)}   •   INSS {format_brl(r.inss)}   •   IRRF {format_brl(r.irrf)}   •   "
                         f"LÍQUIDO ESTIMADO {format_brl(r.net)}   •   Custo total p/ empresa: {tc}")
        txt = [r.label, ""]
        if r.missing:
            txt += ["DADOS QUE FALTAM:"] + [f"  • {m}" for m in r.missing] + [""]
        txt += ["AVISOS E LIMITAÇÕES:"] + [f"  • {w}" for w in r.warnings] + ["", "TABELAS USADAS:"] + [f"  • {k}: {v}" for k, v in r.rules.items()]
        self.notes.setPlainText("\n".join(txt))
        self.b_save.setEnabled(True)

    def save(self) -> None:
        if self.res is None:
            return

        def work():
            with self.ctx.db.session_scope() as s:
                pr.save_payslip(s, self.ctx.current_user_id, self.res, self.inp)
        if run_action(self, work):
            QMessageBox.information(self, "Salvo", "Demonstrativo estimado salvo no histórico da folha.")


class SimTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        w = QLabel(DISCLAIMER)
        w.setObjectName("hint")
        w.setWordWrap(True)
        lay.addWidget(w)
        self.emp = QComboBox()
        lay.addWidget(self.emp)
        row = QHBoxLayout()
        self.b13, self.bv, self.br = QPushButton("Simular 13º salário…"), QPushButton("Simular férias…"), danger(QPushButton("Simular rescisão…"))
        for b in (self.b13, self.bv, self.br):
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("Simulações salvas"))
        self.table = make_table(["Data", "Funcionário", "Tipo", "Resumo"], {0: 140, 1: 180, 2: 130}, stretch=(3,))
        lay.addWidget(self.table, 1)
        self.b13.clicked.connect(self._13)
        self.bv.clicked.connect(self._vac)
        self.br.clicked.connect(self._term)

    def refresh(self) -> None:
        keep = self.emp.currentData()
        self.emp.clear()
        with self.ctx.db.session_scope() as s:
            for e in pr.list_employees(s, self.ctx.current_user_id, True):
                self.emp.addItem(e.name, e.id)
            from sqlalchemy import select
            from sqlalchemy.orm import joinedload
            from ...models import PayrollSimulation
            sims = [(x.created_at, x.employee.name, x.kind, json.loads(x.result).get("title", "")) for x in
                    s.scalars(select(PayrollSimulation).options(joinedload(PayrollSimulation.employee)).order_by(PayrollSimulation.id.desc()).limit(200))]
        self.emp.setCurrentIndex(max(0, self.emp.findData(keep)))
        from ...domain.formatting import format_datetime_local
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(sims))
        for i, (dt, n, k, ttl) in enumerate(sims):
            for j, (txt, key) in enumerate(((format_datetime_local(dt), dt), (n, n), ({"FERIAS": "Férias", "DECIMO_TERCEIRO": "13º salário", "RESCISAO": "Rescisão"}[k], k), (ttl, ttl))):
                t.setItem(i, j, SortItem(txt, key))
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)

    def _eid(self):
        e = self.emp.currentData()
        if e is None:
            QMessageBox.information(self, "Sem funcionário", "Cadastre/seleciona um funcionário primeiro.")
        return e

    def _run(self, eid, ref, fn) -> None:
        box = {}

        def work():
            with self.ctx.db.session_scope() as s:
                r = fn(s)
                pr.save_simulation(s, self.ctx.current_user_id, eid, ref, r)
                box["r"] = r
        if run_action(self, work):
            self.refresh()
            show_result_dialog(self, box["r"])

    def _13(self) -> None:
        eid = self._eid()
        if eid is None:
            return
        year = QSpinBox()
        year.setRange(2000, 2100)
        year.setValue(date.today().year)
        self._run(eid, date(year.value(), 12, 1), lambda s: pr.simulate_13th(s, self.ctx.current_user_id, eid, year.value())) \
            if form_dialog(self, "13º salário", [("Ano", year)], lambda: None, ok_text="Simular") else None

    def _vac(self) -> None:
        eid = self._eid()
        if eid is None:
            return
        d, days, sell = date_edit(), QSpinBox(), QSpinBox()
        days.setRange(5, 30)
        days.setValue(30)
        sell.setRange(0, 10)
        if form_dialog(self, "Férias", [("Início do gozo", d), ("Dias de férias", days), ("Dias vendidos (abono, máx. 10)", sell)], lambda: None, ok_text="Simular"):
            self._run(eid, to_date(d), lambda s: pr.simulate_vacation(s, self.ctx.current_user_id, eid, to_date(d), days.value(), sell.value()))

    def _term(self) -> None:
        eid = self._eid()
        if eid is None:
            return
        reason, d, due, fgts, worked = QComboBox(), date_edit(), QSpinBox(), money_edit("Saldo do FGTS (opcional)"), QCheckBox("Aviso prévio trabalhado")
        for k, v in pr.REASONS.items():
            reason.addItem(v, k)
        due.setRange(0, 5)
        if form_dialog(self, "Rescisão", [("Motivo", reason), ("Data do desligamento", d), ("Períodos de férias vencidas", due),
                                           ("Saldo do FGTS (R$)", fgts), ("", worked)], lambda: read_decimal(fgts, "FGTS"), ok_text="Simular",
                       hint="Simulação com limitações importantes: INSS/IRRF da rescisão não são calculados."):
            bal = read_decimal(fgts, "FGTS", "0") if fgts.text().strip() else None
            self._run(eid, to_date(d), lambda s: pr.simulate_termination(s, self.ctx.current_user_id, eid, reason.currentData(), to_date(d),
                                                                         due.value(), bal, worked.isChecked()))


class HistoryTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.comp = QComboBox()
        self.comp.addItem("Todas as competências", None)
        for i in range(24):
            k = _add(current_competence(), -i)
            self.comp.addItem(comp_label(k), k)
        lay.addWidget(self.comp, 0, Qt.AlignLeft)
        self.table = make_table(["Competência", "Funcionário", "Bruto", "INSS", "IRRF", "Líquido", "Custo total", "Obs."],
                                {0: 95, 2: 105, 3: 95, 4: 95, 5: 105, 6: 110, 7: 160}, stretch=(1,))
        lay.addWidget(self.table, 1)
        self.comp.currentIndexChanged.connect(self.refresh)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            rows = [(x.competence, x.employee.name, x.gross, x.inss, x.irrf, x.net, x.total_cost, bool(json.loads(x.missing)))
                    for x in pr.payroll_history(s, self.ctx.current_user_id, self.comp.currentData())]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (c, n, g, inss, irrf, net, tc, inc) in enumerate(rows):
            vals = [(comp_label(c), c), (n, n), (format_brl(g), g), (format_brl(inss), inss), (format_brl(irrf), irrf), (format_brl(net), net),
                    (format_brl(tc) if tc is not None else "—", tc or 0), ("ESTIMATIVA INCOMPLETA" if inc else "Estimativa", inc)]
            for j, (txt, k) in enumerate(vals):
                t.setItem(i, j, SortItem(txt, k, 2 <= j <= 6))
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)


class PayrollPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(10)
        root.addWidget(title_block("Funcionários e folha", "Cadastro, folha estimada e simulações — acesso restrito"))
        self.denied = QLabel("")
        self.denied.setObjectName("error")
        self.denied.setWordWrap(True)
        root.addWidget(self.denied)
        self.tabs = QTabWidget()
        self.parts = [("Funcionários", EmployeesTab(ctx)), ("Folha do mês", PayslipTab(ctx)), ("13º, férias e rescisão", SimTab(ctx)),
                      ("Histórico da folha", HistoryTab(ctx))]
        for n, w in self.parts:
            self.tabs.addTab(w, n)
        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda *_: self.refresh())

    def refresh(self) -> None:
        try:
            with self.ctx.db.session_scope() as s:
                pr.guard(s, self.ctx.current_user_id)
        except PermissionDeniedError as exc:
            self.denied.setText(str(exc))
            self.tabs.setEnabled(False)
            return
        self.denied.setText("")
        self.tabs.setEnabled(True)
        self.parts[self.tabs.currentIndex()][1].refresh()
