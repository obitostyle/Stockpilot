"""Fluxos reais da interface (Qt offscreen): preenche campos, salva e confere o banco."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from decimal import Decimal as D
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from stockpilot.services import company_service, product_service as ps, stock_service as ss  # noqa: E402
from stockpilot.ui import common  # noqa: E402
from stockpilot.ui.dialogs.movement_dialog import MovementDialog  # noqa: E402
from stockpilot.ui.dialogs.product_dialog import ProductDialog  # noqa: E402
from stockpilot.ui.main_window import MainWindow  # noqa: E402
from stockpilot.ui.theme import apply_theme  # noqa: E402

import tempfile
SHOTS = Path(os.environ.get("STOCKPILOT_SHOTS") or Path(tempfile.gettempdir()) / "stockpilot-shots")


def idx_of(win, name):
    return [n for n, _ in win.pages].index(name)


def page_of(win, name):
    return win.pages[idx_of(win, name)][1]


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    apply_theme(a)
    return a


@pytest.fixture()
def msgs(monkeypatch):
    log = []
    for kind in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, _k=kind, **k: log.append((_k, a[2]))))
    monkeypatch.setattr(common, "confirm", lambda *a, **k: True)
    monkeypatch.setattr("stockpilot.ui.dialogs.movement_dialog.confirm", lambda *a, **k: True)
    return log


def test_fluxo_completo(app, ctx, msgs):
    SHOTS.mkdir(parents=True, exist_ok=True)
    win = MainWindow(ctx)
    win.show()
    for i in range(4):  # navega por todas as páginas sem erro
        win.go(i)
    win.go(0)
    assert "Bem-vindo" in win.pages[0][1].hint.text()  # banco vazio => orientação, não números falsos
    app.processEvents()
    win.grab().save(str(SHOTS / "1_dashboard_vazio.png"))

    # --- empresa: CNPJ inválido é recusado; alfanumérico válido é aceito
    comp = page_of(win, 'Empresa')
    comp.legal.setText("Loja Exemplo LTDA")
    comp.cnpj.setText("11.222.333/0001-82")
    comp.save()
    assert msgs[-1][0] == "warning" and "CNPJ" in msgs[-1][1]
    comp.cnpj.setText("12.ABC.345/01DE-35")
    comp.regime.setCurrentIndex(comp.regime.findData(comp.regime.itemData(2)))
    comp.save()
    with ctx.db.session_scope() as s:
        assert company_service.get_company(s).cnpj == "12ABC34501DE35"
    win.go(idx_of(win, 'Empresa'))
    app.processEvents()
    win.grab().save(str(SHOTS / "4_empresa.png"))

    # --- produto: validação
    dlg = ProductDialog(ctx)
    dlg.name.setText("")
    dlg._save()
    assert msgs[-1][0] == "warning" and "Nome" in msgs[-1][1]
    dlg.name.setText("Café Torrado 500g")
    dlg.cost.setText("abc")
    dlg._save()
    assert "Preço de custo" in msgs[-1][1]

    # --- produto: cadastro com saldo inicial e valores em formato brasileiro
    dlg.cost.setText("12,50")
    dlg.sale.setText("19,90")
    dlg.qty.setText("10")
    dlg.min_stock.setText("4")
    dlg.category.setCurrentText("Mercearia")
    dlg.barcode.setText("7891000100103")
    assert dlg.margin.text() != "—"
    dlg._save()
    assert dlg.result() == QDialog.DialogCode.Accepted
    with ctx.db.session_scope() as s:
        p = ps.search_products(s, "Café")[0]
        pid = p.id
        assert (p.quantity_on_hand, p.cost_price, p.sale_price) == (D("10"), D("12.5"), D("19.9"))
        assert p.category.name == "Mercearia"

    # --- produto fracionado por peso
    d2 = ProductDialog(ctx)
    d2.name.setText("Queijo Minas")
    d2.unit.setCurrentIndex(d2.unit.findText("Quilograma (KG)"))
    assert d2.fraction.isChecked()
    d2.cost.setText("40")
    d2.sale.setText("59,90")
    d2.qty.setText("2,5")
    d2._save()
    with ctx.db.session_scope() as s:
        assert ps.search_products(s, "Queijo")[0].quantity_on_hand == D("2.5")

    # --- código de barras duplicado é recusado
    d3 = ProductDialog(ctx)
    d3.name.setText("Outro")
    d3.barcode.setText("7891000100103")
    d3._save()
    assert "código de barras" in msgs[-1][1].lower() and d3.result() != QDialog.DialogCode.Accepted

    # --- movimentações pela interface
    m = MovementDialog(ctx, "saida", pid)
    m.qty.setText("3")
    m.reason.setText("Consumo interno")
    m._save()
    m2 = MovementDialog(ctx, "saida", pid)
    m2.qty.setText("50")
    m2._save()  # estoque insuficiente
    assert msgs[-1][0] == "warning" and "insuficiente" in msgs[-1][1].lower()
    m3 = MovementDialog(ctx, "entrada", pid)
    m3.qty.setText("10")
    m3.cost.setText("14,50")
    m3._save()
    m4 = MovementDialog(ctx, "ajuste", pid)
    m4.qty.setText("-1")
    m4._save()  # sem motivo
    assert "motivo" in msgs[-1][1].lower()
    m4.reason.setText("Quebra")
    m4._save()
    m5 = MovementDialog(ctx, "inventario", pid)
    m5.qty.setText("15")
    m5.reason.setText("Contagem de novembro")
    m5._save()
    with ctx.db.session_scope() as s:
        p = ps.get_product(s, pid)
        # 10 -3 +10 -1 => 16; inventário para 15 => -1
        assert p.quantity_on_hand == D("15")
        assert p.cost_price == D("13.6765")  # (7*12,5 + 10*14,5) / 17 = 232,5 / 17
        assert ss.verify_consistency(s) == []
        assert len(ss.history(s, product_id=pid)) == 5

    # --- produtos e estoque exibem os dados reais
    win.go(idx_of(win, 'Produtos'))
    prod_page = page_of(win, 'Produtos')
    assert prod_page.table.rowCount() == 2
    prod_page.search.setText("queijo")
    prod_page.reload()  # a busca espera a digitação parar (debounce); aqui força a consulta
    assert prod_page.table.rowCount() == 1
    prod_page.search.setText("")
    prod_page.reload()
    app.processEvents()
    win.grab().save(str(SHOTS / "2_produtos.png"))

    win.go(idx_of(win, 'Estoque'))
    stock_page = page_of(win, 'Estoque')
    assert stock_page.table.rowCount() == 6
    stock_page.table.selectRow(0)
    app.processEvents()
    win.grab().save(str(SHOTS / "3_estoque.png"))

    win.go(0)
    d = win.pages[0][1]
    assert "2 produtos ativos" in d.k_value.note.text() and not d.hint.isVisible()
    app.processEvents()
    win.grab().save(str(SHOTS / "1b_dashboard.png"))
    win.close()
