"""Leitor de código de barras USB (modo teclado): rajada de teclas + Enter."""
import os
from decimal import Decimal as D

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QVBoxLayout, QWidget  # noqa: E402

from stockpilot.services import product_service as ps  # noqa: E402
from stockpilot.ui import common  # noqa: E402
from stockpilot.ui.barcode import ScanDetector, looks_like_barcode, normalize_scan  # noqa: E402
from tests.conftest import make_product  # noqa: E402

CODE = "7891000100103"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def quiet(monkeypatch):
    log = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, _k=kind, **k: log.append((_k, a[2]))))
    import stockpilot.ui.toast as t
    monkeypatch.setattr(t, "show_toast", lambda parent, text, kind="success", ms=0: log.append(("toast", text)))
    return log


def scan(widget, code=CODE, enter=Qt.Key_Return):
    """Simula o leitor: caracteres em rajada (sem intervalo) e Enter no final."""
    widget.setFocus()
    QApplication.processEvents()
    QTest.keyClicks(widget, code)
    QTest.keyClick(widget, enter)
    QApplication.processEvents()


def show(w):
    w.show()
    w.activateWindow()
    QApplication.processEvents()


# ------------------------------------------------------------------ utilitários
def test_normaliza_e_reconhece():
    assert normalize_scan(" 7891000100103\r\n") == CODE
    assert looks_like_barcode("0001") and looks_like_barcode(CODE)
    assert not looks_like_barcode("123") and not looks_like_barcode("ABC1234") and not looks_like_barcode("")


def test_rajada_detectada_e_digitacao_lenta_ignorada(app):
    host = QWidget()
    lay = QVBoxLayout(host)
    edit = QLineEdit()
    lay.addWidget(edit)
    got = []
    ScanDetector(host, lambda c, src: got.append(c))
    show(host)
    scan(edit)
    assert got == [CODE]
    assert edit.text() == ""  # o texto lido sai do campo comum
    edit.setFocus()
    for ch in "1234":
        QTest.keyClick(edit, ch, delay=90)  # pessoa digitando
    QTest.keyClick(edit, Qt.Key_Return, delay=90)
    assert got == [CODE] and edit.text() == "1234"
    host.close()


# ------------------------------------------------------------------ cadastro
def test_cadastro_leitura_em_qualquer_campo_preenche_codigo_sem_salvar(app, ctx, quiet):
    from stockpilot.ui.dialogs.product_dialog import ProductDialog
    d = ProductDialog(ctx)
    show(d)
    d.name.setText("Biscoito")
    scan(d.name)  # o leitor "digitou" no campo Nome
    assert d.name.text() == "Biscoito"
    assert d.barcode.text() == CODE
    assert d.result() == 0 and d.isVisible()  # o Enter do leitor não salvou o produto
    assert "disponível" in d.scan_status.text()
    d.close()


def test_cadastro_bloqueia_codigo_duplicado(app, ctx, quiet):
    from stockpilot.ui.dialogs.product_dialog import ProductDialog
    with ctx.db.session_scope() as s:
        make_product(s, ctx.current_user_id, qty="0", name="Já existe", barcode=CODE)
    d = ProductDialog(ctx)
    show(d)
    scan(d.barcode)
    assert d.barcode.text() == CODE
    assert "já pertence" in d.scan_status.text()
    d.name.setText("Outro")
    d.sale.setText("5")
    d._save()
    with ctx.db.session_scope() as s:
        assert len([p for p in ps.search_products(s, "Outro")]) == 0  # não gravou duplicado
    d.close()


def test_cadastro_sem_codigo_continua_permitido(app, ctx, quiet):
    from stockpilot.ui.dialogs.product_dialog import ProductDialog
    d = ProductDialog(ctx)
    d.name.setText("Granel sem código")
    d.sale.setText("3")
    assert d.check_barcode() is True
    d._save()
    with ctx.db.session_scope() as s:
        p = ps.search_products(s, "Granel")[0]
        assert p.barcode is None


