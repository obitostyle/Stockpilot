"""Movimentação em lote: entrada, saída ou inventário de vários produtos de uma vez.

Pensado para o dia a dia com leitor de código de barras: cada leitura adiciona o produto à lista
(ou soma +1 se ele já estiver nela). Só os produtos lidos/escolhidos entram na tela, então abre
na hora mesmo com dezenas de milhares de produtos cadastrados. Tudo é gravado de uma vez
(tudo ou nada) e com chave única: um clique duplo não duplica o lote.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem,
    QVBoxLayout,
)

from ...domain.formatting import format_cost_plain, format_qty, parse_decimal_br
from ...services import import_service, product_service, stock_service
from ..barcode import ScanDetector
from ..common import SortItem, confirm, make_table, primary, run_action
from ..theme import color_negative, color_positive
from ..widgets import ProductPicker

TITLES = {"entrada": "Entrada em lote", "saida": "Saída em lote", "inventario": "Inventário em lote"}
HINTS = {
    "entrada": "Leia os produtos com o leitor (cada leitura soma 1) ou busque pelo nome. Ajuste a quantidade e, se "
               "quiser, o custo unitário — com custo, o custo médio é recalculado. Tudo é lançado de uma vez.",
    "saida": "Leia os produtos com o leitor (cada leitura soma 1) ou busque pelo nome. Use para perdas, consumo "
             "interno ou transferências. Vendas devem ser feitas no PDV.",
    "inventario": "Conte e leia: cada leitura soma 1 unidade CONTADA, ou digite a contagem. Ao aplicar, o saldo de "
                  "cada produto da lista é acertado para a contagem; as diferenças ficam no histórico.",
}
QTY_COL = 3


class InventoryDialog(QDialog):
    """Mantém o nome usado pela tela de Estoque; `kind` escolhe entrada, saída ou inventário."""

    def __init__(self, ctx, parent=None, kind: str = "inventario",
                 preset: list[tuple[int, Decimal, Decimal | None]] | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self.kind = kind
        self.batch_key = uuid.uuid4().hex  # idempotência do lote inteiro
        self.lines: dict[int, dict] = {}   # pid -> dados da linha (ordem de inserção = ordem da tabela)
        self.setWindowTitle(TITLES[kind])
        self.setMinimumSize(860, 580)
        lay = QVBoxLayout(self)
        h = QLabel(HINTS[kind])
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)

        self.picker = ProductPicker(ctx, placeholder="Leia o código de barras ou digite o nome e tecle Enter…")
        lay.addWidget(self.picker)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("scanStatus")
        self.scan_status.hide()
        lay.addWidget(self.scan_status)

        cols = ["Código", "Produto", "Saldo atual", "Contado" if kind == "inventario" else "Quantidade"]
        if kind == "entrada":
            cols.append("Custo unit. (opcional)")
        cols.append("Diferença" if kind == "inventario" else "Saldo após")
        self.result_col = len(cols) - 1
        self.cost_col = 4 if kind == "entrada" else None
        self.table = make_table(cols, {0: 90, 2: 100, 3: 100, 4: 170, 5: 100}, stretch=(1,))
        self.table.setSortingEnabled(False)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed | QAbstractItemView.SelectedClicked)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.empty_text = "Leia um produto com o leitor ou busque pelo nome para começar"
        lay.addWidget(self.table, 1)

        self.reason = QLineEdit(TITLES[kind])
        self.reason.setPlaceholderText("Motivo / observação")
        lay.addWidget(self.reason)
        row = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setObjectName("pageSub")
        remove = QPushButton("Remover item")
        remove.setToolTip("Remove o item selecionado da lista (Delete)")
        self.ok = primary(QPushButton({"entrada": "Lançar entradas", "saida": "Lançar saídas",
                                       "inventario": "Aplicar contagem"}[kind]))
        self.ok.setAutoDefault(False)
        cancel = QPushButton("Cancelar")
        row.addWidget(self.summary, 1)
        row.addWidget(remove)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)

        self.picker.chosen.connect(lambda pid: self.add_product(pid, from_scan=False))
        self.picker.not_found.connect(lambda c: self._status(f"Código {c} não cadastrado.", "warn"))
        self.scanner = ScanDetector(self, self._on_scan)
        self.table.itemChanged.connect(self._item_changed)
        remove.clicked.connect(self._remove_selected)
        QShortcut(QKeySequence(Qt.Key_Delete), self.table, activated=self._remove_selected)
        self.ok.clicked.connect(self._apply)
        cancel.clicked.connect(self.reject)
        for pid, qty, cost in preset or []:
            self.add_product(pid, from_scan=False, qty=qty, cost=cost)
        self._summary()
        self.picker.edit.setFocus()

    # ------------------------------------------------------------- itens
    def _status(self, text: str, tone: str) -> None:
        self.scan_status.setText(text)
        self.scan_status.setProperty("tone", tone)
        self.scan_status.setVisible(bool(text))
        self.scan_status.style().unpolish(self.scan_status)
        self.scan_status.style().polish(self.scan_status)

    def _on_scan(self, code: str, _src) -> None:
        with self.ctx.db.session_scope() as s:
            p = product_service.find_by_barcode(s, code)
            pid = p.id if p else None
        if pid is None:
            self._status(f"Código {code} não cadastrado.", "warn")
            return
        self.add_product(pid, from_scan=True)

    def add_product(self, pid: int, from_scan: bool, qty: Decimal | None = None, cost: Decimal | None = None) -> None:
        if pid in self.lines:  # mesma leitura de novo: soma 1
            line = self.lines[pid]
            line["qty"] = (line["qty"] or Decimal("0")) + (qty if qty is not None else Decimal("1"))
            self._render_row(pid)
            self._status(f"{line['name']}: {format_qty(line['qty'], line['frac'])} {line['unit']}", "ok")
        else:
            with self.ctx.db.session_scope() as s:
                p = product_service.get_product(s, pid)
                if not p.active:
                    self._status(f"{p.name} está inativo e não pode ser movimentado.", "warn")
                    return
                line = dict(code=p.internal_code, name=p.name, saldo=p.quantity_on_hand, frac=p.allows_fraction,
                            unit=p.unit.value, cost=cost,
                            qty=qty if qty is not None else (Decimal("1") if from_scan else None))
            self.lines[pid] = line
            r = self.table.rowCount()
            self.table.blockSignals(True)
            self.table.insertRow(r)
            self.table.setItem(r, 0, SortItem(line["code"]))
            self.table.item(r, 0).setData(Qt.UserRole, pid)
            self.table.setItem(r, 1, SortItem(line["name"]))
            self.table.setItem(r, 2, SortItem(f"{format_qty(line['saldo'], line['frac'])} {line['unit']}", line["saldo"], True))
            for c in (0, 1, 2):
                self.table.item(r, c).setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            q = QTableWidgetItem("")
            q.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(r, QTY_COL, q)
            if self.cost_col is not None:
                c = QTableWidgetItem("")
                c.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, self.cost_col, c)
            res = SortItem("", 0, True)
            res.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(r, self.result_col, res)
            self.table.blockSignals(False)
            self._render_row(pid)
            self._status(f"{line['name']} adicionado.", "ok")
        row = self._row_of(pid)
        self.table.setCurrentCell(row, QTY_COL)
        self.table.scrollToItem(self.table.item(row, QTY_COL))
        if not from_scan:
            self.table.setFocus()  # digitar a quantidade direto
        else:
            self.picker.clear()
            self.picker.edit.setFocus()
        self._summary()

    def _row_of(self, pid: int) -> int:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == pid:
                return r
        return -1

    def _render_row(self, pid: int) -> None:
        line, r = self.lines[pid], self._row_of(pid)
        self.table.blockSignals(True)
        self.table.item(r, QTY_COL).setText("" if line["qty"] is None else format_qty(line["qty"], line["frac"]))
        if self.cost_col is not None:
            self.table.item(r, self.cost_col).setText("" if line["cost"] is None else format_cost_plain(line["cost"]))
        res = self.table.item(r, self.result_col)
        qty, saldo, frac = line["qty"], line["saldo"], line["frac"]
        if line.get("error"):
            res.setText(line["error"])
            res.setForeground(color_negative())
        elif qty is None:
            res.setText("")
        elif self.kind == "inventario":
            d = qty - saldo
            res.setText(("+" if d > 0 else "") + format_qty(d, frac))
            res.setForeground(color_positive() if d > 0 else color_negative() if d < 0 else res.foreground())
        else:
            after = saldo + qty if self.kind == "entrada" else saldo - qty
            res.setText(format_qty(after, frac))
            res.setForeground(color_negative() if after < 0 else self.table.palette().text())
        self.table.blockSignals(False)

    def _item_changed(self, item) -> None:
        pid = self.table.item(item.row(), 0).data(Qt.UserRole)
        line = self.lines[pid]
        line.pop("error", None)
        text = item.text().strip()
        try:
            v = parse_decimal_br(text) if text else None
        except ValueError:
            line["error"] = "valor inválido"
            v = None
        if item.column() == QTY_COL:
            if v is not None and (v < 0 or (v == 0 and self.kind != "inventario")):
                line["error"] = "quantidade inválida"
            elif v is not None and not line["frac"] and v != v.to_integral_value():
                line["error"] = "use número inteiro"
            line["qty"] = v
        elif item.column() == self.cost_col:
            if v is not None and v < 0:
                line["error"] = "custo inválido"
            line["cost"] = v
        self._render_row(pid)
        self._summary()

    def _remove_selected(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            return
        pid = self.table.item(r, 0).data(Qt.UserRole)
        self.lines.pop(pid, None)
        self.table.removeRow(r)
        self._summary()

    def _summary(self) -> None:
        filled = [l for l in self.lines.values() if l["qty"] is not None]
        bad = sum(1 for l in self.lines.values() if l.get("error"))
        txt = f"{len(self.lines)} produto(s) na lista, {len(filled)} com quantidade"
        if bad:
            txt += f" — {bad} com erro"
        self.summary.setText(txt)

    # ------------------------------------------------------------- gravar
    def _apply(self) -> None:
        if any(l.get("error") for l in self.lines.values()):
            QMessageBox.warning(self, "Corrija a lista", "Há itens com quantidade ou custo inválido (em vermelho).")
            return
        lines = {pid: l for pid, l in self.lines.items() if l["qty"] is not None}
        if not lines:
            QMessageBox.information(self, "Nada a lançar", "Leia ou adicione ao menos um produto e informe a quantidade.")
            return
        reason = self.reason.text().strip() or TITLES[self.kind]
        if self.kind == "saida":
            neg = [l["name"] for l in lines.values() if l["qty"] > l["saldo"]]
            if neg and not confirm(self, "Saldo insuficiente",
                                   "Estes produtos ficariam negativos:\n• " + "\n• ".join(neg[:8]),
                                   "Tentar mesmo assim",
                                   details="Se o sistema não permitir estoque negativo, nada será lançado."):
                return
        total = len(lines)
        if not confirm(self, TITLES[self.kind], f"Lançar {TITLES[self.kind].lower()} de {total} produto(s)?",
                       self.ok.text(), details="A operação é gravada de uma vez e fica no histórico com o seu usuário."):
            return
        box = {}
        uid = self.ctx.current_user_id
        self.ok.setEnabled(False)  # evita clique duplo

        def work():
            with self.ctx.db.session_scope() as s:
                if self.kind == "inventario":
                    box["n"] = import_service.batch_inventory(s, {pid: l["qty"] for pid, l in lines.items()}, uid, reason)
                else:
                    box["n"] = stock_service.batch_move(s, self.kind, {pid: (l["qty"], l["cost"]) for pid, l in lines.items()},
                                                        user_id=uid, reason=reason, batch_key=self.batch_key)
        ok = run_action(self, work)
        self.ok.setEnabled(True)
        if ok:
            self.applied = box["n"]
            self.accept()

    # compatibilidade com a versão anterior (testes/automação)
    @property
    def edits(self):
        return self.lines
