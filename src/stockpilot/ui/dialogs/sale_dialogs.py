from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout)

from ...domain.enums import PaymentMethod
from ...domain.formatting import format_brl, format_qty
from ...services import sales_service
from ...services.sales_service import PaymentInput
from ..common import SortItem, make_table, primary, read_decimal, run_action
from ..widgets import date_edit, money_edit, to_date


class PaymentDialog(QDialog):
    """Coleta os pagamentos (pode misturar formas). Resultado em self.payments."""

    def __init__(self, total: Decimal, customer_known: bool, parent=None):
        super().__init__(parent)
        self.total = total
        self.payments: list[PaymentInput] = []
        self.setWindowTitle("Pagamento")
        self.setMinimumWidth(560)
        self.big = QLabel(f"Total a pagar: {format_brl(total)}")
        self.big.setObjectName("kpiValue")
        self.method = QComboBox()
        for m in PaymentMethod:
            self.method.addItem(m.label, m.value)
        self.amount = money_edit(text=str(total).replace(".", ","))
        self.parcels = QSpinBox()
        self.parcels.setRange(1, 24)
        self.due = date_edit(date.today() + timedelta(days=30))
        self.note = QLineEdit()
        self.note.setPlaceholderText("Qual meio? (somente para 'Outro')")
        self.b_add = QPushButton("Adicionar pagamento")
        self.table = make_table(["Forma", "Valor", "Detalhe"], {1: 110}, stretch=(2,))
        self.table.setMaximumHeight(130)
        self.b_rm = QPushButton("Remover")
        self.status = QLabel("")
        self.status.setObjectName("sectionTitle")
        self.ok = primary(QPushButton("Concluir venda"))
        cancel = QPushButton("Voltar")
        form = QFormLayout()
        form.addRow("Forma", self.method)
        form.addRow("Valor entregue (R$)", self.amount)
        form.addRow("Parcelas", self.parcels)
        form.addRow("Vencimento (a prazo)", self.due)
        form.addRow("", self.note)
        row = QHBoxLayout()
        row.addWidget(self.b_rm)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay = QVBoxLayout(self)
        lay.addWidget(self.big)
        lay.addLayout(form)
        lay.addWidget(self.b_add)
        lay.addWidget(self.table)
        lay.addWidget(self.status)
        lay.addLayout(row)
        self.b_add.clicked.connect(self._add)
        self.b_rm.clicked.connect(self._rm)
        self.ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        self.method.currentIndexChanged.connect(self._toggle)
        self._toggle()
        self._render()

    def _toggle(self) -> None:
        m = self.method.currentData()
        self.parcels.setEnabled(m in (PaymentMethod.CREDITO.value, PaymentMethod.A_PRAZO.value))
        self.due.setEnabled(m == PaymentMethod.A_PRAZO.value)
        self.note.setEnabled(m == PaymentMethod.OUTRO.value)

    def _add(self) -> None:
        def work():
            amt = read_decimal(self.amount, "Valor", None)
            self.payments.append(PaymentInput(PaymentMethod(self.method.currentData()), amt, self.parcels.value() if self.parcels.isEnabled() else 1,
                                              to_date(self.due) if self.due.isEnabled() else None,
                                              self.note.text().strip() or None))
            self._render()
        run_action(self, work)

    def _rm(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.payments.pop(self.table.item(r, 0).data(Qt.UserRole))
            self._render()

    def _render(self) -> None:
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(self.payments))
        for r, p in enumerate(self.payments):
            det = []
            if p.installments > 1:
                det.append(f"{p.installments}x")
            if p.due_date:
                det.append(f"vence {p.due_date:%d/%m/%Y}")
            if p.note:
                det.append(p.note)
            for c, v in enumerate((p.method.label, format_brl(p.amount), ", ".join(det))):
                t.setItem(r, c, SortItem(v, align_right=(c == 1)))
            t.item(r, 0).setData(Qt.UserRole, r)
        paid = sum((p.amount for p in self.payments), Decimal("0"))
        if paid >= self.total:
            self.status.setText(f"Pago: {format_brl(paid)}   •   Troco: {format_brl(paid - self.total)}")
            self.ok.setEnabled(True)
        else:
            rest = self.total - paid
            self.status.setText(f"Pago: {format_brl(paid)}   •   Falta: {format_brl(rest)}")
            self.amount.setText(str(rest).replace(".", ","))
            self.ok.setEnabled(False)


class ReceiptDialog(QDialog):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comprovante interno (não fiscal)")
        self.setMinimumSize(460, 520)
        self.text = text
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        f = QFont("Consolas")
        f.setStyleHint(QFont.Monospace)
        box.setFont(f)
        b_save = QPushButton("Salvar como arquivo de texto…")
        b_close = primary(QPushButton("Fechar"))
        row = QHBoxLayout()
        row.addWidget(b_save)
        row.addStretch()
        row.addWidget(b_close)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addLayout(row)
        b_close.clicked.connect(self.accept)
        b_save.clicked.connect(self._save)

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar comprovante", "comprovante.txt", "Texto (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.text)


class ReturnDialog(QDialog):
    def __init__(self, ctx, sale_id: int, parent=None):
        super().__init__(parent)
        self.ctx, self.sale_id = ctx, sale_id
        self.setWindowTitle("Devolução de itens")
        self.setMinimumSize(640, 440)
        self.rows: list[tuple[int, QLineEdit]] = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Informe a quantidade a devolver de cada item (deixe 0 para os que ficam)."))
        self.table = make_table(["Produto", "Vendido", "Já devolvido", "Devolver agora"], {1: 80, 2: 100, 3: 120}, stretch=(0,))
        lay.addWidget(self.table)
        with ctx.db.session_scope() as s:
            sale = sales_service._load(s, sale_id)
            items = [(i.id, i.product_name, i.quantity, sales_service.returned_quantity(s, i.id), i.product.allows_fraction)
                     for i in sale.items]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        for r, (iid, name, qty, ret, frac) in enumerate(items):
            for c, v in enumerate((name, format_qty(qty, frac), format_qty(ret, frac))):
                self.table.setItem(r, c, SortItem(v, align_right=c > 0))
            e = QLineEdit("0")
            e.setAlignment(Qt.AlignRight)
            self.table.setCellWidget(r, 3, e)
            self.rows.append((iid, e))
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Motivo da devolução *")
        self.restock = QCheckBox("Devolver as mercadorias ao estoque")
        self.restock.setChecked(True)
        ok = primary(QPushButton("Registrar devolução"))
        cancel = QPushButton("Cancelar")
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addWidget(self.reason)
        lay.addWidget(self.restock)
        lay.addLayout(row)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)

    def _save(self) -> None:
        def work():
            lines = []
            for iid, e in self.rows:
                q = read_decimal(e, "Quantidade")
                if q > 0:
                    lines.append((iid, q))
            with self.ctx.db.session_scope() as s:
                sales_service.return_items(s, self.sale_id, lines, self.reason.text(), self.ctx.current_user_id,
                                           restock=self.restock.isChecked())
        if run_action(self, work):
            self.accept()
