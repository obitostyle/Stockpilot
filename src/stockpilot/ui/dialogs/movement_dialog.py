from __future__ import annotations

import uuid

from decimal import Decimal

from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout,
)
from PySide6.QtCore import Qt

from ...domain.enums import MovementOrigin, MovementType
from ...models import utcnow
from ...domain.formatting import format_qty
from ...services import product_service, stock_service
from ..barcode import ScanDetector
from ..common import confirm, primary, read_decimal, run_action

TITLES = {
    "entrada": "Entrada de mercadoria", "saida": "Saída de mercadoria",
    "ajuste": "Ajuste de estoque", "inventario": "Inventário (contagem física)",
}


class MovementDialog(QDialog):
    def __init__(self, ctx, kind: str, product_id: int | None = None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.setWindowTitle(TITLES[kind])
        self.setMinimumWidth(520)
        self._products: dict[int, tuple[str, Decimal, bool, str]] = {}

        self.product = QComboBox()
        self.product.setEditable(True)
        self.product.setInsertPolicy(QComboBox.NoInsert)
        comp = self.product.completer()
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.balance = QLabel("")
        self.qty = QLineEdit()
        self.cost = QLineEdit()
        self.cost.setPlaceholderText("Opcional — atualiza o custo médio")
        self.reason = QLineEdit()

        qty_label = {"entrada": "Quantidade *", "saida": "Quantidade *",
                     "ajuste": "Ajuste (+ ou −) *", "inventario": "Quantidade contada *"}[kind]
        reason_label = "Motivo *" if kind in ("ajuste", "inventario") else "Motivo / observação"

        form = QFormLayout()
        form.addRow("Produto *", self.product)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("scanStatus")
        self.scan_status.hide()
        form.addRow("", self.scan_status)
        form.addRow("", self.balance)
        form.addRow(qty_label, self.qty)
        if kind == "entrada":
            form.addRow("Custo unitário (R$)", self.cost)
        form.addRow(reason_label, self.reason)
        if kind == "ajuste":
            self.qty.setPlaceholderText("Ex.: -2 para baixar, 3 para acrescentar")

        self.btn = primary(QPushButton("Registrar"))
        cancel = QPushButton("Cancelar")
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(self.btn)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        self.btn.clicked.connect(self._save)
        self.product.currentIndexChanged.connect(self._show_balance)

        self._load_products(product_id)
        self.product.setFocus()
        self.product.setToolTip("Leia o código de barras com o leitor ou digite o nome")
        self.scanner = ScanDetector(self, self._on_scan)
        self.op_key = "mov:" + uuid.uuid4().hex  # a mesma janela nunca grava duas vezes

    def _on_scan(self, code: str, _source) -> None:
        """Leitura do leitor: escolhe o produto exato e leva o foco à quantidade."""
        with self.ctx.db.session_scope() as s:
            p = product_service.find_by_barcode(s, code)
            pid = p.id if p else None
        idx = self.product.findData(pid) if pid is not None else -1
        if idx < 0:
            self.scan_status.setText(f"Código {code} não cadastrado. Cadastre o produto em Produtos.")
            self.scan_status.setProperty("tone", "warn")
            self.product.setCurrentIndex(-1)
            self.product.setCurrentText("")
            self.product.setFocus()
        else:
            self.product.setCurrentIndex(idx)
            self.scan_status.setText(f"Produto encontrado pelo código {code}.")
            self.scan_status.setProperty("tone", "ok")
            self.qty.setFocus()
            self.qty.selectAll()
        self.scan_status.show()
        self.scan_status.style().unpolish(self.scan_status)
        self.scan_status.style().polish(self.scan_status)

    def _load_products(self, preselect: int | None) -> None:
        with self.ctx.db.session_scope() as s:
            for p in product_service.search_products(s, only_active=True):
                self._products[p.id] = (p.name, p.quantity_on_hand, p.allows_fraction, p.unit.value)
                self.product.addItem(f"{p.internal_code} — {p.name}", p.id)
        idx = self.product.findData(preselect) if preselect else -1
        self.product.setCurrentIndex(idx)
        if idx < 0:
            self.product.setCurrentText("")
        self._show_balance()

    def _selected_id(self) -> int:
        pid = self.product.currentData()
        text = self.product.currentText().strip()
        if pid is None or self.product.itemText(self.product.currentIndex()) != text:
            from ...domain.errors import ValidationError
            raise ValidationError("Selecione um produto da lista.")
        return pid

    def _show_balance(self) -> None:
        pid = self.product.currentData()
        if pid in self._products and self.product.itemText(self.product.currentIndex()) == self.product.currentText():
            name, qty, frac, unit = self._products[pid]
            self.balance.setText(f"Saldo atual: {format_qty(qty, frac)} {unit}")
        else:
            self.balance.setText("")

    def _save(self) -> None:
        def work():
            pid = self._selected_id()
            name, current, frac, unit = self._products[pid]
            uid = self.ctx.current_user_id
            reason = self.reason.text().strip() or None
            with_cost = self.cost.text().strip()
            qty = read_decimal(self.qty, "Quantidade", default=None)
            if self.kind in ("ajuste", "inventario"):
                novo = current + qty if self.kind == "ajuste" else qty
                if not confirm(self, "Confirmar operação",
                               f"{TITLES[self.kind]}\n\nProduto: {name}\nSaldo atual: {format_qty(current, frac)} {unit}\n"
                               f"Novo saldo: {format_qty(novo, frac)} {unit}\n\nEsta operação ficará registrada com seu usuário."):
                    return
            if self.kind in ("entrada", "saida"):
                mtype = MovementType.ENTRADA if self.kind == "entrada" else MovementType.SAIDA
                delta = qty if self.kind == "entrada" else -qty
                with self.ctx.db.session_scope() as s:
                    dup = stock_service.recent_similar(s, pid, mtype, delta)
                    ago = int((utcnow() - dup.created_at).total_seconds()) if dup else 0
                if dup and not confirm(self, "Movimentação repetida?",
                                       f"Uma {TITLES[self.kind].lower()} de {format_qty(qty, frac)} {unit} de {name} "
                                       f"foi registrada há {ago} segundo(s).",
                                       "Registrar outra", details="Confirme só se for realmente uma nova movimentação."):
                    return
            self.btn.setEnabled(False)  # evita clique duplo
            with self.ctx.db.session_scope() as s:
                if self.kind == "entrada":
                    cost = read_decimal(self.cost, "Custo unitário") if with_cost else None
                    stock_service.register_entry(s, pid, qty, cost, reason=reason, user_id=uid,
                                                 origin=MovementOrigin.MANUAL, idempotency_key=self.op_key)
                elif self.kind == "saida":
                    stock_service.register_exit(s, pid, qty, reason=reason, user_id=uid, idempotency_key=self.op_key)
                elif self.kind == "ajuste":
                    stock_service.adjust(s, pid, qty, reason or "", uid)
                else:
                    stock_service.inventory_count(s, pid, qty, reason or "", uid)
            self.accept()

        run_action(self, work)
        self.btn.setEnabled(True)
