"""Fluxos de interface das fases 3-6 (Qt offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from stockpilot.domain.enums import PaymentMethod, TaxRegime  # noqa: E402
from stockpilot.models import Company  # noqa: E402
from stockpilot.services import purchase_service as pus, sales_service as ss, supplier_service  # noqa: E402
from stockpilot.services.purchase_service import PurchaseLine  # noqa: E402
from stockpilot.ui import common  # noqa: E402
from stockpilot.ui.dialogs.sale_dialogs import PaymentDialog  # noqa: E402
from stockpilot.ui.main_window import MainWindow  # noqa: E402
from stockpilot.ui.theme import QSS  # noqa: E402
from tests.conftest import make_product  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(QSS)
    return a


@pytest.fixture()
def msgs(monkeypatch):
    log = []
    for kind in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, _k=kind, **k: log.append((_k, a[2]))))
    return log


def test_todas_as_paginas_abrem_sem_erro(app, ctx, msgs):
    w = MainWindow(ctx)
    for i in range(len(w.pages)):
        w.go(i)
        page = w.stack.currentWidget()
        if hasattr(page, "tabs"):
            for t in range(page.tabs.count()):
                page.tabs.setCurrentIndex(t)
                page.refresh()
    assert not [m for m in msgs if m[0] == "critical"]


def test_pdv_venda_completa_pela_interface(app, ctx, msgs, monkeypatch):
    with ctx.db.session_scope() as s:
        p = make_product(s, ctx.current_user_id, qty="10", name="Caneta", sale_price="5")
        pid = p.id
    w = MainWindow(ctx)
    idx = [n for n, _ in w.pages].index("Vendas (PDV)")
    w.go(idx)
    page = w.stack.currentWidget()
    page._add_by_id(pid)
    page._add_by_id(pid)
    assert page.cart[0]["qty"] == D("2")
    assert page.total_lbl.text() == "R$ 10,00"

    class FakeDlg:
        def __init__(self, total, known, parent=None):
            self.payments = [ss.PaymentInput(PaymentMethod.DINHEIRO, D("20"))]

        def exec(self):
            return QDialog.Accepted
    monkeypatch.setattr("stockpilot.ui.pages.sales_page.PaymentDialog", FakeDlg)
    shown = []
    monkeypatch.setattr("stockpilot.ui.pages.sales_page.ReceiptDialog", lambda text, parent=None: type("R", (), {"exec": lambda self: shown.append(text)})())
    page.finalize()
    assert page.cart == []
    assert "NÃO É DOCUMENTO FISCAL" in shown[0]
    with ctx.db.session_scope() as s:
        from stockpilot.services import product_service
        assert product_service.get_product(s, pid).quantity_on_hand == D("8")
        assert ss.totals_for_day(s, date.today()) == (1, D("10.00"))


def test_dialogo_pagamento_calcula_troco_e_falta(app):
    d = PaymentDialog(D("50"), False)
    assert not d.ok.isEnabled()
    d.amount.setText("30")
    d._add()
    assert "Falta: R$ 20,00" in d.status.text()
    d.amount.setText("50")
    d._add()
    assert d.ok.isEnabled() and "Troco: R$ 30,00" in d.status.text()


def test_historico_e_devolucao_pela_interface(app, ctx, msgs):
    with ctx.db.session_scope() as s:
        p = make_product(s, ctx.current_user_id, qty="10", sale_price="5")
        sale = ss.finalize_sale(s, [ss.CartItem(p.id, D("3"))], [ss.PaymentInput(PaymentMethod.PIX, D("15"))],
                                seller_id=ctx.current_user_id)
        sid = sale.id
    w = MainWindow(ctx)
    page = w.pages[[n for n, _ in w.pages].index("Vendas (PDV)")][1]
    page.tabs.setCurrentIndex(1)
    page._load_history()
    assert page.h_table.rowCount() == 1


def test_compra_pela_interface(app, ctx, msgs, monkeypatch):
    from stockpilot.ui.dialogs.purchase_dialog import PurchaseDialog
    with ctx.db.session_scope() as s:
        sup = supplier_service.save_supplier(s, name="Fornecedor X")
        p = make_product(s, ctx.current_user_id, qty="0", name="Lápis")
        sid, pid = sup.id, p.id
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    d = PurchaseDialog(ctx)
    d.picker.edit.setText("Lápis")
    d.qty.setText("10")
    d.cost.setText("2,50")
    d._add()
    assert len(d.lines) == 1
    d._save(True)
    assert not [m for m in msgs if m[0] in ("warning", "critical")], msgs
    with ctx.db.session_scope() as s:
        from stockpilot.services import product_service
        assert product_service.get_product(s, pid).quantity_on_hand == D("10")


def test_tributario_e_folha_pela_interface(app, ctx, msgs):
    with ctx.db.session_scope() as s:
        s.add(Company(legal_name="X LTDA", cnpj="11222333000181", tax_regime=TaxRegime.MEI, activity_start_date=date(2020, 1, 1)))
    w = MainWindow(ctx)
    tax = w.pages[[n for n, _ in w.pages].index("Tributário")][1]
    tab = tax.parts[0][1]
    tab.refresh()
    tab.calc()
    assert tab.result is not None and tab.result.amount == D("82.05")
    assert "ESTIMATIVA" in tab.notes.toPlainText()
    tab.save()
    pay = w.pages[[n for n, _ in w.pages].index("Funcionários")][1]
    pay.refresh()
    assert pay.denied.text() == ""


def test_relatorios_backup_configuracoes_pela_interface(app, ctx, msgs, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    w = MainWindow(ctx)
    names = [n for n, _ in w.pages]
    rep = w.pages[names.index("Relatórios")][1]
    rep.refresh()
    for row in range(rep.list.count()):
        rep.list.setCurrentRow(row)
        rep.generate()
        assert rep.report is not None, row
    out = tmp_path / "r.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    rep._export("pdf")
    assert out.read_bytes()[:4] == b"%PDF"
    bk = w.pages[names.index("Backup")][1]
    bk.refresh()
    bk._now()
    assert bk.table.rowCount() == 1
    sel = w.pages[names.index("Configurações")][1]
    sel.refresh()
    sel.tabs.setCurrentIndex(1)
    sel.refresh()
    assert not [m for m in msgs if m[0] == "critical"]


def test_perfis_limitam_menu(app, ctx, msgs):
    from stockpilot.domain.enums import UserRole
    from stockpilot.services import user_service as us
    with ctx.db.session_scope() as s:
        op = us.create_user(s, ctx.current_user_id, "caixa", "Caixa", UserRole.OPERADOR, "segredo1")
        ctx.current_user_id = op.id
    w = MainWindow(ctx)
    vis = {n for i, (n, _) in enumerate(w.pages) if not w.group.button(i).isHidden()}
    assert vis == {"Vendas (PDV)", "Produtos", "Estoque", "Compras", "Fornecedores"}


def test_login_dialog(app, ctx):
    from stockpilot.services import user_service as us
    from stockpilot.ui.dialogs.login_dialog import LoginDialog
    with ctx.db.session_scope() as s:
        us.update_user(s, ctx.current_user_id, ctx.current_user_id, new_password="admin123")
    d = LoginDialog(ctx)
    d.user.setText("admin")
    d.pwd.setText("errada")
    d._try()
    assert d.user_id is None and "incorretos" in d.err.text()
    d.pwd.setText("admin123")
    d._try()
    assert d.user_id == ctx.current_user_id


def test_licenca_pela_interface_com_chave_do_fabricante(app, ctx, msgs):
    """Usa a chave privada gerada para este produto (se estiver presente no ambiente de desenvolvimento)."""
    import subprocess, sys
    from pathlib import Path
    pem = Path("/home/claude/CHAVE_PRIVADA_DO_FABRICANTE.pem")
    if not pem.exists():
        pytest.skip("chave privada do fabricante não está neste ambiente")
    w = MainWindow(ctx)
    sp = w.pages[[n for n, _ in w.pages].index("Configurações")][1]
    tab = sp.parts[2][1]
    tab.refresh()
    iid = tab.iid.text()
    key = subprocess.run([sys.executable, "tools/license_tool.py", "issue", "--key", str(pem), "--id", iid, "--customer", "Loja Piloto"],
                         capture_output=True, text=True, check=True).stdout.strip()
    tab.key.setPlainText(key)
    tab._activate()
    assert "Licenciado" in tab.state.text() and "Loja Piloto" in tab.detail.text()


def test_inventario_em_lote_pela_interface(app, ctx, msgs, monkeypatch):
    from stockpilot.ui.dialogs import inventory_dialog as idg
    monkeypatch.setattr(idg, "confirm", lambda *a, **k: True)
    with ctx.db.session_scope() as s:
        p = make_product(s, ctx.current_user_id, qty="10", name="Item")
        pid = p.id
    d = idg.InventoryDialog(ctx)
    d.add_product(pid, from_scan=False)
    d.table.item(0, idg.QTY_COL).setText("7")
    assert d.table.item(0, d.result_col).text() == "-3"
    d._apply()
    with ctx.db.session_scope() as s:
        from stockpilot.services import product_service
        assert product_service.get_product(s, pid).quantity_on_hand == D("7")
