from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QVBoxLayout)

from ...domain.enums import PaymentMethod
from ...domain.formatting import format_brl, format_cost, format_qty
from ...services import product_service, purchase_service as ps, supplier_service
from ...services.purchase_service import PurchaseLine
from ..barcode import ScanDetector
from ..common import SortItem, make_table, primary, read_decimal, run_action, toast
from ..widgets import ProductPicker, date_edit, money_edit, set_date, to_date

METHODS = [PaymentMethod.DINHEIRO, PaymentMethod.PIX, PaymentMethod.DEBITO, PaymentMethod.CREDITO,
           PaymentMethod.OUTRO, PaymentMethod.A_PRAZO]


class PurchaseDialog(QDialog):
    """Cria/edita um RASCUNHO. Só 'Salvar e confirmar' atualiza o estoque (uma única vez)."""

    def __init__(self, ctx, purchase_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.pid = purchase_id
        self.lines: list[dict] = []   # {id, label, frac, qty, cost}
        self.setWindowTitle("Compra de mercadoria")
        self.setMinimumSize(860, 640)

        self.supplier = QComboBox()
        with ctx.db.session_scope() as s:
            for sup in supplier_service.list_suppliers(s):
                self.supplier.addItem(sup.name, sup.id)
        self.issue = date_edit()
        self.picker = ProductPicker(ctx)
        self.qty = money_edit("Quantidade", "1")
        self.cost = money_edit("Custo unit.")
        self.b_add = QPushButton("Adicionar item")
        self.table = make_table(["Produto", "Quantidade", "Custo unit.", "Total"], {1: 100, 2: 110, 3: 110}, stretch=(0,))
        self.b_rm = QPushButton("Remover item selecionado")
        self.discount = money_edit(text="0")
        self.extra = money_edit(text="0")
        self.method = QComboBox()
        for m in METHODS:
            self.method.addItem(m.label, m.value)
        self.parcels = QSpinBox()
        self.parcels.setRange(1, 60)
        self.due = date_edit(date.today() + timedelta(days=30))
        self.notes = QLineEdit()
        self.total_lbl = QLabel("")
        self.total_lbl.setObjectName("sectionTitle")
        self.hint = QLabel("")
        self.hint.setObjectName("pageSub")

        top = QFormLayout()
        top.addRow("Fornecedor *", self.supplier)
        top.addRow("Data da compra", self.issue)
        add = QHBoxLayout()
        add.addWidget(self.picker, 3)
        add.addWidget(self.qty, 1)
        add.addWidget(self.cost, 1)
        add.addWidget(self.b_add)
        pay = QFormLayout()
        pay.addRow("Desconto (R$)", self.discount)
        pay.addRow("Frete/outras despesas (R$)", self.extra)
        pay.addRow("Forma de pagamento", self.method)
        pay.addRow("Parcelas", self.parcels)
        pay.addRow("1º vencimento", self.due)
        pay.addRow("Observações", self.notes)

        self.b_draft = QPushButton("Salvar rascunho")
        self.b_confirm = primary(QPushButton("Salvar e confirmar (atualiza o estoque)"))
        b_cancel = QPushButton("Fechar")
        foot = QHBoxLayout()
        foot.addWidget(self.total_lbl)
        foot.addStretch()
        foot.addWidget(b_cancel)
        foot.addWidget(self.b_draft)
        foot.addWidget(self.b_confirm)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addLayout(add)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.b_rm, 0, Qt.AlignLeft)
        lay.addLayout(pay)
        lay.addWidget(self.hint)
        lay.addLayout(foot)

        self.picker.chosen.connect(self._picked)
        self.picker.not_found.connect(
            lambda c: toast(self, f"Código {c} não cadastrado. Cadastre o produto em Produtos.", "warning"))
        self._scanner = ScanDetector(self, lambda code, _src: self.picker.scan(code))
        self.picker.combo.currentIndexChanged.connect(self._prefill_cost)
        self.b_add.clicked.connect(self._add)
        self.b_rm.clicked.connect(self._remove)
        self.method.currentIndexChanged.connect(self._toggle)
        self.parcels.valueChanged.connect(self._toggle)
        self.discount.textChanged.connect(self._totals)
        self.extra.textChanged.connect(self._totals)
        self.b_draft.clicked.connect(lambda: self._save(False))
        self.b_confirm.clicked.connect(lambda: self._save(True))
        b_cancel.clicked.connect(self.reject)
        if purchase_id:
            self._load()
        self._toggle()
        self._render()

    # -- estado
    def _toggle(self) -> None:
        prazo = self.method.currentData() == PaymentMethod.A_PRAZO.value or self.parcels.value() > 1
        self.due.setEnabled(prazo)
        self.hint.setText("A prazo: gera contas a pagar. À vista: gera saída de caixa na confirmação.")

    def _load(self) -> None:
        with self.ctx.db.session_scope() as s:
            p = ps.get_purchase(s, self.pid)
            i = self.supplier.findData(p.supplier_id)
            if i >= 0:
                self.supplier.setCurrentIndex(i)
            set_date(self.issue, p.issue_date)
            for it in p.items:
                self.lines.append(dict(id=it.product_id, label=f"{it.product.internal_code} — {it.product.name}",
                                       frac=it.product.allows_fraction, qty=it.quantity, cost=it.unit_cost))
            self.discount.setText(str(p.discount))
            self.extra.setText(str(p.extra_expenses))
            self.method.setCurrentIndex(max(0, self.method.findData(p.payment_method.value)))
            self.parcels.setValue(p.installments)
            if p.first_due_date:
                set_date(self.due, p.first_due_date)
            self.notes.setText(p.notes or "")

    def _picked(self, pid: int) -> None:
        i = self.picker.combo.findData(pid)
        if i >= 0:
            self.picker.combo.setCurrentIndex(i)
        self.qty.setFocus()

    def _prefill_cost(self) -> None:
        pid = self.picker.current_id()
        if pid is None:
            return
        with self.ctx.db.session_scope() as s:
            p = product_service.get_product(s, pid)
            if p.cost_price is not None:
                self.cost.setText(format_cost(p.cost_price))

    def _add(self) -> None:
        def work():
            pid = self.picker.current_id()
            if pid is None:
                QMessageBox.information(self, "Escolha um produto", "Busque e selecione um produto.")
                return
            qty = read_decimal(self.qty, "Quantidade", None)
            cost = read_decimal(self.cost, "Custo unitário", None)
            with self.ctx.db.session_scope() as s:
                p = product_service.get_product(s, pid)
                label, frac = f"{p.internal_code} — {p.name}", p.allows_fraction
            if any(l["id"] == pid for l in self.lines):
                QMessageBox.information(self, "Produto já incluído", "Esse produto já está na compra. Remova-o para alterar.")
                return
            self.lines.append(dict(id=pid, label=label, frac=frac, qty=qty, cost=cost))
            self.picker.clear()
            self.cost.clear()
            self.qty.setText("1")
            self._render()
        run_action(self, work)

    def _remove(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.lines.pop(self.table.item(r, 0).data(Qt.UserRole))
            self._render()

    def _render(self) -> None:
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(self.lines))
        for r, l in enumerate(self.lines):
            vals = [l["label"], format_qty(l["qty"], l["frac"]), format_cost(l["cost"]), format_brl(l["qty"] * l["cost"])]
            for c, v in enumerate(vals):
                t.setItem(r, c, SortItem(v, align_right=c > 0))
            t.item(r, 0).setData(Qt.UserRole, r)
        self._totals()

    def _totals(self) -> None:
        sub = sum((l["qty"] * l["cost"] for l in self.lines), Decimal("0"))
        try:
            d = read_decimal(self.discount, "Desconto")
            e = read_decimal(self.extra, "Despesas")
        except Exception:
            self.total_lbl.setText("")
            return
        self.total_lbl.setText(f"Itens: {format_brl(sub)}   •   Total da compra: {format_brl(sub - d + e)}")

    def _save(self, confirm_now: bool) -> None:
        def work():
            lines = [PurchaseLine(l["id"], l["qty"], l["cost"]) for l in self.lines]
            disc, extra = read_decimal(self.discount, "Desconto"), read_decimal(self.extra, "Despesas")
            method = PaymentMethod(self.method.currentData())
            prazo = method == PaymentMethod.A_PRAZO or self.parcels.value() > 1
            with self.ctx.db.session_scope() as s:
                p = ps.save_purchase(s, supplier_id=self.supplier.currentData() or 0, lines=lines,
                                     issue_date=to_date(self.issue), discount=disc, extra_expenses=extra,
                                     payment_method=method, installments=self.parcels.value(),
                                     first_due_date=to_date(self.due) if prazo else None, notes=self.notes.text(),
                                     user_id=self.ctx.current_user_id, purchase_id=self.pid)
                if confirm_now:
                    ps.confirm_purchase(s, p.id, self.ctx.current_user_id)
        if confirm_now:
            if QMessageBox.question(self, "Confirmar compra",
                                    "Ao confirmar, o estoque é atualizado e o financeiro é lançado.\n"
                                    "Isso só acontece uma vez. Continuar?") != QMessageBox.Yes:
                return
        if run_action(self, work):
            self.accept()
