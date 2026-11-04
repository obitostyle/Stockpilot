from __future__ import annotations

from ..theme import color_negative, color_inactive

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ...domain.enums import AccountType, BillStatus, FinGroup, FinKind, FinOrigin
from ...domain.errors import ValidationError
from ...domain.formatting import format_brl, format_date
from ...services import finance_service as fin
from ..common import SortItem, card, confirm, danger, make_table, primary, read_decimal, run_action, title_block
from ..widgets import date_edit, form_dialog, money_edit, set_date, to_date
from .base import Page


def period_combo() -> QComboBox:
    c = QComboBox()
    for label, key in (("Este mês", "mes"), ("Mês anterior", "ant"), ("Últimos 30 dias", "30"),
                       ("Este ano", "ano"), ("Últimos 12 meses", "12m")):
        c.addItem(label, key)
    return c


def period_range(key: str) -> tuple[date, date]:
    t = date.today()
    if key == "mes":
        return t.replace(day=1), t
    if key == "ant":
        end = t.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if key == "30":
        return t - timedelta(days=29), t
    if key == "ano":
        return date(t.year, 1, 1), t
    return t - timedelta(days=364), t


def account_combo(ctx, with_all: bool = False) -> QComboBox:
    c = QComboBox()
    c.setProperty("with_all", with_all)
    reload_accounts(ctx, c)
    return c


def reload_accounts(ctx, c: QComboBox) -> None:
    """Recarrega as contas mantendo a seleção (contas novas aparecem sem reiniciar)."""
    keep = c.currentData()
    c.blockSignals(True)
    c.clear()
    if c.property("with_all"):
        c.addItem("Todas as contas", None)
    with ctx.db.session_scope() as s:
        for a in fin.list_accounts(s):
            c.addItem(a.name, a.id)
    i = c.findData(keep)
    c.setCurrentIndex(max(0, i))
    c.blockSignals(False)


