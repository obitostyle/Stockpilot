"""Componentes reutilizáveis de formulário."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import QComboBox, QDateEdit, QHBoxLayout, QLineEdit, QWidget

from ..services import product_service
from .common import read_decimal


def date_edit(initial: date | None = None) -> QDateEdit:
    d = QDateEdit()
    d.setDisplayFormat("dd/MM/yyyy")
    d.setCalendarPopup(True)
    d.setDate(QDate(initial.year, initial.month, initial.day) if initial else QDate.currentDate())
    return d


def to_date(d: QDateEdit) -> date:
    q = d.date()
    return date(q.year(), q.month(), q.day())


def set_date(d: QDateEdit, v: date) -> None:
    d.setDate(QDate(v.year, v.month, v.day))


class ProductPicker(QWidget):
    """Campo de busca (nome, código, SKU ou código de barras) + lista de resultados."""
    chosen = Signal(int)   # Enter com resultado único/primeiro ou código de barras exato
    not_found = Signal(str)  # leitura/código de barras que não existe no cadastro

    def __init__(self, ctx, parent=None, placeholder="Digite o nome, código ou leia o código de barras…"):
        super().__init__(parent)
        self.ctx = ctx
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setClearButtonEnabled(True)
        self.combo = QComboBox()
        self.combo.setMinimumWidth(280)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.combo, 1)
        self.edit.textChanged.connect(self._search)
        self.edit.returnPressed.connect(self._enter)
        self._search("")

    def _search(self, text: str) -> None:
        self.combo.clear()
        if not text.strip():
            return
        with self.ctx.db.session_scope() as s:
            for p in product_service.search_products(s, text, limit=30):
                self.combo.addItem(f"{p.internal_code} — {p.name}", p.id)

    def _enter(self) -> None:
        from .barcode import looks_like_barcode, normalize_scan
        text = self.edit.text().strip()
        if not text:
            return
        is_code = looks_like_barcode(text)
        with self.ctx.db.session_scope() as s:
            p = product_service.find_by_barcode(s, normalize_scan(text) if is_code else text)
            pid = p.id if p else None
        if pid is None and is_code:
            # Código de barras sem cadastro: nunca escolhe um produto "parecido" no lugar dele.
            self.edit.selectAll()
            self.not_found.emit(normalize_scan(text))
            return
        if pid is None and self.combo.count():
            pid = self.combo.itemData(0)
        if pid is not None:
            self.chosen.emit(int(pid))

    def scan(self, code: str) -> None:
        """Leitura vinda do leitor quando o foco estava em outro ponto da tela."""
        self.edit.setText(code)
        self.edit.setFocus()
        self._enter()

    def current_id(self) -> int | None:
        v = self.combo.currentData()
        return int(v) if v is not None else None

    def clear(self) -> None:
        self.edit.clear()
        self.combo.clear()


def money_edit(placeholder: str = "0,00", text: str = "") -> QLineEdit:
    e = QLineEdit(text)
    e.setPlaceholderText(placeholder)
    e.setAlignment(Qt.AlignRight)
    return e


def form_dialog(parent, title: str, rows: list[tuple[str, QWidget]], on_ok, ok_text: str = "Salvar",
                hint: str | None = None, min_width: int = 460) -> bool:
    """Diálogo simples de formulário. `on_ok()` faz a ação (via run_action); retorna True se confirmada."""
    from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout
    from .common import primary, run_action
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.setMinimumWidth(min_width)
    lay = QVBoxLayout(d)
    if hint:
        h = QLabel(hint)
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)
    form = QFormLayout()
    for label, w in rows:
        form.addRow(label, w)
    lay.addLayout(form)
    row = QHBoxLayout()
    ok = primary(QPushButton(ok_text))
    cancel = QPushButton("Cancelar")
    row.addStretch()
    row.addWidget(cancel)
    row.addWidget(ok)
    lay.addLayout(row)
    cancel.clicked.connect(d.reject)
    ok.clicked.connect(lambda: d.accept() if run_action(d, on_ok) else None)
    return bool(d.exec())
