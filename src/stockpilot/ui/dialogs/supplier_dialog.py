from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from ...domain.validators import format_cnpj, format_cpf
from ...services import supplier_service
from ..common import primary, run_action


class SupplierDialog(QDialog):
    def __init__(self, ctx, supplier=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.sid = supplier.id if supplier else None
        self.setWindowTitle("Editar fornecedor" if supplier else "Novo fornecedor")
        self.setMinimumWidth(500)
        self.name = QLineEdit(supplier.name if supplier else "")
        doc = supplier.document if supplier and supplier.document else ""
        self.doc = QLineEdit(format_cpf(doc) if len(doc) == 11 else format_cnpj(doc) if doc else "")
        self.phone = QLineEdit(supplier.phone or "" if supplier else "")
        self.email = QLineEdit(supplier.email or "" if supplier else "")
        self.addr = QLineEdit(supplier.address or "" if supplier else "")
        self.notes = QPlainTextEdit(supplier.notes or "" if supplier else "")
        self.notes.setFixedHeight(70)
        self.active = QCheckBox("Fornecedor ativo")
        self.active.setChecked(supplier.active if supplier else True)
        form = QFormLayout()
        form.addRow("Nome / Razão social *", self.name)
        form.addRow("CPF ou CNPJ", self.doc)
        form.addRow("Telefone", self.phone)
        form.addRow("E-mail", self.email)
        form.addRow("Endereço", self.addr)
        form.addRow("Observações", self.notes)
        form.addRow("", self.active)
        ok = primary(QPushButton("Salvar"))
        cancel = QPushButton("Cancelar")
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addLayout(row)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)

    def _save(self) -> None:
        def work():
            with self.ctx.db.session_scope() as s:
                supplier_service.save_supplier(
                    s, name=self.name.text(), document=self.doc.text(), phone=self.phone.text(), email=self.email.text(),
                    address=self.addr.text(), notes=self.notes.toPlainText(), active=self.active.isChecked(),
                    supplier_id=self.sid)
        if run_action(self, work):
            self.accept()
