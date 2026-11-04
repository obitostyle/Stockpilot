from __future__ import annotations

from ..barcode import ScanDetector
from ..common import toast

from ..theme import color_inactive

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTabWidget, QVBoxLayout, QWidget)

from ...domain.enums import SaleStatus, UserRole
from ...domain.errors import DiscountNotAuthorizedError
from ...domain.formatting import format_brl, format_date, format_qty
from ...models import User
from ...services import company_service, product_service, sales_service as ss
from ...services.sales_service import CartItem
from ..common import SortItem, card, confirm, danger, make_table, primary, read_decimal, run_action, title_block
from ..dialogs.sale_dialogs import PaymentDialog, ReceiptDialog, ReturnDialog
from ..widgets import ProductPicker, money_edit
from .base import Page


class SalesPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(10)
        root.addWidget(title_block("Vendas (PDV)", "Venda no balcão com baixa automática do estoque — comprovante interno, sem valor fiscal"))
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_pdv(), "Nova venda")
        self.tabs.addTab(self._build_history(), "Histórico")
        self.tabs.currentChanged.connect(lambda *_: self.refresh())
        QShortcut(QKeySequence("F2"), self, activated=self.finalize)

    # ------------------------------------------------------------ PDV
    def _build_pdv(self) -> QWidget:
        self.cart: list[dict] = []   # {id, name, frac, qty, disc, price}
        w = QWidget()
        lay = QVBoxLayout(w)
        self.picker = ProductPicker(self.ctx, placeholder="Leia o código de barras ou digite o nome e tecle Enter…")
        lay.addWidget(self.picker)
        self.b_add = QPushButton("Adicionar o produto selecionado")
        lay.addWidget(self.b_add, 0, Qt.AlignLeft)
        self.table = make_table(["Produto", "Qtd", "Preço unit.", "Desconto", "Total"], {1: 80, 2: 100, 3: 100, 4: 110}, stretch=(0,))
        self.table.empty_text = "Carrinho vazio — leia o código de barras ou busque o produto acima"
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_qty, self.b_idisc = QPushButton("Alterar quantidade"), QPushButton("Desconto do item")
        self.b_rm = QPushButton("Remover item")
        self.b_clear = danger(QPushButton("Limpar venda"))
        for b in (self.b_qty, self.b_idisc, self.b_rm):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.b_clear)
        lay.addLayout(row)
        c = card()
        cl = QHBoxLayout(c)
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Cliente (obrigatório para venda a prazo)")
        self.sale_disc = money_edit("Desconto geral em R$ (opcional)")
        self.total_lbl = QLabel("R$ 0,00")
        self.total_lbl.setObjectName("kpiValue")
        self.info = QLabel("")
        self.info.setObjectName("kpiNote")
        self.b_fin = primary(QPushButton("Finalizar venda (F2)"))
        left = QVBoxLayout()
        left.addWidget(self.customer)
        left.addWidget(self.sale_disc)
        left.addWidget(self.info)
        cl.addLayout(left, 2)
        cl.addStretch()
        right = QVBoxLayout()
        right.addWidget(self.total_lbl, 0, Qt.AlignRight)
        right.addWidget(self.b_fin)
        cl.addLayout(right)
        lay.addWidget(c)
        self.picker.chosen.connect(self._add_by_id)
        self.picker.not_found.connect(
            lambda c: toast(self, f"Código {c} não cadastrado. Cadastre o produto em Produtos.", "warning"))
        # leitor de código de barras: funciona com o foco em qualquer ponto da venda (carrinho, botões…)
        self._scanner = ScanDetector(self.picker.parentWidget(), lambda code, _src: self.picker.scan(code))
        self.b_add.clicked.connect(lambda: self.picker.current_id() and self._add_by_id(self.picker.current_id()))
        self.b_qty.clicked.connect(self._chg_qty)
        self.b_idisc.clicked.connect(self._chg_disc)
        self.b_rm.clicked.connect(self._rm)
        self.b_clear.clicked.connect(self._clear)
        self.sale_disc.textChanged.connect(self._render)
        self.b_fin.clicked.connect(self.finalize)
        return w

    def _add_by_id(self, pid: int) -> None:
        def work():
            with self.ctx.db.session_scope() as s:
                p = product_service.get_product(s, pid)
                if not p.active:
                    raise_msg = "Produto inativo."
                    QMessageBox.warning(self, "Produto inativo", raise_msg)
                    return
                name, frac, price, stock = f"{p.internal_code} — {p.name}", p.allows_fraction, p.sale_price, p.quantity_on_hand
            for l in self.cart:
                if l["id"] == pid:
                    l["qty"] += Decimal("1")
                    break
            else:
                self.cart.append(dict(id=pid, name=name, frac=frac, qty=Decimal("1"), disc=Decimal("0"), price=price))
            self.picker.clear()
            self.picker.edit.setFocus()
            self._render()
        run_action(self, work)

    def _cur(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione um item", "Clique em um item do carrinho primeiro.")
            return None
        return self.cart[self.table.item(r, 0).data(Qt.UserRole)]

    def _chg_qty(self) -> None:
        l = self._cur()
        if l:
            v, ok = QInputDialog.getText(self, "Quantidade", "Nova quantidade:", text=format_qty(l["qty"], l["frac"]))
            if ok:
                def work():
                    from ...domain.formatting import parse_decimal_br
                    q = parse_decimal_br(v)
                    if q <= 0:
                        raise ValueError
                    l["qty"] = q
                    self._render()
                try:
                    work()
                except Exception:
                    QMessageBox.warning(self, "Quantidade inválida", "Informe um número maior que zero. Exemplo: 2 ou 1,5")

    def _chg_disc(self) -> None:
        l = self._cur()
        if l:
            v, ok = QInputDialog.getText(self, "Desconto do item", "Desconto em R$ neste item:", text="0")
            if ok:
                try:
                    from ...domain.formatting import parse_decimal_br
                    d = parse_decimal_br(v)
                    if d < 0:
                        raise ValueError
                    l["disc"] = d
                    self._render()
                except Exception:
                    QMessageBox.warning(self, "Desconto inválido", "Informe um valor em reais. Exemplo: 2,50")

    def _rm(self) -> None:
        l = self._cur()
        if l:
            self.cart.remove(l)
            self._render()

    def _clear(self) -> None:
        if self.cart and confirm(self, "Limpar venda", "Descartar todos os itens do carrinho?", "Limpar"):
            self.cart.clear()
            self.customer.clear()
            self.sale_disc.clear()
            self._render()

    def _items(self) -> list[CartItem]:
        return [CartItem(l["id"], l["qty"], l["disc"]) for l in self.cart]

    def _render(self) -> None:
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(self.cart))
        sub = Decimal("0")
        for r, l in enumerate(self.cart):
            tot = ss.q2(l["qty"] * l["price"] - l["disc"])
            sub += tot
            for c, v in enumerate((l["name"], format_qty(l["qty"], l["frac"]), format_brl(l["price"]),
                                   format_brl(l["disc"]), format_brl(tot))):
                t.setItem(r, c, SortItem(v, align_right=c > 0))
            t.item(r, 0).setData(Qt.UserRole, r)
        try:
            gd = read_decimal(self.sale_disc, "Desconto")
        except Exception:
            gd = Decimal("0")
        self.total_lbl.setText(format_brl(max(Decimal("0"), sub - gd)))
        self.info.setText(f"{len(self.cart)} item(ns)   •   Subtotal {format_brl(sub)}")

    def finalize(self) -> None:
        if self.tabs.currentIndex() != 0 or not self.cart:
            return

        def prep():
            with self.ctx.db.session_scope() as s:
                return ss.calculate(s, self._items(), read_decimal(self.sale_disc, "Desconto")).total
        box: dict = {}
        if not run_action(self, lambda: box.update(total=prep())):
            return
        dlg = PaymentDialog(box["total"], bool(self.customer.text().strip()), self)
        if not dlg.exec():
            return
        payments = dlg.payments
        authorized = False
        while True:
            try:
                with self.ctx.db.session_scope() as s:
                    sale = ss.finalize_sale(s, self._items(), payments, seller_id=self.ctx.current_user_id,
                                            customer_name=self.customer.text(),
                                            sale_discount=read_decimal(self.sale_disc, "Desconto"),
                                            discount_authorized=authorized)
                    sid, number = sale.id, sale.number
                break
            except DiscountNotAuthorizedError as exc:
                with self.ctx.db.session_scope() as s:
                    u = s.get(User, self.ctx.current_user_id)
                    can = u is not None and u.role in (UserRole.ADMIN, UserRole.GERENTE)
                if can and confirm(self, "Autorizar desconto", f"{exc}\n\nVocê tem permissão para autorizar. Autorizar este desconto?", "Autorizar"):
                    authorized = True
                    continue
                if not can:
                    QMessageBox.warning(self, "Desconto não autorizado", f"{exc}\nPeça a um gerente ou administrador.")
                return
            except Exception as exc:
                if not run_action(self, lambda e=exc: (_ for _ in ()).throw(e)):
                    return
        with self.ctx.db.session_scope() as s:
            c = company_service.get_company(s)
            text = ss.receipt_text(s, sid, (c.trade_name or c.legal_name) if c else "")
        self.cart.clear()
        self.customer.clear()
        self.sale_disc.clear()
        self._render()
        ReceiptDialog(text, self).exec()

    # ------------------------------------------------------------ histórico
    def _build_history(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.h_text = QLineEdit()
        self.h_text.setPlaceholderText("Buscar por número ou cliente…")
        self.h_period = QComboBox()
        for label, d in (("Hoje", 0), ("Últimos 7 dias", 7), ("Últimos 30 dias", 30), ("Todo o período", None)):
            self.h_period.addItem(label, d)
        self.h_period.setCurrentIndex(2)
        self.b_rec, self.b_ret = QPushButton("Comprovante"), QPushButton("Devolução")
        self.b_canc = danger(QPushButton("Cancelar venda"))
        bar.addWidget(self.h_text, 1)
        bar.addWidget(self.h_period)
        for b in (self.b_rec, self.b_ret, self.b_canc):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.h_table = make_table(["Número", "Data", "Cliente", "Total", "Pagamento", "Vendedor", "Situação"],
                                  {0: 85, 1: 95, 3: 105, 4: 140, 5: 110, 6: 95}, stretch=(2,))
        self.h_table.empty_text = "Nenhuma venda no período selecionado"
        lay.addWidget(self.h_table, 1)
        self.h_sum = QLabel("")
        self.h_sum.setObjectName("pageSub")
        lay.addWidget(self.h_sum)
        self.h_text.textChanged.connect(self._load_history)
        self.h_period.currentIndexChanged.connect(self._load_history)
        self.b_rec.clicked.connect(self._receipt)
        self.b_ret.clicked.connect(self._return)
        self.b_canc.clicked.connect(self._cancel)
        return w

    def refresh(self) -> None:
        if self.tabs.currentIndex() == 1:
            self._load_history()
        else:
            self._render()

    def _load_history(self) -> None:
        days = self.h_period.currentData()
        start = None if days is None else date.today() - timedelta(days=days)
        with self.ctx.db.session_scope() as s:
            rows = [(x.id, x.number, x.sale_date, x.customer_name or "", x.total,
                     ", ".join(sorted({p.method.label for p in x.payments})), x.seller.full_name if x.seller else "", x.status)
                    for x in ss.list_sales(s, start=start, text=self.h_text.text())]
        t = self.h_table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        total = Decimal("0")
        for r, (sid, num, d, cust, tot, pay, seller, st) in enumerate(rows):
            if st == SaleStatus.CONCLUIDA:
                total += tot
            for c, it in enumerate([SortItem(num), SortItem(format_date(d), d), SortItem(cust),
                                    SortItem(format_brl(tot), tot, True), SortItem(pay), SortItem(seller), SortItem(st.label)]):
                t.setItem(r, c, it)
                if st == SaleStatus.CANCELADA:
                    it.setForeground(color_inactive())
            t.item(r, 0).setData(Qt.UserRole, (sid, st.value))
        t.setSortingEnabled(True)
        t.sortByColumn(0, Qt.DescendingOrder)
        self.h_sum.setText(f"{len(rows)} venda(s) listada(s) — concluídas somam {format_brl(total)} (antes de devoluções).")

    def _sel(self):
        r = self.h_table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione uma venda", "Clique em uma venda da lista primeiro.")
            return None
        return self.h_table.item(r, 0).data(Qt.UserRole)

    def _receipt(self) -> None:
        sel = self._sel()
        if sel:
            with self.ctx.db.session_scope() as s:
                c = company_service.get_company(s)
                text = ss.receipt_text(s, sel[0], (c.trade_name or c.legal_name) if c else "")
            ReceiptDialog(text, self).exec()

    def _return(self) -> None:
        sel = self._sel()
        if sel:
            if sel[1] != SaleStatus.CONCLUIDA.value:
                QMessageBox.information(self, "Não permitido", "Só é possível devolver itens de venda concluída.")
                return
            if ReturnDialog(self.ctx, sel[0], self).exec():
                self._load_history()

    def _cancel(self) -> None:
        sel = self._sel()
        if not sel:
            return
        reason, ok = QInputDialog.getText(self, "Cancelar venda", "Motivo do cancelamento:")
        if not ok or not confirm(self, "Confirmar cancelamento",
                                 "O estoque e o financeiro da venda serão estornados. O registro continua no histórico.", "Cancelar venda"):
            return

        def work():
            with self.ctx.db.session_scope() as s:
                ss.cancel_sale(s, sel[0], reason, self.ctx.current_user_id)
        if run_action(self, work):
            self._load_history()
