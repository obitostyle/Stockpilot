from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from ...domain.enums import UnitOfMeasure
from ...domain.formatting import format_cost_plain, format_percent, format_qty
from ...services import product_service
from ..barcode import ScanDetector, looks_like_barcode, normalize_scan
from ...services.schemas import ProductInput, build
from ..common import primary, read_decimal, run_action


class ProductDialog(QDialog):
    def __init__(self, ctx, product_id: int | None = None, parent=None, barcode: str | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.product_id = product_id
        self.setWindowTitle("Novo produto" if product_id is None else "Editar produto")
        self.setMinimumWidth(760)

        self.name = QLineEdit()
        self.code = QLineEdit()
        self.code.setPlaceholderText("Automático se vazio")
        self.sku = QLineEdit()
        self.barcode = QLineEdit()
        self.barcode.setPlaceholderText("Leia com o leitor ou digite")
        self.barcode.setToolTip("Aponte o leitor para o produto: o código é preenchido sozinho, de qualquer campo.")
        self.barcode.installEventFilter(self)  # Enter neste campo confere o código em vez de salvar
        self.category = QComboBox()
        self.category.setEditable(True)
        self.brand = QLineEdit()
        self.unit = QComboBox()
        for u in UnitOfMeasure:
            self.unit.addItem(u.label, u.value)  # guarda o texto: Qt não preserva enums str
        self.fraction = QCheckBox("Vendido por peso / fração")
        self.cost = QLineEdit()
        self.cost.setPlaceholderText("0,00")
        self.sale = QLineEdit()
        self.sale.setPlaceholderText("0,00")
        self.margin = QLineEdit()
        self.margin.setReadOnly(True)
        self.qty = QLineEdit()
        self.qty.setPlaceholderText("0")
        self.min_stock = QLineEdit()
        self.min_stock.setPlaceholderText("0")
        self.location = QLineEdit()
        self.supplier = QComboBox()
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(64)
        self.active = QCheckBox("Produto ativo")
        self.active.setChecked(True)

        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(8)

        def add(row, col, text, widget, span=1):
            lab = QLabel(text)
            g.addWidget(lab, row, col * 2, alignment=Qt.AlignRight | Qt.AlignVCenter)
            g.addWidget(widget, row, col * 2 + 1, 1, span * 2 - 1 if span > 1 else 1)

        add(0, 0, "Nome *", self.name, span=2)
        add(1, 0, "Código interno", self.code)
        add(1, 1, "SKU", self.sku)
        add(2, 0, "Código de barras", self.barcode)
        add(2, 1, "Categoria", self.category)
        add(3, 0, "Marca", self.brand)
        add(3, 1, "Unidade", self.unit)
        add(4, 0, "Preço de custo (R$)", self.cost)
        add(4, 1, "Preço de venda (R$)", self.sale)
        add(5, 0, "Margem estimada", self.margin)
        g.addWidget(self.fraction, 5, 3)
        self.qty_label = "Estoque inicial" if product_id is None else "Estoque atual"
        add(6, 0, self.qty_label, self.qty)
        add(6, 1, "Estoque mínimo", self.min_stock)
        add(7, 0, "Localização", self.location)
        add(7, 1, "Fornecedor", self.supplier)
        add(8, 0, "Descrição", self.description, span=2)
        g.addWidget(self.active, 9, 1)
        for col in (1, 3):
            g.setColumnStretch(col, 1)
            g.setColumnMinimumWidth(col, 210)

        self.btn_save = primary(QPushButton("Salvar"))
        self.btn_save.setDefault(True)
        btn_cancel = QPushButton("Cancelar")
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn_cancel)
        row.addWidget(self.btn_save)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("scanStatus")
        self.scan_status.setWordWrap(True)
        self.scan_status.hide()
        lay = QVBoxLayout(self)
        lay.addLayout(g)
        lay.addWidget(self.scan_status)
        lay.addSpacing(8)
        lay.addLayout(row)

        btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save)
        self.unit.currentIndexChanged.connect(self._unit_changed)
        self.cost.textChanged.connect(self._update_margin)
        self.sale.textChanged.connect(self._update_margin)

        self._load()
        self.barcode.textChanged.connect(lambda: self._set_status("", ""))
        self.barcode.editingFinished.connect(self.check_barcode)
        self.scanner = ScanDetector(self, self._on_scan, keep_in=lambda w: w is self.barcode)
        if barcode:
            self.barcode.setText(normalize_scan(barcode))
            self.check_barcode()
        self.name.setFocus()

    # ------------------------------------------------------- código de barras
    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is self.barcode and ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.check_barcode():
                self._focus_next_empty()
            return True
        return super().eventFilter(obj, ev)

    def _on_scan(self, code: str, _source) -> None:
        self.barcode.setText(code)
        if self.check_barcode():
            self._focus_next_empty()
        else:
            self.barcode.setFocus()
            self.barcode.selectAll()

    def _focus_next_empty(self) -> None:
        for w in (self.name, self.cost, self.sale):
            if not w.text().strip():
                w.setFocus()
                return
        self.btn_save.setFocus()

    def _set_status(self, text: str, tone: str) -> None:
        self.scan_status.setText(text)
        self.scan_status.setProperty("tone", tone)
        self.scan_status.setVisible(bool(text))
        self.barcode.setProperty("state", {"error": "error", "ok": "ok"}.get(tone, ""))
        for w in (self.scan_status, self.barcode):
            w.style().unpolish(w)
            w.style().polish(w)

    def check_barcode(self) -> bool:
        """Confere formato e duplicidade na hora. Vazio é permitido (produto sem código de barras)."""
        code = normalize_scan(self.barcode.text())
        if code != self.barcode.text():
            self.barcode.blockSignals(True)
            self.barcode.setText(code)
            self.barcode.blockSignals(False)
        if not code:
            self._set_status("", "")
            return True
        if not looks_like_barcode(code):
            self._set_status("Código de barras inválido: use apenas números (4 a 14 dígitos).", "error")
            return False
        with self.ctx.db.session_scope() as s:
            owner = product_service.barcode_owner(s, code, self.product_id)
            who = f"{owner.internal_code} — {owner.name}" if owner else ""
        if owner:
            self._set_status(f"O código {code} já pertence a {who}. Cada código só pode estar em um produto.", "error")
            return False
        self._set_status(f"Código {code} lido e disponível.", "ok")
        return True

    # ---------------------------------------------------------------- dados
    def _load(self) -> None:
        with self.ctx.db.session_scope() as s:
            for c in product_service.list_categories(s):
                self.category.addItem(c.name)
            self.category.setCurrentIndex(-1)
            self.supplier.addItem("(nenhum)", None)
            for sup in product_service.list_suppliers(s):
                self.supplier.addItem(sup.name, sup.id)
            if self.product_id is None:
                self._unit_changed()
                return
            p = product_service.get_product(s, self.product_id)
            self.name.setText(p.name)
            self.code.setText(p.internal_code)
            self.sku.setText(p.sku or "")
            self.barcode.setText(p.barcode or "")
            self.category.setCurrentText(p.category.name if p.category else "")
            self.brand.setText(p.brand or "")
            self.unit.setCurrentIndex(self.unit.findData(p.unit.value))
            self.fraction.setChecked(p.allows_fraction)
            self.cost.setText(format_cost_plain(p.cost_price))
            self.sale.setText(format_cost_plain(p.sale_price))
            self.qty.setText(format_qty(p.quantity_on_hand, p.allows_fraction))
            self.qty.setReadOnly(True)
            self.qty.setToolTip("O saldo só muda por movimentação de estoque (entrada, saída, ajuste).")
            self.min_stock.setText(format_qty(p.min_stock, p.allows_fraction))
            self.location.setText(p.location or "")
            idx = self.supplier.findData(p.supplier_id)
            self.supplier.setCurrentIndex(max(idx, 0))
            self.description.setPlainText(p.description or "")
            self.active.setChecked(p.active)
        self._update_margin()

    def _unit_changed(self) -> None:
        unit = UnitOfMeasure(self.unit.currentData())
        self.fraction.setChecked(unit.fractional_by_default)

    def _update_margin(self) -> None:
        try:
            cost = read_decimal(self.cost, "custo")
            sale = read_decimal(self.sale, "venda")
        except Exception:
            self.margin.setText("—")
            return
        self.margin.setText(format_percent((sale - cost) / sale * 100) if sale > 0 else "—")

    # ---------------------------------------------------------------- salvar
    def _save(self) -> None:
        def work():
            data = build(
                ProductInput,
                name=self.name.text(), internal_code=self.code.text(), sku=self.sku.text(),
                barcode=self.barcode.text(), category_name=self.category.currentText(),
                brand=self.brand.text(), description=self.description.toPlainText(),
                unit=self.unit.currentData(), allows_fraction=self.fraction.isChecked(),
                cost_price=read_decimal(self.cost, "Preço de custo"),
                sale_price=read_decimal(self.sale, "Preço de venda"),
                min_stock=read_decimal(self.min_stock, "Estoque mínimo"),
                location=self.location.text(), supplier_id=self.supplier.currentData(),
                active=self.active.isChecked(),
            )
            with self.ctx.db.session_scope() as s:
                if self.product_id is None:
                    initial = read_decimal(self.qty, "Estoque inicial")
                    p = product_service.create_product(s, data, initial, self.ctx.current_user_id)
                    self.product_id = p.id
                else:
                    product_service.update_product(s, self.product_id, data)

        if run_action(self, work):
            self.accept()
