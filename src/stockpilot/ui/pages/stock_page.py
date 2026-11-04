from __future__ import annotations

from ..theme import color_positive, color_negative, color_inactive

from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMenu,
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout,
)

from ...domain.enums import MovementType
from ...domain.formatting import format_cost, format_datetime_local, format_qty
from ...models import utcnow
from ...services import product_service, stock_analytics, stock_service
from ..barcode import ScanDetector
from ..common import SortItem, confirm, danger, make_table, primary, run_action, title_block, toast
from ..dialogs.movement_dialog import MovementDialog
from .base import Page

HEADERS = ["Data/hora", "Produto", "Tipo", "Quantidade", "Saldo após", "Custo unit.", "Origem",
           "Motivo", "Usuário", "Situação"]


class StockPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)
        root.addWidget(title_block("Estoque", "Movimentações, ajustes e inventário — o histórico nunca é apagado"))

        from .dashboard_page import KpiCard, kpi_strip
        self.k_value = KpiCard("Valor em estoque (custo)")
        self.k_low = KpiCard("Abaixo do mínimo")
        self.k_zero = KpiCard("Sem saldo")
        self.k_stale = KpiCard(f"Parados há {stock_analytics.STALE_DAYS}+ dias")
        root.addWidget(kpi_strip("Situação do estoque", "Produtos ativos", [self.k_value, self.k_low, self.k_zero, self.k_stale]))

        bar = QHBoxLayout()
        self.b_in = primary(QPushButton("＋ Entrada"))
        self.b_out = QPushButton("− Saída")
        self.b_adj = QPushButton("Ajuste")
        self.b_inv = QPushButton("Inventário")
        self.b_lot = QPushButton("Em lote")
        self.b_lot.setToolTip("Entrada, saída ou inventário de vários produtos de uma vez, com o leitor")
        lot_menu = QMenu(self.b_lot)
        lot_menu.addAction("Entrada em lote…", lambda: self._batch("entrada"))
        lot_menu.addAction("Saída em lote…", lambda: self._batch("saida"))
        lot_menu.addAction("Inventário em lote…", lambda: self._batch("inventario"))
        self.b_lot.setMenu(lot_menu)
        self.b_repl = QPushButton("Reposição sugerida…")
        self.b_repl.setToolTip("O que repor, quanto e por quê — com base no giro real")
        self.b_rev = danger(QPushButton("Estornar selecionada"))
        for b in (self.b_in, self.b_out, self.b_adj, self.b_inv, self.b_lot, self.b_repl):
            bar.addWidget(b)
        bar.addStretch()
        bar.addWidget(self.b_rev)
        root.addLayout(bar)

        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar por produto (nome ou código)…")
        self.search.setClearButtonEnabled(True)
        self.type = QComboBox()
        self.type.addItem("Todos os tipos", None)
        for t in MovementType:
            self.type.addItem(t.label, t.value)
        self.period = QComboBox()
        for label, days in (("Últimos 7 dias", 7), ("Últimos 30 dias", 30), ("Últimos 90 dias", 90), ("Todo o período", None)):
            self.period.addItem(label, days)
        self.period.setCurrentIndex(1)
        f.addWidget(self.search, 1)
        f.addWidget(self.type)
        f.addWidget(self.period)
        root.addLayout(f)

        self.table = make_table(HEADERS, {0: 135, 2: 85, 3: 95, 4: 92, 5: 95, 7: 150, 8: 105}, stretch=(1,))
        self.table.empty_text = "Nenhuma movimentação no período e filtros selecionados"
        root.addWidget(self.table, 1)
        self.count = QLabel("")
        self.count.setObjectName("pageSub")
        root.addWidget(self.count)

        self.b_in.clicked.connect(lambda: self._move("entrada"))
        self.b_out.clicked.connect(lambda: self._move("saida"))
        self.b_adj.clicked.connect(lambda: self._move("ajuste"))
        self.b_inv.clicked.connect(lambda: self._move("inventario"))
        self.b_rev.clicked.connect(self.reverse_selected)
        self.scanned_pid = None
        self.search.textEdited.connect(lambda *_: setattr(self, "scanned_pid", None))
        self.scanner = ScanDetector(self, self.on_scan)
        self.b_repl.clicked.connect(self._replenish)
        from PySide6.QtCore import QTimer
        self._debounce = QTimer(self, singleShot=True, interval=220)  # busca sem travar a cada tecla
        self._debounce.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda *_: self._debounce.start())
        self.type.currentIndexChanged.connect(self.refresh)
        self.period.currentIndexChanged.connect(self.refresh)

    def on_scan(self, code: str, _src=None) -> None:
        """Leitura na tela de estoque: filtra o histórico do produto e o deixa pré-selecionado nas operações."""
        with self.ctx.db.session_scope() as s:
            p = product_service.find_by_barcode(s, code, include_inactive=True)
            info = (p.id, p.internal_code, p.name, format_qty(p.quantity_on_hand, p.allows_fraction)) if p else None
        if not info:
            self.scanned_pid = None
            toast(self, f"Código {code} não cadastrado. Cadastre o produto em Produtos.", "warning")
            return
        self.scanned_pid, icode, name, qty = info
        self.search.setText(icode)
        self.search.setFocus()
        self.search.selectAll()
        toast(self, f"{name}: estoque {qty}. Entrada, Saída, Ajuste e Inventário já abrem com este produto.")

    def _move(self, kind: str) -> None:
        pid = getattr(self, "scanned_pid", None)
        if MovementDialog(self.ctx, kind, pid, self).exec():
            self.refresh()

    def _batch(self, kind: str = "inventario") -> None:
        from ..dialogs.inventory_dialog import InventoryDialog
        dlg = InventoryDialog(self.ctx, self, kind=kind)
        if dlg.exec():
            self.refresh()
            toast(self, f"{dlg.windowTitle()}: {dlg.applied} produto(s) lançado(s).")

    def _replenish(self) -> None:
        from ..dialogs.replenishment_dialog import ReplenishmentDialog
        ReplenishmentDialog(self.ctx, self).exec()
        self.refresh()

    def _refresh_overview(self) -> None:
        from ...domain.formatting import format_brl
        with self.ctx.db.session_scope() as s:
            o = stock_analytics.overview(s)
        self.k_value.set(format_brl(o.value_at_cost), f"{o.active_products} produtos ativos")
        self.k_low.set(str(o.below_min), "Ainda têm saldo, mas no mínimo ou abaixo", note_tone="warn" if o.below_min else "")
        self.k_zero.set(str(o.out_of_stock), "Saldo zerado ou negativo", tone="negative" if o.out_of_stock else "")
        self.k_stale.set(str(o.stale), "Com saldo e sem nenhuma movimentação")

    def refresh(self) -> None:
        self._refresh_overview()
        days = self.period.currentData()
        start = utcnow() - timedelta(days=days) if days else None
        mtype = MovementType(self.type.currentData()) if self.type.currentData() else None
        with self.ctx.db.session_scope() as s:
            movs = stock_service.history(s, start=start, types=[mtype] if mtype else None,
                                         text=self.search.text(), limit=1000)
            reversed_ids = {m.reverses_movement_id for m in movs if m.reverses_movement_id}
            rows = [(m.id, m.created_at, m.product.internal_code + " — " + m.product.name, m.movement_type,
                     m.quantity_delta, m.balance_after, m.unit_cost, m.origin.label, m.reason or "",
                     m.user.full_name if m.user else "", m.reverses_movement_id, m.product.allows_fraction)
                    for m in movs]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, (mid, dt, prod, mt, delta, bal, cost, origin, reason, user, rev_of, frac) in enumerate(rows):
            situ = f"Estorno da mov. #{rev_of}" if rev_of else ("Estornada" if mid in reversed_ids else "")
            items = [
                SortItem(format_datetime_local(dt), mid), SortItem(prod), SortItem(mt.label),
                SortItem(("+" if delta > 0 else "") + format_qty(delta, frac), delta, True),
                SortItem(format_qty(bal, frac), bal, True), SortItem(format_cost(cost), cost or 0, True),
                SortItem(origin), SortItem(reason), SortItem(user), SortItem(situ),
            ]
            for c, it in enumerate(items):
                t.setItem(r, c, it)
            t.item(r, 0).setData(Qt.UserRole, (mid, mt.value, mid in reversed_ids))
            items[3].setForeground(color_positive() if delta > 0 else color_negative())
            if situ:
                for it in items:
                    it.setForeground(color_inactive())
        t.sortByColumn(0, Qt.DescendingOrder)
        t.setSortingEnabled(True)
        self.count.setText(f"{len(rows)} movimentação(ões) exibida(s). Máximo de 1.000 por consulta — use os filtros.")

    def reverse_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Selecione uma movimentação", "Clique em uma movimentação da lista primeiro.")
            return
        mid, mtype, already = self.table.item(row, 0).data(Qt.UserRole)
        if mtype == MovementType.ESTORNO.value:
            QMessageBox.information(self, "Não permitido", "Um estorno não pode ser estornado.")
            return
        if already:
            QMessageBox.information(self, "Já estornada", "Esta movimentação já foi estornada.")
            return
        reason, ok = QInputDialog.getText(self, "Estornar movimentação",
                                          f"Informe o motivo do estorno da movimentação #{mid}:")
        if not ok:
            return
        if not confirm(self, "Confirmar estorno",
                       f"Será criada uma movimentação inversa para a #{mid}.\n"
                       "A original permanece no histórico.", "Estornar"):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                stock_service.reverse_movement(s, mid, reason, self.ctx.current_user_id)
        if run_action(self, work):
            self.refresh()
