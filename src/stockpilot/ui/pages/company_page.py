from __future__ import annotations

from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ...domain.enums import TaxRegime
from ...domain.formatting import format_date, parse_date_br
from ...domain.validators import format_cnae, format_cnpj
from ...services import company_service
from ...services.schemas import CompanyInput, build
from ...domain.errors import ValidationError
from ..common import scroll_body, card, primary, run_action, title_block
from .base import Page


class CompanyPage(Page):
    saved = Signal()

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(scroll_body(self))
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)
        root.addWidget(title_block("Empresa", "Dados cadastrais usados nos módulos fiscal e de folha"))

        note = QLabel("A validação do CNPJ confere o <b>formato e os dígitos verificadores</b> (inclui o CNPJ "
                      "alfanumérico). Ela <b>não</b> consulta a situação cadastral na Receita Federal.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        note.setMaximumWidth(980)
        root.addWidget(note)

        box = card()
        box.setMaximumWidth(980)
        grid = QGridLayout(box)
        grid.setContentsMargins(24, 20, 24, 20)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(6)
        self.legal = QLineEdit()
        self.trade = QLineEdit()
        self.cnpj = QLineEdit()
        self.cnpj.setPlaceholderText("00.000.000/0000-00")
        self.ie = QLineEdit()
        self.im = QLineEdit()
        self.address = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.regime = QComboBox()
        self.regime.addItem("(não informado)", None)
        for r in TaxRegime:
            self.regime.addItem(r.label, r.value)
        self.start = QLineEdit()
        self.start.setPlaceholderText("DD/MM/AAAA")
        self.start.setInputMask("00/00/0000;_")
        self.cnae1 = QLineEdit()
        self.cnae1.setPlaceholderText("0000-0/00")
        self.cnae2 = QLineEdit()
        self.cnae2.setPlaceholderText("Separe por vírgula")
        groups = (
            ("Identificação", (("Razão social *", self.legal, 2), ("Nome fantasia", self.trade, 2),
                               ("CNPJ *", self.cnpj, 1), ("Início das atividades", self.start, 1),
                               ("Inscrição estadual", self.ie, 1), ("Inscrição municipal", self.im, 1))),
            ("Enquadramento fiscal", (("Regime tributário", self.regime, 1), ("CNAE principal", self.cnae1, 1),
                                      ("CNAEs secundários", self.cnae2, 2))),
            ("Contato", (("Endereço", self.address, 2), ("Telefone", self.phone, 1), ("E-mail", self.email, 1))),
        )
        row = 0
        for gi, (gname, fields) in enumerate(groups):
            if gi:
                line = QFrame()
                line.setObjectName("hDivider")
                line.setFixedHeight(1)
                grid.addWidget(line, row, 0, 1, 2)
                row += 1
            g = QLabel(gname)
            g.setObjectName("sectionTitle")
            grid.addWidget(g, row, 0, 1, 2)
            row += 1
            col = 0
            for label, w, span in fields:
                if span == 2 and col == 1:
                    row += 2
                    col = 0
                lbl = QLabel(label)
                lbl.setObjectName("formLabel")
                grid.addWidget(lbl, row, col, 1, span)
                grid.addWidget(w, row + 1, col, 1, span)
                col += span
                if col >= 2:
                    col = 0
                    row += 2
            if col:
                row += 2
            grid.setRowMinimumHeight(row, 10)
            row += 1

        self.btn = primary(QPushButton("Salvar dados da empresa"))
        self.btn.clicked.connect(self.save)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.btn)
        grid.addLayout(actions, row, 0, 1, 2)
        root.addWidget(box)
        root.addStretch()

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            c = company_service.get_company(s)
            if c is None:
                return
            self.legal.setText(c.legal_name)
            self.trade.setText(c.trade_name or "")
            self.cnpj.setText(format_cnpj(c.cnpj))
            self.ie.setText(c.state_registration or "")
            self.im.setText(c.municipal_registration or "")
            self.address.setText(c.address or "")
            self.phone.setText(c.phone or "")
            self.email.setText(c.email or "")
            self.regime.setCurrentIndex(max(self.regime.findData(c.tax_regime.value if c.tax_regime else None), 0))
            self.start.setText(format_date(c.activity_start_date))
            prim = [x.code for x in c.cnaes if x.is_primary]
            self.cnae1.setText(format_cnae(prim[0]) if prim else "")
            self.cnae2.setText(", ".join(format_cnae(x.code) for x in c.cnaes if not x.is_primary))

    def save(self) -> None:
        def work():
            try:
                start: date | None = parse_date_br(self.start.text())
            except ValueError:
                raise ValidationError("Início das atividades: data inválida (use DD/MM/AAAA).")
            data = build(
                CompanyInput, legal_name=self.legal.text(), cnpj=self.cnpj.text(), trade_name=self.trade.text(),
                state_registration=self.ie.text(), municipal_registration=self.im.text(),
                address=self.address.text(), phone=self.phone.text(), email=self.email.text(),
                tax_regime=self.regime.currentData(), activity_start_date=start,
                cnae_primary=self.cnae1.text(),
                cnae_secondary=[x.strip() for x in self.cnae2.text().replace(";", ",").split(",")],
            )
            with self.ctx.db.session_scope() as s:
                company_service.save_company(s, data)
            QMessageBox.information(self, "Salvo", "Dados da empresa salvos com sucesso.")
        if run_action(self, work):
            self.saved.emit()
            self.refresh()