def test_cadastro_pre_preenchido_pela_tela_de_produtos(app, ctx, quiet):
    from stockpilot.ui.dialogs.product_dialog import ProductDialog
    d = ProductDialog(ctx, None, None, barcode=" 0001234567890\n")
    assert d.barcode.text() == "0001234567890"  # zeros à esquerda preservados


def test_servico_dono_do_codigo(session, uid):
    p = make_product(session, uid, qty="0", name="A", barcode=CODE)
    assert ps.barcode_owner(session, CODE).id == p.id
    assert ps.barcode_owner(session, CODE, exclude_id=p.id) is None
    ps.set_active(session, p.id, False)
    assert ps.find_by_barcode(session, CODE) is None
    assert ps.find_by_barcode(session, CODE, include_inactive=True).id == p.id


# ------------------------------------------------------------------ busca em Produtos
def _main(ctx):
    from stockpilot.ui.main_window import MainWindow
    w = MainWindow(ctx)
    show(w)
    return w


def test_produtos_leitura_encontra_e_seleciona(app, ctx, quiet):
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="7", name="Café", barcode=CODE).id
        make_product(s, ctx.current_user_id, qty="1", name="Outro")
    w = _main(ctx)
    w.go([n for n, _ in w.pages].index("Produtos"))
    page = w.stack.currentWidget()
    scan(page.table)  # foco na tabela: a leitura funciona mesmo assim
    row = page.table.currentRow()
    assert row >= 0 and page.table.item(row, 0).data(Qt.UserRole) == pid
    assert "encontrado" in page.scan_status.text() and not page.btn_register_code.isVisible()
    assert page.search.hasFocus() and page.search.selectedText() == CODE  # pronto para a próxima leitura
    w.close()


def test_produtos_codigo_inexistente_oferece_cadastro(app, ctx, quiet):
    w = _main(ctx)
    w.go([n for n, _ in w.pages].index("Produtos"))
    page = w.stack.currentWidget()
    scan(page.search, "1234567890123")
    assert "não cadastrado" in page.scan_status.text()
    assert page.btn_register_code.isVisible() and page._missing_code == "1234567890123"
    w.close()


# ------------------------------------------------------------------ venda e movimentação
def test_pdv_leituras_seguidas_e_codigo_desconhecido(app, ctx, quiet):
    with ctx.db.session_scope() as s:
        make_product(s, ctx.current_user_id, qty="10", name="Café", barcode=CODE, sale_price="10")
    w = _main(ctx)
    w.go([n for n, _ in w.pages].index("Vendas (PDV)"))
    page = w.stack.currentWidget()
    scan(page.picker.edit)
    scan(page.table)  # segunda leitura com o foco no carrinho
    assert len(page.cart) == 1 and page.cart[0]["qty"] == D("2")
    scan(page.picker.edit, "78910001")  # parte de um código existente: NÃO pode escolher o "parecido"
    assert page.cart[0]["qty"] == D("2") and len(page.cart) == 1
    assert any("não cadastrado" in m for k, m in quiet if k == "toast")
    w.close()


def test_movimentacao_leitura_escolhe_produto_e_foca_quantidade(app, ctx, quiet):
    from stockpilot.ui.dialogs.movement_dialog import MovementDialog
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="3", name="Café", barcode=CODE).id
        make_product(s, ctx.current_user_id, qty="3", name="Arroz")
    d = MovementDialog(ctx, "entrada")
    show(d)
    scan(d.product)
    assert d.product.currentData() == pid
    assert d.qty.hasFocus() and d.result() == 0
    scan(d.product, "999999999")
    assert "não cadastrado" in d.scan_status.text()
    d.close()


def test_estoque_leitura_preseleciona_produto(app, ctx, quiet):
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="3", name="Café", barcode=CODE).id
    w = _main(ctx)
    w.go([n for n, _ in w.pages].index("Estoque"))
    page = w.stack.currentWidget()
    scan(page.table)
    assert page.scanned_pid == pid
    w.close()
