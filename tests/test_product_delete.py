"""Exclusão de produtos e remoção do bloqueio por identificação da empresa (v0.3)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from stockpilot.app_context import bootstrap  # noqa: E402
from stockpilot.domain.errors import NotFoundError, ValidationError  # noqa: E402
from stockpilot.models import Product  # noqa: E402
from stockpilot.services import product_service as ps  # noqa: E402
from stockpilot.ui.main_window import MainWindow  # noqa: E402
from stockpilot.ui.pages import products_page as pp  # noqa: E402
from tests.conftest import make_product  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def msgs(monkeypatch):
    log = []
    for kind in ("warning", "critical", "information"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, _k=kind, **k: log.append((_k, a[2]))))
    monkeypatch.setattr(pp, "toast", lambda parent, text, kind="success": log.append(("toast", text)))
    return log


# ------------------------------------------------------------------ serviço
def test_exclui_produto_sem_historico(session, uid):
    p = make_product(session, uid, qty="0", name="Sem uso")
    assert not ps.product_usage(session, p.id).has_history
    assert ps.delete_product(session, p.id) == "Sem uso"
    assert session.get(Product, p.id) is None


def test_nao_exclui_produto_com_historico(session, uid):
    p = make_product(session, uid, qty="5", name="Com saldo")  # estoque inicial gera movimentação
    with pytest.raises(ValidationError) as e:
        ps.delete_product(session, p.id)
    assert "Inativar" in str(e.value)
    assert session.get(Product, p.id) is not None  # nada apagado
    assert ps.product_usage(session, p.id).movements == 1


def test_produto_inexistente(session):
    with pytest.raises(NotFoundError):
        ps.delete_product(session, 999999)


def test_exclusao_persiste_apos_reabrir(tmp_path):
    ctx = bootstrap(tmp_path / "h")
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="0", name="Temporário").id
    with ctx.db.session_scope() as s:
        ps.delete_product(s, pid)
    ctx.close()
    ctx2 = bootstrap(tmp_path / "h")
    with ctx2.db.session_scope() as s:
        assert s.get(Product, pid) is None
    ctx2.close()


# ------------------------------------------------------------------ interface
def _page(w):
    return w.pages[[n for n, _ in w.pages].index("Produtos")][1]


def _select(page, pid):
    from PySide6.QtCore import Qt
    for r in range(page.table.rowCount()):
        if page.table.item(r, 0).data(Qt.UserRole) == pid:
            page.table.setCurrentCell(r, 1)
            return
    raise AssertionError("produto não está na lista")


def test_botao_excluir_cancelar_e_confirmar(app, ctx, msgs, monkeypatch):
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="0", name="Apagável").id
    w = MainWindow(ctx)
    w.go([n for n, _ in w.pages].index("Produtos"))
    page = _page(w)
    assert page.btn_delete.text() == "Excluir" and not page.btn_delete.icon().isNull()
    _select(page, pid)
    monkeypatch.setattr(pp, "confirm", lambda *a, **k: False)  # Cancelar
    page.delete_selected()
    with ctx.db.session_scope() as s:
        assert s.get(Product, pid) is not None
    asked = []
    monkeypatch.setattr(pp, "confirm", lambda *a, **k: asked.append(k) or True)  # Excluir produto
    page.delete_selected()
    assert asked and asked[0].get("destructive") is True
    with ctx.db.session_scope() as s:
        assert s.get(Product, pid) is None
    assert page.table.rowCount() == 0  # lista atualizada na hora
    assert ("toast", "Produto 'Apagável' excluído.") in msgs


def test_produto_com_historico_oferece_inativar(app, ctx, msgs, monkeypatch):
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="3", name="Histórico").id
    w = MainWindow(ctx)
    page = _page(w)
    page.refresh()
    _select(page, pid)
    texts = []
    monkeypatch.setattr(pp, "confirm", lambda parent, title, text, yes, **k: texts.append((title, yes)) or True)
    page.delete_selected()
    assert texts == [("Exclusão não permitida", "Inativar produto")]
    with ctx.db.session_scope() as s:
        p = s.get(Product, pid)
        assert p is not None and p.active is False  # inativado, histórico intacto


def test_falha_de_persistencia_nao_trava(app, ctx, msgs, monkeypatch):
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="0", name="Falha").id
    w = MainWindow(ctx)
    page = _page(w)
    page.refresh()
    _select(page, pid)
    monkeypatch.setattr(pp, "confirm", lambda *a, **k: True)

    def boom(*a, **k):
        raise RuntimeError("disco cheio")
    monkeypatch.setattr(ps, "delete_product", boom)
    page.delete_selected()
    assert any(k == "critical" for k, _ in msgs)
    with ctx.db.session_scope() as s:
        assert s.get(Product, pid) is not None


def test_produto_removido_em_outra_tela(app, ctx, msgs, monkeypatch):
    with ctx.db.session_scope() as s:
        pid = make_product(s, ctx.current_user_id, qty="0", name="Fantasma").id
    w = MainWindow(ctx)
    page = _page(w)
    page.refresh()
    _select(page, pid)
    with ctx.db.session_scope() as s:
        ps.delete_product(s, pid)
    page.delete_selected()
    assert any(k == "warning" and "não existe" in t for k, t in msgs)


def test_telas_de_taxas_abrem_sem_cadastro_de_empresa(app, ctx, msgs):
    w = MainWindow(ctx)
    for name in ("Tributário", "Funcionários"):
        i = [n for n, _ in w.pages].index(name)
        w.go(i)
        assert w.stack.currentWidget() is w.pages[i][1]  # sem tela de bloqueio
    assert not hasattr(w, "locked")
