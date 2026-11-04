from __future__ import annotations

from ..theme import color_inactive

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QMessageBox, QPushButton, QVBoxLayout)

from ...domain.enums import PurchaseStatus
from ...domain.formatting import format_brl, format_date
from ...services import purchase_service as ps
from ..common import SortItem, confirm, danger, make_table, primary, run_action, title_block
from ..dialogs.purchase_dialog import PurchaseDialog
from .base import Page


class PurchasesPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)
        root.addWidget(title_block("Compras", "Entrada de mercadoria dos fornecedores — o estoque só muda quando você confirma"))
        bar = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItem("Todas as situações", None)
        for st in PurchaseStatus:
            self.status.addItem(st.label, st.value)
        self.period = QComboBox()
        for label, d in (("Últimos 30 dias", 30), ("Últimos 90 dias", 90), ("Último ano", 365), ("Todo o período", None)):
            self.period.addItem(label, d)
        self.period.setCurrentIndex(1)
        self.b_new = primary(QPushButton("＋ Nova compra"))
        self.b_open = QPushButton("Abrir / editar rascunho")
        self.b_confirm = QPushButton("Confirmar rascunho")
        self.b_cancel = danger(QPushButton("Cancelar compra"))
        bar.addWidget(self.status)
        bar.addWidget(self.period)
        bar.addStretch()
        for b in (self.b_open, self.b_confirm, self.b_cancel, self.b_new):
            bar.addWidget(b)
        root.addLayout(bar)
        self.table = make_table(["Número", "Data", "Fornecedor", "Total", "Pagamento", "Situação"],
                                {0: 90, 1: 95, 3: 110, 4: 150, 5: 100}, stretch=(2,))
        self.table.empty_text = "Nenhuma compra no período — clique em Nova compra para registrar uma entrada"
        root.addWidget(self.table, 1)
        self.status.currentIndexChanged.connect(self.refresh)
        self.period.currentIndexChanged.connect(self.refresh)
        self.b_new.clicked.connect(lambda: self._dlg(None))
        self.b_open.clicked.connect(self._open)
        self.b_confirm.clicked.connect(self._confirm)
        self.b_cancel.clicked.connect(self._cancel)

    def refresh(self) -> None:
        days = self.period.currentData()
        with self.ctx.db.session_scope() as s:
            rows = [(p.id, p.number, p.issue_date, p.supplier.name, p.total,
                     p.payment_method.label + (f" {p.installments}x" if p.installments > 1 else ""), p.status)
                    for p in ps.list_purchases(
                        s, start=date.today() - timedelta(days=days) if days else None,
                        status=PurchaseStatus(self.status.currentData()) if self.status.currentData() else None)]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, (pid, num, d, sup, total, pay, st) in enumerate(rows):
            for c, it in enumerate([SortItem(num), SortItem(format_date(d), d), SortItem(sup),
                                    SortItem(format_brl(total), total, True), SortItem(pay), SortItem(st.label)]):
                t.setItem(r, c, it)
            t.item(r, 0).setData(Qt.UserRole, (pid, st.value))
            if st == PurchaseStatus.CANCELADA:
                for c in range(6):
                    t.item(r, c).setForeground(color_inactive())
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione uma compra", "Clique em uma compra da lista primeiro.")
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _dlg(self, pid) -> None:
        if PurchaseDialog(self.ctx, pid, self).exec():
            self.refresh()

    def _open(self) -> None:
        sel = self._sel()
        if not sel:
            return
        if sel[1] != PurchaseStatus.RASCUNHO.value:
            QMessageBox.information(self, "Compra já fechada",
                                    "Só rascunhos podem ser editados. Compras confirmadas podem ser canceladas (estorno).")
            return
        self._dlg(sel[0])

    def _confirm(self) -> None:
        sel = self._sel()
        if not sel or not confirm(self, "Confirmar compra", "O estoque será atualizado e o financeiro lançado (uma única vez).", "Confirmar"):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                ps.confirm_purchase(s, sel[0], self.ctx.current_user_id)
        if run_action(self, work):
            self.refresh()

    def _cancel(self) -> None:
        sel = self._sel()
        if not sel:
            return
        reason, ok = QInputDialog.getText(self, "Cancelar compra", "Motivo do cancelamento:")
        if not ok or not confirm(self, "Confirmar cancelamento",
                                 "Se a compra estava confirmada, o estoque e o financeiro serão estornados.\n"
                                 "Só é possível se o estoque ainda comportar a devolução.", "Cancelar compra"):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                ps.cancel_purchase(s, sel[0], reason, self.ctx.current_user_id)
        if run_action(self, work):
            self.refresh()
