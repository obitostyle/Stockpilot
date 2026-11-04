"""Reposição sugerida: o que comprar, quanto e por quê — e um clique para dar entrada."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox,
    QTableWidgetItem, QVBoxLayout,
)

from ...domain.formatting import format_qty, parse_decimal_br
from ...services import stock_analytics as sa
from ..common import SortItem, make_table, primary, run_action, toast
from ..delegates import LEVEL_ROLE, PILL_ROLE

COLS = ["Código", "Produto", "Saldo", "Mínimo", "Saídas/dia", "Cobertura", "Motivo", "Sugerido"]
SUG = 7


class ReplenishmentDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Reposição sugerida")
        self.setMinimumSize(980, 600)
        lay = QVBoxLayout(self)
        hint = QLabel(sa.CRITERIOS)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        opts = QHBoxLayout()
        self.days = QSpinBox()
        self.days.setRange(7, 365)
        self.days.setValue(30)
        self.days.setSuffix(" dias")
        self.cover = QSpinBox()
        self.cover.setRange(7, 180)
        self.cover.setValue(30)
        self.cover.setSuffix(" dias")
        opts.addWidget(QLabel("Analisar saídas dos últimos"))
        opts.addWidget(self.days)
        opts.addSpacing(16)
        opts.addWidget(QLabel("Repor para cobrir"))
        opts.addWidget(self.cover)
        opts.addStretch()
        lay.addLayout(opts)

        self.table = make_table(COLS, {0: 90, 2: 110, 3: 75, 4: 90, 5: 95, 6: 150, 7: 95}, stretch=(1,))
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.empty_text = "Nenhum produto precisa de reposição pelos critérios acima"
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setObjectName("pageSub")
        export = QPushButton("Exportar lista (Excel)")
        export.setProperty("role", "ghost")
        self.btn_entry = primary(QPushButton("Dar entrada nos itens…"))
        self.btn_entry.setToolTip("Abre a entrada em lote já preenchida com as quantidades sugeridas")
        close = QPushButton("Fechar")
        row.addWidget(self.summary, 1)
        row.addWidget(export)
        row.addWidget(close)
        row.addWidget(self.btn_entry)
        lay.addLayout(row)

        self.days.valueChanged.connect(self.load)
        self.cover.valueChanged.connect(self.load)
        export.clicked.connect(self._export)
        self.btn_entry.clicked.connect(self._entry)
        close.clicked.connect(self.reject)
        self.load()

    def load(self) -> None:
        with self.ctx.db.session_scope() as s:
            self.items = sa.replenishment(s, self.days.value(), self.cover.value())
        t = self.table
        t.setUpdatesEnabled(False)
        t.setSortingEnabled(False)
        t.setRowCount(len(self.items))
        for r, sg in enumerate(self.items):
            it = sg.item
            saldo = SortItem(format_qty(it.quantity, it.allows_fraction), it.quantity, True)
            saldo.setData(LEVEL_ROLE, (float(it.quantity), float(it.min_stock)))
            cover = "—" if it.cover_days is None else f"{format_qty(it.cover_days, True)} d"
            why = SortItem(sg.reason)
            why.setData(PILL_ROLE, "danger" if it.quantity <= 0 else "warn")
            cells = [SortItem(it.code), SortItem(it.name), saldo,
                     SortItem(format_qty(it.min_stock, it.allows_fraction), it.min_stock, True),
                     SortItem(format_qty(it.avg_daily, True), it.avg_daily, True),
                     SortItem(cover, it.cover_days if it.cover_days is not None else Decimal(10**9), True), why]
            for c, cell in enumerate(cells):
                cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                t.setItem(r, c, cell)
            q = QTableWidgetItem(format_qty(sg.suggested, it.allows_fraction))
            q.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            q.setToolTip("Clique duas vezes para mudar a quantidade antes de dar entrada")
            t.setItem(r, SUG, q)
        t.setUpdatesEnabled(True)
        zero = sum(1 for s in self.items if s.item.quantity <= 0)
        self.summary.setText(f"{len(self.items)} produto(s) para repor — {zero} sem saldo")
        self.btn_entry.setEnabled(bool(self.items))

    def selected_lines(self) -> list[tuple[int, Decimal, Decimal | None]]:
        out = []
        for r, sg in enumerate(self.items):
            try:
                q = parse_decimal_br(self.table.item(r, SUG).text().strip() or "0")
            except ValueError:
                raise ValueError(f"Quantidade inválida para {sg.item.name}.")
            if q > 0:
                out.append((sg.item.product_id, q, None))
        return out

    def _entry(self) -> None:
        from .inventory_dialog import InventoryDialog
        try:
            lines = self.selected_lines()
        except ValueError as exc:
            QMessageBox.warning(self, "Quantidade inválida", str(exc))
            return
        dlg = InventoryDialog(self.ctx, self, kind="entrada", preset=lines)
        dlg.reason.setText("Reposição de estoque")
        if dlg.exec():
            toast(self, f"Entrada lançada para {dlg.applied} produto(s).")
            self.load()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar reposição", str(Path.home() / "reposicao.xlsx"),
                                              "Planilha Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        def work():
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Reposição"
            ws.append(["Código", "Produto", "Saldo", "Mínimo", "Saídas/dia", "Cobertura (dias)", "Motivo", "Quantidade sugerida"])
            for r, sg in enumerate(self.items):
                it = sg.item
                ws.append([it.code, it.name, float(it.quantity), float(it.min_stock), float(it.avg_daily),
                           float(it.cover_days) if it.cover_days is not None else None, sg.reason,
                           float(parse_decimal_br(self.table.item(r, SUG).text() or "0"))])
            ws.column_dimensions["B"].width = 42
            wb.save(path)
            toast(self, "Lista de reposição exportada.")
        run_action(self, work)