class BillsTab(QWidget):
    def __init__(self, ctx, kind: str, parent=None):
        super().__init__(parent)
        self.ctx, self.kind = ctx, kind
        pay = kind == "P"
        self.verb = "Pagar" if pay else "Receber"
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItem("Em aberto", BillStatus.ABERTA.value)
        self.status.addItem("Todas", None)
        for st in (BillStatus.PAGA, BillStatus.CANCELADA):
            self.status.addItem(st.label, st.value)
        self.overdue = QCheckBox("Só vencidas")
        self.b_new = primary(QPushButton("＋ Nova conta"))
        self.b_pay = QPushButton(f"Dar baixa ({self.verb.lower()})")
        self.b_rev = QPushButton("Estornar baixa")
        self.b_cancel = danger(QPushButton("Cancelar conta"))
        bar.addWidget(self.status)
        bar.addWidget(self.overdue)
        bar.addStretch()
        for b in (self.b_pay, self.b_rev, self.b_cancel, self.b_new):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = make_table(["Vencimento", "Descrição", "Parcela", "Valor", "Pago", "Em aberto", "Situação"],
                                {0: 95, 2: 70, 3: 105, 4: 105, 5: 105, 6: 100}, stretch=(1,))
        self.table.empty_text = "Nenhuma conta neste filtro"
        lay.addWidget(self.table, 1)
        self.sum = QLabel("")
        self.sum.setObjectName("pageSub")
        lay.addWidget(self.sum)
        self.status.currentIndexChanged.connect(self.refresh)
        self.overdue.toggled.connect(self.refresh)
        self.b_new.clicked.connect(self._new)
        self.b_pay.clicked.connect(self._pay)
        self.b_rev.clicked.connect(self._reverse)
        self.b_cancel.clicked.connect(self._cancel)

    def refresh(self) -> None:
        st = BillStatus(self.status.currentData()) if self.status.currentData() else None
        with self.ctx.db.session_scope() as s:
            bills = fin.list_bills(s, self.kind, status=st, only_overdue=self.overdue.isChecked())
            rows = [(b.id, b.due_date, b.description + (f" — {b.customer_name}" if self.kind == "R" and b.customer_name else ""),
                     f"{b.installment_no}/{b.installment_total}", b.amount, b.paid_amount, b.open_amount, b.status)
                    for b in bills]
            total_open = fin.open_total(s, self.kind)
            overdue_open = sum((r[6] for r in rows if r[7] == BillStatus.ABERTA and r[1] < date.today()), Decimal("0"))
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, (bid, due, desc, par, amt, paid, op, stt) in enumerate(rows):
            late = stt == BillStatus.ABERTA and due < date.today()
            items = [SortItem(format_date(due), due), SortItem(desc), SortItem(par), SortItem(format_brl(amt), amt, True),
                     SortItem(format_brl(paid), paid, True), SortItem(format_brl(op), op, True),
                     SortItem("Vencida" if late else stt.label)]
            for c, it in enumerate(items):
                t.setItem(r, c, it)
                if late:
                    it.setForeground(color_negative())
                elif stt != BillStatus.ABERTA:
                    it.setForeground(color_inactive())
            t.item(r, 0).setData(Qt.UserRole, (bid, stt.value))
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.AscendingOrder)
        self.sum.setText(f"Total em aberto (todas): {format_brl(total_open)}   •   Vencido na lista: {format_brl(overdue_open)}")

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione uma conta", "Clique em uma conta da lista primeiro.")
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _new(self) -> None:
        desc, total, due = QLineEdit(), money_edit("0,00"), date_edit(date.today() + timedelta(days=30))
        parcels = QSpinBox()
        parcels.setRange(1, 60)
        cat = QComboBox()
        with self.ctx.db.session_scope() as s:
            groups = (FinGroup.DESPESA_FIXA, FinGroup.DESPESA_VARIAVEL) if self.kind == "P" else (FinGroup.OUTRA_RECEITA, FinGroup.RECEITA_VENDAS)
            for c in fin.list_categories(s, groups):
                cat.addItem(c.name, c.id)
        who = QLineEdit()
        who.setPlaceholderText("Nome do cliente" if self.kind == "R" else "(opcional)")

        def ok():
            with self.ctx.db.session_scope() as s:
                fin.create_bills(s, self.kind, description=desc.text(), total=read_decimal(total, "Valor", None),
                                 first_due=to_date(due), installments=parcels.value(), category_id=cat.currentData(),
                                 customer_name=who.text().strip() or None if self.kind == "R" else None)
        rows = [("Descrição *", desc), ("Valor total *", total), ("1º vencimento", due), ("Parcelas", parcels), ("Categoria", cat)]
        if self.kind == "R":
            rows.insert(1, ("Cliente *", who))
        if form_dialog(self, "Nova conta a " + ("pagar" if self.kind == "P" else "receber"), rows, ok):
            self.refresh()

    def _pay(self) -> None:
        sel = self._sel()
        if not sel:
            return
        with self.ctx.db.session_scope() as s:
            from ...services.finance_service import _bill
            b = _bill(s, self.kind, sel[0])
            open_amt, desc = b.open_amount, b.description
        amt = money_edit(text=str(open_amt).replace(".", ","))
        acc = account_combo(self.ctx)
        d = date_edit()

        def ok():
            with self.ctx.db.session_scope() as s:
                fin.pay_bill(s, self.kind, sel[0], read_decimal(amt, "Valor", None), account_id=acc.currentData(),
                             pay_date=to_date(d), user_id=self.ctx.current_user_id)
        if form_dialog(self, f"{self.verb} — {desc}", [("Valor (R$)", amt), ("Conta", acc), ("Data", d)], ok,
                       hint=f"Em aberto: {format_brl(open_amt)}. Pagamento parcial é permitido.", ok_text="Confirmar baixa"):
            self.refresh()

    def _reverse(self) -> None:
        sel = self._sel()
        if not sel:
            return
        with self.ctx.db.session_scope() as s:
            pays = [(p.id, f"{format_date(p.date)} — {format_brl(p.amount)} (lanç. #{p.id})")
                    for p in fin.bill_payments(s, self.kind, sel[0]) if p.reverses_id is None and not fin.is_reversed(s, p.id)]
        if not pays:
            QMessageBox.information(self, "Sem baixas", "Esta conta não tem baixas a estornar.")
            return
        label, ok = QInputDialog.getItem(self, "Estornar baixa", "Qual baixa estornar?", [p[1] for p in pays], 0, False)
        if not ok:
            return
        reason, ok = QInputDialog.getText(self, "Estornar baixa", "Motivo:")
        if not ok:
            return
        tx_id = next(p[0] for p in pays if p[1] == label)

        def work():
            with self.ctx.db.session_scope() as s:
                fin.reverse_payment(s, tx_id, reason, self.ctx.current_user_id)
        if run_action(self, work):
            self.refresh()

    def _cancel(self) -> None:
        sel = self._sel()
        if not sel:
            return
        reason, ok = QInputDialog.getText(self, "Cancelar conta", "Motivo do cancelamento:")
        if not ok or not confirm(self, "Cancelar conta", "A conta deixará de contar como em aberto. O registro é mantido.", "Cancelar conta"):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                fin.cancel_bill(s, self.kind, sel[0], reason)
        if run_action(self, work):
            self.refresh()


class SummaryTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.period = period_combo()
        lay.addWidget(self.period, 0, Qt.AlignLeft)
        self.table = make_table(["Indicador", "Valor"], {1: 160}, stretch=(0,))
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        lay.addWidget(self.table, 1)
        self.notes = QLabel("")
        self.notes.setObjectName("hint")
        self.notes.setWordWrap(True)
        lay.addWidget(self.notes)
        self.period.currentIndexChanged.connect(self.refresh)

    def refresh(self) -> None:
        a, b = period_range(self.period.currentData())
        with self.ctx.db.session_scope() as s:
            r = fin.result_summary(s, a, b)
        rows = [("Faturamento (vendas concluídas)", r.gross_revenue), ("(−) Devoluções", r.returns),
                ("Receita líquida", r.net_revenue), ("(−) CMV (custo das mercadorias vendidas)", r.cogs),
                ("Lucro bruto", r.gross_profit), ("(+) Outras receitas", r.other_income), ("(−) Despesas pagas", r.expenses),
                ("RESULTADO OPERACIONAL — ESTIMADO", r.operating_result), ("", None),
                ("Recebido de vendas no período (caixa)", r.receipts), ("Compras de mercadoria pagas", r.merchandise_paid),
                ("Saldo em caixa/contas na data final", r.cash_balance), ("Contas a receber em aberto", r.receivable_open),
                ("Contas a pagar em aberto", r.payable_open)]
        t = self.table
        t.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            t.setItem(i, 0, SortItem(k))
            it = SortItem("" if v is None else format_brl(v), 0, True)
            t.setItem(i, 1, it)
            if v is not None and k.startswith(("RESULTADO", "Lucro")):
                for c in (0, 1):
                    f = t.item(i, c).font()
                    f.setBold(True)
                    t.item(i, c).setFont(f)
        self.notes.setText("Premissas do cálculo:\n• " + "\n• ".join(r.assumptions))


class FlowTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.period = period_combo()
        self.acc = account_combo(ctx, True)
        bar.addWidget(self.period)
        bar.addWidget(self.acc)
        bar.addStretch()
        lay.addLayout(bar)
        self.table = make_table(["Dia", "Entradas", "Saídas", "Saldo do dia"], {0: 100, 1: 130, 2: 130, 3: 140}, stretch=())
        lay.addWidget(self.table, 1)
        self.lbl = QLabel("")
        self.lbl.setObjectName("pageSub")
        lay.addWidget(self.lbl)
        self.period.currentIndexChanged.connect(self.refresh)
        self.acc.currentIndexChanged.connect(self.refresh)

    def refresh(self) -> None:
        reload_accounts(self.ctx, self.acc)
        a, b = period_range(self.period.currentData())
        with self.ctx.db.session_scope() as s:
            opening, rows = fin.cash_flow(s, a, b, self.acc.currentData())
        rows = [r for r in rows if r.inflow or r.outflow]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for c, (txt, k) in enumerate(((format_date(r.day), r.day), (format_brl(r.inflow), r.inflow),
                                          (format_brl(r.outflow), r.outflow), (format_brl(r.balance), r.balance))):
                t.setItem(i, c, SortItem(txt, k, c > 0))
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)
        tin, tout = sum((r.inflow for r in rows), Decimal("0")), sum((r.outflow for r in rows), Decimal("0"))
        self.lbl.setText(f"Saldo inicial: {format_brl(opening)}   •   Entradas: {format_brl(tin)}   •   Saídas: {format_brl(tout)}   •   "
                         f"Saldo final: {format_brl(opening + tin - tout)}   (dias sem movimento ocultos)")


class TransactionsTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.period = period_combo()
        self.acc = account_combo(ctx, True)
        self.b_in = primary(QPushButton("＋ Entrada"))
        self.b_out = QPushButton("− Saída")
        self.b_rec = QPushButton("Conciliar / desconciliar")
        self.b_rev = danger(QPushButton("Estornar"))
        bar.addWidget(self.period)
        bar.addWidget(self.acc)
        bar.addStretch()
        for b in (self.b_rec, self.b_rev, self.b_out, self.b_in):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = make_table(["Data", "Conta", "Categoria", "Descrição", "Entrada", "Saída", "Origem", "Concil."],
                                {0: 90, 1: 110, 2: 140, 4: 100, 5: 100, 6: 90, 7: 60}, stretch=(3,))
        self.table.empty_text = "Nenhum lançamento no período"
        lay.addWidget(self.table, 1)
        self.period.currentIndexChanged.connect(self.refresh)
        self.acc.currentIndexChanged.connect(self.refresh)
        self.b_in.clicked.connect(lambda: self._new(FinKind.ENTRADA))
        self.b_out.clicked.connect(lambda: self._new(FinKind.SAIDA))
        self.b_rec.clicked.connect(self._reconcile)
        self.b_rev.clicked.connect(self._reverse)

    def refresh(self) -> None:
        reload_accounts(self.ctx, self.acc)
        a, b = period_range(self.period.currentData())
        with self.ctx.db.session_scope() as s:
            rec = fin.reconciled_ids(s)
            rows = [(x.id, x.date, x.account.name, x.category.name, x.description or "", x.kind, x.amount, x.origin,
                     x.reverses_id, x.id in rec, fin.is_reversed(s, x.id))
                    for x in fin.list_transactions(s, start=a, end=b, account_id=self.acc.currentData())]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, (tid, d, acc, cat, desc, kind, amt, org, revof, reco, was_rev) in enumerate(rows):
            if revof:
                desc = f"[ESTORNO #{revof}] {desc}"
            elif was_rev:
                desc = f"[ESTORNADO] {desc}"
            items = [SortItem(format_date(d), (d, tid)), SortItem(acc), SortItem(cat), SortItem(desc),
                     SortItem(format_brl(amt) if kind == FinKind.ENTRADA else "", amt if kind == FinKind.ENTRADA else 0, True),
                     SortItem(format_brl(amt) if kind == FinKind.SAIDA else "", amt if kind == FinKind.SAIDA else 0, True),
                     SortItem(org.label), SortItem("✔" if reco else "")]
            for c, it in enumerate(items):
                t.setItem(i, c, it)
                if revof or was_rev:
                    it.setForeground(color_inactive())
            t.item(i, 0).setData(Qt.UserRole, (tid, org.value, bool(revof), was_rev, reco))
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione um lançamento", "Clique em um lançamento da lista primeiro.")
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _new(self, kind: FinKind) -> None:
        acc = account_combo(self.ctx)
        d, amt, desc = date_edit(), money_edit("0,00"), QLineEdit()
        cat = QComboBox()
        with self.ctx.db.session_scope() as s:
            groups = (FinGroup.OUTRA_RECEITA,) if kind == FinKind.ENTRADA else (FinGroup.DESPESA_FIXA, FinGroup.DESPESA_VARIAVEL)
            for c in fin.list_categories(s, groups):
                cat.addItem(c.name, c.id)

        def ok():
            with self.ctx.db.session_scope() as s:
                fin.add_manual_transaction(s, account_id=acc.currentData(), tx_date=to_date(d), kind=kind,
                                           amount=read_decimal(amt, "Valor", None), category_id=cat.currentData() or 0,
                                           description=desc.text(), user_id=self.ctx.current_user_id)
        title = "Entrada manual (outras receitas)" if kind == FinKind.ENTRADA else "Saída manual (despesa)"
        if form_dialog(self, title, [("Conta", acc), ("Data", d), ("Valor (R$)", amt), ("Categoria", cat), ("Descrição *", desc)], ok):
            self.refresh()

    def _reconcile(self) -> None:
        sel = self._sel()
        if not sel:
            return

        def work():
            with self.ctx.db.session_scope() as s:
                if sel[4]:
                    fin.unreconcile(s, sel[0])
                else:
                    fin.reconcile(s, sel[0], date.today(), self.ctx.current_user_id)
        if run_action(self, work):
            self.refresh()

    def _reverse(self) -> None:
        sel = self._sel()
        if not sel:
            return
        if sel[1] != FinOrigin.MANUAL.value:
            QMessageBox.information(self, "Use a tela de origem",
                                    "Lançamentos de vendas, compras e baixas são corrigidos cancelando a venda/compra "
                                    "ou estornando a baixa na conta correspondente.")
            return
        if sel[2] or sel[3]:
            QMessageBox.information(self, "Não permitido", "Este lançamento já é um estorno ou já foi estornado.")
            return
        reason, ok = QInputDialog.getText(self, "Estornar lançamento", "Motivo do estorno:")
        if not ok:
            return

        def work():
            with self.ctx.db.session_scope() as s:
                fin.reverse_manual_transaction(s, sel[0], reason, self.ctx.current_user_id)
        if run_action(self, work):
            self.refresh()


class RegistryTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QHBoxLayout(self)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.addWidget(QLabel("Contas (caixa e bancos)"))
        self.t_acc = make_table(["Conta", "Tipo", "Saldo atual"], {1: 70, 2: 120}, stretch=(0,))
        left.addWidget(self.t_acc)
        r1 = QHBoxLayout()
        b1, b2 = primary(QPushButton("＋ Nova conta")), QPushButton("Editar conta")
        r1.addStretch()
        r1.addWidget(b2)
        r1.addWidget(b1)
        left.addLayout(r1)
        right.addWidget(QLabel("Categorias e centros de custo"))
        self.t_cat = make_table(["Categoria", "Grupo"], {1: 160}, stretch=(0,))
        right.addWidget(self.t_cat)
        r2 = QHBoxLayout()
        b3, b4 = primary(QPushButton("＋ Nova categoria")), QPushButton("＋ Centro de custo")
        r2.addStretch()
        r2.addWidget(b4)
        r2.addWidget(b3)
        right.addLayout(r2)
        lay.addLayout(left, 1)
        lay.addLayout(right, 1)
        b1.clicked.connect(lambda: self._acc(None))
        b2.clicked.connect(self._edit_acc)
        b3.clicked.connect(self._cat)
        b4.clicked.connect(self._cc)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            accs = [(a.id, a.name, a.type.label, fin.account_balance(s, a.id)) for a in fin.list_accounts(s, only_active=False)]
            cats = [(c.name, c.group.label) for c in fin.list_categories(s)]
        for t, rows in ((self.t_acc, accs), (self.t_cat, cats)):
            t.setSortingEnabled(False)
            t.setRowCount(len(rows))
            for i, row in enumerate(rows):
                vals = row[1:] if t is self.t_acc else row
                for c, v in enumerate(vals):
                    t.setItem(i, c, SortItem(format_brl(v) if isinstance(v, Decimal) else v, v if isinstance(v, Decimal) else None,
                                             isinstance(v, Decimal)))
                if t is self.t_acc:
                    t.item(i, 0).setData(Qt.UserRole, row[0])
            t.setSortingEnabled(True)

    def _edit_acc(self) -> None:
        r = self.t_acc.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione uma conta", "Clique em uma conta primeiro.")
            return
        self._acc(self.t_acc.item(r, 0).data(Qt.UserRole))

    def _acc(self, acc_id) -> None:
        name, typ, bal = QLineEdit(), QComboBox(), money_edit("0,00", "0")
        for t in AccountType:
            typ.addItem(t.label, t.value)
        if acc_id:
            with self.ctx.db.session_scope() as s:
                a = next(x for x in fin.list_accounts(s, only_active=False) if x.id == acc_id)
                name.setText(a.name)
                typ.setCurrentIndex(typ.findData(a.type.value))
                bal.setText(str(a.opening_balance).replace(".", ","))

        def ok():
            with self.ctx.db.session_scope() as s:
                fin.save_account(s, name.text(), AccountType(typ.currentData()), read_decimal(bal, "Saldo inicial"), acc_id)
        if form_dialog(self, "Conta", [("Nome *", name), ("Tipo", typ), ("Saldo inicial (R$)", bal)], ok,
                       hint="O saldo inicial só pode ser alterado enquanto a conta não tiver lançamentos."):
            self.refresh()

    def _cat(self) -> None:
        name, grp = QLineEdit(), QComboBox()
        for g in (FinGroup.OUTRA_RECEITA, FinGroup.DESPESA_FIXA, FinGroup.DESPESA_VARIAVEL):
            grp.addItem(g.label, g.value)

        def ok():
            with self.ctx.db.session_scope() as s:
                fin.save_category(s, name.text(), FinGroup(grp.currentData()))
        if form_dialog(self, "Nova categoria", [("Nome *", name), ("Grupo", grp)], ok):
            self.refresh()

    def _cc(self) -> None:
        name = QLineEdit()

        def ok():
            with self.ctx.db.session_scope() as s:
                fin.save_cost_center(s, name.text())
        form_dialog(self, "Novo centro de custo", [("Nome *", name)], ok)


class FinancePage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(10)
        root.addWidget(title_block("Financeiro", "Contas a pagar e receber, fluxo de caixa e resultado estimado"))
        self.tabs = QTabWidget()
        self.tab_list = [("Resumo", SummaryTab(ctx)), ("A pagar", BillsTab(ctx, "P")), ("A receber", BillsTab(ctx, "R")),
                         ("Fluxo de caixa", FlowTab(ctx)), ("Lançamentos", TransactionsTab(ctx)),
                         ("Contas e categorias", RegistryTab(ctx))]
        for name, w in self.tab_list:
            self.tabs.addTab(w, name)
        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda *_: self.refresh())

    def refresh(self) -> None:
        self.tab_list[self.tabs.currentIndex()][1].refresh()
