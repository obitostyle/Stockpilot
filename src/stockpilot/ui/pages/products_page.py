from __future__ import annotations

from ..theme import color_negative, color_inactive

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ...domain.formatting import format_brl, format_cost, format_percent, format_qty
import logging

from ...domain.errors import NotFoundError
from ...services import product_service

log = logging.getLogger("stockpilot.ui")
from ..common import SortItem, confirm, danger, make_table, primary, run_action, title_block, toast
from ..barcode import ScanDetector, looks_like_barcode, normalize_scan
from ..delegates import LEVEL_ROLE
from ..icons import action_icon
from ..theme import DANGER, MUTED, TEXT
from ..dialogs.movement_dialog import MovementDialog
from ..dialogs.product_dialog import ProductDialog
from .base import Page

HEADERS = ["Código", "Produto", "Cód. barras", "Categoria", "Estoque", "Mínimo",
           "Custo médio", "Preço venda", "Margem", "Situação"]
WIDTHS = {0: 92, 2: 125, 3: 110, 4: 110, 5: 75, 6: 110, 7: 105, 8: 75, 9: 80}


class ProductsPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(title_block("Produtos", "Cadastro e consulta de produtos e saldos"), 1)
        self._top = top
        self.btn_new = primary(QPushButton("Novo produto"))
        self.btn_new.setIcon(action_icon("plus", "#FFFFFF"))  # branco sobre o azul primário
        self.btn_new.setToolTip("Cadastrar produto (Ctrl+N)")
        top.addWidget(self.btn_new)
        root.addLayout(top)

        f = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Pesquisar ou ler o código de barras com o leitor…")
        self.search.setClearButtonEnabled(True)
        self.category = QComboBox()
        self.only_active = QCheckBox("Somente ativos")
        self.only_active.setChecked(True)
        self.only_low = QCheckBox("Estoque baixo")
        self.only_zero = QCheckBox("Sem saldo")
        f.addWidget(self.search, 1)
        f.addWidget(QLabel("Categoria:"))
        f.addWidget(self.category)
        f.addWidget(self.only_active)
        f.addWidget(self.only_low)
        f.addWidget(self.only_zero)
        root.addLayout(f)

        # resultado da leitura do código de barras (encontrado / não cadastrado)
        sb = QHBoxLayout()
        sb.setSpacing(10)
        self.scan_status = QLabel("")
        self.scan_status.setObjectName("scanStatus")
        self.btn_register_code = primary(QPushButton("Cadastrar com este código"))
        self.btn_register_code.hide()
        sb.addWidget(self.scan_status)
        sb.addWidget(self.btn_register_code)
        sb.addStretch()
        self.scan_row = QWidget()
        self.scan_row.setLayout(sb)
        sb.setContentsMargins(0, 0, 0, 0)
        self.scan_row.hide()
        root.addWidget(self.scan_row)

        self.table = make_table(HEADERS, WIDTHS)
        root.addWidget(self.table, 1)

        b = QHBoxLayout()
        self.count = QLabel("")
        self.count.setObjectName("pageSub")
        self.btn_edit = QPushButton("Editar")
        self.btn_edit.setIcon(action_icon("edit", MUTED, TEXT))
        self.btn_delete = danger(QPushButton("Excluir"))
        self.btn_delete.setIcon(action_icon("trash", DANGER))
        self.btn_delete.setToolTip("Excluir o produto selecionado (Delete)")
        self.btn_toggle = QPushButton("Ativar / Inativar")
        self.btn_entry = QPushButton("Entrada")
        self.btn_export = QPushButton("Exportar")
        self.btn_export.setToolTip("Exportar a lista para Excel")
        self.btn_import = QPushButton("Importar…")
        self.btn_import.setToolTip("Importar produtos de uma planilha Excel")
        b.addWidget(self.count, 1)
        for w in (self.btn_entry, self.btn_edit, self.btn_toggle, self.btn_delete):
            b.addWidget(w)
        # ações da página (cabeçalho) separadas das ações do produto selecionado (rodapé)
        for w in (self.btn_import, self.btn_export):
            w.setProperty("role", "ghost")
            self._top.insertWidget(self._top.count() - 1, w)
        self._top.insertSpacing(self._top.count() - 1, 4)
        root.addLayout(b)

        self.btn_new.clicked.connect(lambda: self.new_product())
        self.btn_register_code.clicked.connect(lambda: self.new_product(self._missing_code))
        self.search.returnPressed.connect(self._search_enter)
        self._missing_code = ""
        # leitor: vale com o foco em qualquer ponto da tela (busca, tabela, botões)
        self.scanner = ScanDetector(self, lambda code, _src: self.lookup_barcode(code))
        self.btn_edit.clicked.connect(self.edit_selected)
        self.btn_toggle.clicked.connect(self.toggle_selected)
        self.btn_delete.clicked.connect(self.delete_selected)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        QShortcut(QKeySequence(Qt.Key_Delete), self.table, activated=self.delete_selected)
        self.btn_entry.clicked.connect(self.entry_selected)
        self.btn_export.clicked.connect(self.export)
        self.btn_import.clicked.connect(self.import_sheet)
        self.table.doubleClicked.connect(lambda *_: self.edit_selected())
        from PySide6.QtCore import QTimer
        self._debounce = QTimer(self, singleShot=True, interval=180)  # espera a pessoa parar de digitar
        self._debounce.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda *_: self._debounce.start())
        self.search.textEdited.connect(lambda *_: self.scan_row.isVisible() and self._set_scan('', ''))
        self.category.currentIndexChanged.connect(self.reload)
        self.only_active.toggled.connect(self.reload)
        self.only_low.toggled.connect(self.reload)
        self.only_zero.toggled.connect(self.reload)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.new_product)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: self.search.setFocus())
        self._loading = False

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        # em janelas estreitas, colunas de consulta ocasional saem para o nome do produto respirar
        narrow = self.width() < 1180
        for col in (2, 3):  # Cód. barras, Categoria
            self.table.setColumnHidden(col, narrow)

    # --------------------------------------------------------------- dados
    def refresh(self) -> None:
        self._loading = True
        current = self.category.currentData()
        self.category.clear()
        self.category.addItem("Todas", None)
        with self.ctx.db.session_scope() as s:
            for c in product_service.list_categories(s):
                self.category.addItem(c.name, c.id)
        self.category.setCurrentIndex(max(self.category.findData(current), 0))
        self._loading = False
        self.reload()

    PAGE_LIMIT = 500  # a tela mostra até 500 linhas; a busca encontra entre todos os produtos

    def reload(self) -> None:
        if self._loading:
            return
        self._debounce.stop()
        filters = dict(text=self.search.text(), category_id=self.category.currentData(),
                       only_active=self.only_active.isChecked(), low_stock_only=self.only_low.isChecked(),
                       out_of_stock_only=self.only_zero.isChecked())
        with self.ctx.db.session_scope() as s:
            rows = [
                (p.id, p.internal_code, p.name, p.sku or "", p.barcode or "",
                 p.category.name if p.category else "", p.quantity_on_hand, p.min_stock,
                 p.cost_price, p.sale_price, p.margin_percent, p.active, p.allows_fraction, p.is_low_stock)
                for p in product_service.search_products(s, limit=self.PAGE_LIMIT, **filters)
            ]
            total = len(rows) if len(rows) < self.PAGE_LIMIT else product_service.count_products(s, **filters)
        t = self.table
        filtered = bool(self.search.text().strip() or self.category.currentData() or self.only_low.isChecked()
                        or self.only_zero.isChecked())
        t.empty_text = ("Nenhum produto encontrado com esses filtros" if filtered
                        else "Nenhum produto cadastrado — clique em Novo produto para começar")
        t.setUpdatesEnabled(False)  # evita piscar durante a atualização
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for r, (pid, code, name, sku, bar, cat, qty, mn, cost, sale, mg, active, frac, low) in enumerate(rows):
            items = [
                SortItem(code), SortItem(name), SortItem(bar), SortItem(cat),
                SortItem(format_qty(qty, frac), qty, True), SortItem(format_qty(mn, frac), mn, True),
                SortItem(format_cost(cost), cost, True),
                SortItem(format_brl(sale), sale, True),
                SortItem(format_percent(mg), mg if mg is not None else -10**9, True),
                SortItem("Ativo" if active else "Inativo"),
            ]
            for c, it in enumerate(items):
                t.setItem(r, c, it)
            t.item(r, 0).setData(Qt.UserRole, pid)
            items[4].setData(LEVEL_ROLE, (float(qty), float(mn)))
            if low:
                items[4].setForeground(color_negative())
            if not active:
                for it in items:
                    it.setForeground(color_inactive())
        t.setSortingEnabled(True)
        t.setUpdatesEnabled(True)
        if total > len(rows):
            self.count.setText(f"Mostrando {len(rows)} de {total} produtos. Use a busca, o leitor ou os filtros para achar o restante.")
        else:
            self.count.setText(f"{total} produto(s)")

    def _selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Selecione um produto", "Clique em um produto da lista primeiro.")
            return None
        return self.table.item(row, 0).data(Qt.UserRole)

    # --------------------------------------------------------------- ações
    def new_product(self, barcode: str | None = None) -> None:
        dlg = ProductDialog(self.ctx, None, self, barcode=barcode or None)
        if dlg.exec():
            self.refresh()
            code = normalize_scan(dlg.barcode.text())
            if code:
                self.lookup_barcode(code, registered=True)
            else:
                toast(self, "Produto cadastrado.")

    # ----------------------------------------------------- código de barras
    def _search_enter(self) -> None:
        if looks_like_barcode(self.search.text()):
            self.lookup_barcode(normalize_scan(self.search.text()))

    def _set_scan(self, text: str, tone: str, missing: str = "") -> None:
        self._missing_code = missing
        self.scan_status.setText(text)
        self.scan_status.setProperty("tone", tone)
        self.scan_status.style().unpolish(self.scan_status)
        self.scan_status.style().polish(self.scan_status)
        self.btn_register_code.setVisible(bool(missing))
        self.scan_row.setVisible(bool(text))

    def lookup_barcode(self, code: str, registered: bool = False) -> int | None:
        """Leitura: localiza o produto exato (mesmo inativo) e o seleciona; se não existir, oferece o cadastro."""
        with self.ctx.db.session_scope() as s:
            p = product_service.find_by_barcode(s, code, include_inactive=True)
            info = (p.id, p.internal_code, p.name, p.active, format_qty(p.quantity_on_hand, p.allows_fraction),
                    p.unit.value) if p else None
        for w in (self.search, self.category, self.only_active, self.only_low, self.only_zero):
            w.blockSignals(True)
        self.search.setText(code)
        self.category.setCurrentIndex(0)
        self.only_low.setChecked(False)
        self.only_zero.setChecked(False)
        if info and not info[3]:
            self.only_active.setChecked(False)  # produto inativo também aparece na consulta
        for w in (self.search, self.category, self.only_active, self.only_low, self.only_zero):
            w.blockSignals(False)
        self.reload()
        self.search.setFocus()
        self.search.selectAll()  # a próxima leitura substitui o texto
        if not info:
            self.table.clearSelection()
            self._set_scan(f"Código {code} não cadastrado.", "warn", missing=code)
            return None
        pid, icode, name, active, qty, unit = info
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == pid:
                self.table.selectRow(r)
                self.table.scrollToItem(self.table.item(r, 0))
                break
        verb = "Produto cadastrado" if registered else "Produto encontrado"
        extra = "" if active else " Este produto está inativo."
        self._set_scan(f"{verb}: {name} ({icode}), estoque {qty} {unit}.{extra} "
                       "Use Entrada ou Editar para atualizar.", "ok")
        if registered:
            toast(self, f"Produto '{name}' cadastrado.")
        return pid

    def edit_selected(self) -> None:
        pid = self._selected_id()
        if pid and ProductDialog(self.ctx, pid, self).exec():
            self.refresh()

    def entry_selected(self) -> None:
        pid = self._selected_id()
        if pid and MovementDialog(self.ctx, "entrada", pid, self).exec():
            self.reload()

    def toggle_selected(self) -> None:
        pid = self._selected_id()
        if not pid:
            return
        with self.ctx.db.session_scope() as s:
            p = product_service.get_product(s, pid)
            name, active = p.name, p.active
        verbo = "inativar" if active else "reativar"
        if not confirm(self, "Confirmar", f"Deseja {verbo} o produto '{name}'?\n"
                       "O histórico de movimentações é preservado.", verbo.capitalize()):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                product_service.set_active(s, pid, not active)
        if run_action(self, work):
            self.reload()

    def _context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        if self.table.itemAt(pos) is None:
            return
        m = QMenu(self)
        m.addAction(action_icon("edit", MUTED), "Editar", self.edit_selected)
        m.addAction("Entrada de estoque", self.entry_selected)
        m.addAction("Ativar / Inativar", self.toggle_selected)
        m.addSeparator()
        m.addAction(action_icon("trash", DANGER), "Excluir produto", self.delete_selected)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def delete_selected(self) -> None:
        pid = self._selected_id()
        if not pid:
            return
        try:
            with self.ctx.db.session_scope() as s:
                p = product_service.get_product(s, pid)
                name, active = p.name, p.active
                usage = product_service.product_usage(s, pid)
        except NotFoundError:  # excluído em outra janela
            QMessageBox.warning(self, "Produto não encontrado", "O produto não existe mais. A lista será atualizada.")
            self.reload()
            return
        except Exception:
            log.exception("Falha ao consultar o produto para exclusão")
            QMessageBox.critical(self, "Erro", "Não foi possível consultar o produto. Tente novamente.")
            return
        if usage.has_history:
            # Histórico preservado: o livro de estoque é imutável e vendas/compras/relatórios dependem dele.
            text = (f"O produto '{name}' possui histórico ({usage.describe()}) e não pode ser excluído "
                    "sem comprometer esses registros.")
            if not active:
                QMessageBox.information(self, "Exclusão não permitida", text + "\n\nEle já está inativo.")
                return
            if confirm(self, "Exclusão não permitida", text,
                       "Inativar produto", details="Você pode inativá-lo: ele sai das listas e da venda, "
                       "e todo o histórico continua disponível nos relatórios."):
                def work_inactivate():
                    with self.ctx.db.session_scope() as s:
                        product_service.set_active(s, pid, False)
                if run_action(self, work_inactivate):
                    self.reload()
                    toast(self, f"Produto '{name}' inativado.")
            return
        if not confirm(self, "Excluir produto",
                       f"Tem certeza de que deseja excluir o produto '{name}'?",
                       "Excluir produto", destructive=True,
                       details="Essa ação poderá afetar os registros associados e não pode ser desfeita."):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                product_service.delete_product(s, pid)
        if run_action(self, work):
            self.refresh()
            toast(self, f"Produto '{name}' excluído.")
        else:
            self.reload()

    def export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar produtos", str(Path.home() / "produtos.xlsx"),
                                              "Planilha Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        def work():
            with self.ctx.db.session_scope() as s:
                product_service.export_products_xlsx(s, path)
            QMessageBox.information(self, "Exportação concluída", f"Arquivo gerado:\n{path}")
        run_action(self, work)

    def import_sheet(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from ...services import import_service
        from ..common import run_action
        box = QMessageBox(QMessageBox.Question, "Importar produtos", "Importe produtos de uma planilha Excel (.xlsx).\n"
                          "Se ainda não tem o modelo, baixe-o primeiro.", QMessageBox.NoButton, self)
        b_model = box.addButton("Baixar modelo", QMessageBox.ActionRole)
        b_open = box.addButton("Escolher planilha…", QMessageBox.AcceptRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_model:
            path, _ = QFileDialog.getSaveFileName(self, "Salvar modelo", "modelo_produtos.xlsx", "Excel (*.xlsx)")
            if path:
                run_action(self, lambda: import_service.write_template(path))
            return
        if box.clickedButton() is not b_open:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Escolher planilha", "", "Excel (*.xlsx)")
        if not path:
            return
        out = {}

        def work():
            with self.ctx.db.session_scope() as s:
                out["r"] = import_service.import_products(s, path, self.ctx.current_user_id)
        if not run_action(self, work):
            return
        r = out["r"]
        if r.ok:
            QMessageBox.information(self, "Importação concluída", f"{r.created} produto(s) importado(s).")
            self.reload()
        else:
            msg = "\n".join(r.errors[:25]) + (f"\n… e mais {len(r.errors) - 25} erro(s)." if len(r.errors) > 25 else "")
            QMessageBox.warning(self, "Nada foi importado", "Corrija estes problemas na planilha e tente de novo:\n\n" + msg)
