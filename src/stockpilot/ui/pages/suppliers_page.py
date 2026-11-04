from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QVBoxLayout

from ...domain.validators import format_cnpj, format_cpf
from ...services import supplier_service
from ..common import SortItem, make_table, primary, title_block
from ..dialogs.supplier_dialog import SupplierDialog
from .base import Page


class SuppliersPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)
        root.addWidget(title_block("Fornecedores", "Cadastro de quem vende mercadoria para você"))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nome, documento ou telefone…")
        self.search.setClearButtonEnabled(True)
        self.inactive = QCheckBox("Mostrar inativos")
        self.b_new = primary(QPushButton("＋ Novo fornecedor"))
        self.b_edit = QPushButton("Editar")
        bar.addWidget(self.search, 1)
        bar.addWidget(self.inactive)
        bar.addWidget(self.b_edit)
        bar.addWidget(self.b_new)
        root.addLayout(bar)
        self.table = make_table(["Nome", "CPF/CNPJ", "Telefone", "E-mail", "Situação"], {1: 150, 2: 130, 4: 80},
                                stretch=(0, 3))
        self.table.empty_text = "Nenhum fornecedor cadastrado — clique em Novo fornecedor"
        root.addWidget(self.table, 1)
        self.search.textChanged.connect(self.refresh)
        self.inactive.toggled.connect(self.refresh)
        self.b_new.clicked.connect(lambda: self._open(None))
        self.b_edit.clicked.connect(self._edit)
        self.table.doubleClicked.connect(lambda *_: self._edit())

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            rows = [(x.id, x.name, x.document or "", x.phone or "", x.email or "", x.active)
                    for x in supplier_service.list_suppliers(s, self.search.text(), only_active=not self.inactive.isChecked())]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, (sid, name, doc, phone, email, active) in enumerate(rows):
            d = format_cpf(doc) if len(doc) == 11 else format_cnpj(doc) if doc else ""
            for c, v in enumerate((name, d, phone, email, "Ativo" if active else "Inativo")):
                t.setItem(r, c, SortItem(v))
            t.item(r, 0).setData(Qt.UserRole, sid)
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.AscendingOrder)

    def _selected_id(self):
        r = self.table.currentRow()
        return None if r < 0 else self.table.item(r, 0).data(Qt.UserRole)

    def _edit(self) -> None:
        sid = self._selected_id()
        if sid is None:
            QMessageBox.information(self, "Selecione um fornecedor", "Clique em um fornecedor da lista primeiro.")
            return
        self._open(sid)

    def _open(self, sid) -> None:
        with self.ctx.db.session_scope() as s:
            sup = next((x for x in supplier_service.list_suppliers(s, only_active=False) if x.id == sid), None) if sid else None
            if sup is not None:
                s.expunge(sup)
        if SupplierDialog(self.ctx, sup, self).exec():
            self.refresh()
