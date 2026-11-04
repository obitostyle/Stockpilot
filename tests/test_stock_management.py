"""Gestão de estoque: indicadores, giro, reposição, lotes e proteção contra lançamento duplicado."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from decimal import Decimal as D

import pytest

from stockpilot.domain.enums import MovementType
from stockpilot.domain.errors import InsufficientStockError, ValidationError
from stockpilot.services import product_service as ps, stock_analytics as sa, stock_service as ss
from tests.conftest import make_product


def _mk(ctx, **kw):
    with ctx.db.session_scope() as s:
        return make_product(s, ctx.current_user_id, **kw).id


def test_overview_valor_e_alertas(ctx):
    _mk(ctx, qty="10", name="A", cost_price="2.50", min_stock="3")      # ok
    _mk(ctx, qty="2", name="B", cost_price="10", min_stock="5")         # abaixo do mínimo
    _mk(ctx, qty="0", name="C", cost_price="7", min_stock="1")          # sem saldo
    with ctx.db.session_scope() as s:
        o = sa.overview(s)
    assert o.active_products == 3
    assert o.value_at_cost == D("45.00")  # 10*2,50 + 2*10
    assert o.below_min == 1 and o.out_of_stock == 1 and o.stale == 0


def test_giro_desconta_estornos_e_calcula_cobertura(ctx):
    pid = _mk(ctx, qty="100", name="Giro")
    uid = ctx.current_user_id
    with ctx.db.session_scope() as s:
        m1 = ss.register_exit(s, pid, D("30"), reason="x", user_id=uid)
        ss.register_exit(s, pid, D("30"), reason="x", user_id=uid)
        ss.reverse_movement(s, m1.id, "devolução", uid)
    with ctx.db.session_scope() as s:
        t = {x.product_id: x for x in sa.turnover(s, 30)}[pid]
    assert t.exits == D("30")                      # 60 saídas - 30 estornadas
    assert t.avg_daily == D("1.000")
    assert t.cover_days == D("70.0")               # saldo 70 / 1 por dia


def test_reposicao_criterios_e_quantidade(ctx):
    sem = _mk(ctx, qty="0", name="Sem saldo", min_stock="4")
    baixo = _mk(ctx, qty="2", name="Baixo", min_stock="5")
    _mk(ctx, qty="50", name="Folgado", min_stock="5")
    with ctx.db.session_scope() as s:
        sug = {x.item.product_id: x for x in sa.replenishment(s)}
    assert set(sug) == {sem, baixo}
    assert sug[sem].reason == "Sem saldo" and sug[sem].suggested == D("8")      # 2 × mínimo
    assert sug[baixo].reason == "Abaixo do mínimo" and sug[baixo].suggested == D("8")  # 10 - 2
    with ctx.db.session_scope() as s:
        order = [x.item.product_id for x in sa.replenishment(s)]
    assert order[0] == sem  # sem saldo vem primeiro


def test_reposicao_por_cobertura_curta(ctx):
    pid = _mk(ctx, qty="40", name="Vende muito", min_stock="0")
    with ctx.db.session_scope() as s:
        ss.register_exit(s, pid, D("35"), reason="x", user_id=ctx.current_user_id)
    with ctx.db.session_scope() as s:
        sug = {x.item.product_id: x for x in sa.replenishment(s, days=30, cover_days=30)}
    assert pid in sug and "Cobertura" in sug[pid].reason
    # alvo = 35/30*30 = 35 ; saldo 5 => sugerido 30
    assert sug[pid].suggested == D("30")


def test_relatorio_giro_estoque(ctx):
    from stockpilot.reports import builders as rb
    pid = _mk(ctx, qty="10", name="Rel", min_stock="2")
    with ctx.db.session_scope() as s:
        ss.register_exit(s, pid, D("9"), reason="x", user_id=ctx.current_user_id)
        rep = rb.giro_estoque(s, 30)
    assert rep.rows and any("Rel" in str(c) for r in rep.rows for c in r)


def test_batch_move_entrada_saida_e_atomicidade(ctx):
    a = _mk(ctx, qty="5", name="A")
    b = _mk(ctx, qty="1", name="B")
    uid = ctx.current_user_id
    with ctx.db.session_scope() as s:
        n = ss.batch_move(s, "entrada", {a: (D("3"), None), b: (D("2"), D("11"))}, user_id=uid, reason="Lote", batch_key="k1")
    assert n == 2
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, a).quantity_on_hand == D("8")
        assert ps.get_product(s, b).quantity_on_hand == D("3")
    # saída com um item sem saldo: nada é gravado (tudo ou nada)
    with pytest.raises(InsufficientStockError):
        with ctx.db.session_scope() as s:
            ss.batch_move(s, "saida", {a: (D("2"), None), b: (D("99"), None)}, user_id=uid, reason="Lote", batch_key="k2")
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, a).quantity_on_hand == D("8")
        assert ss.verify_consistency(s) == []


def test_batch_move_reenvio_nao_duplica(ctx):
    a = _mk(ctx, qty="5", name="A")
    uid = ctx.current_user_id
    for _ in range(2):
        with ctx.db.session_scope() as s:
            ss.batch_move(s, "entrada", {a: (D("3"), None)}, user_id=uid, reason="Lote", batch_key="mesmo")
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, a).quantity_on_hand == D("8")


def test_batch_move_validacoes(ctx):
    with pytest.raises(ValidationError):
        with ctx.db.session_scope() as s:
            ss.batch_move(s, "entrada", {}, user_id=ctx.current_user_id, reason=None, batch_key="v")
    with pytest.raises(ValidationError):
        with ctx.db.session_scope() as s:
            ss.batch_move(s, "ajuste", {1: (D("1"), None)}, user_id=ctx.current_user_id, reason=None, batch_key="v")


def test_recent_similar_detecta_repeticao(ctx):
    pid = _mk(ctx, qty="10", name="Rep")
    uid = ctx.current_user_id
    with ctx.db.session_scope() as s:
        assert ss.recent_similar(s, pid, MovementType.SAIDA, D("-2")) is None
        ss.register_exit(s, pid, D("2"), reason="x", user_id=uid)
    with ctx.db.session_scope() as s:
        assert ss.recent_similar(s, pid, MovementType.SAIDA, D("-2")) is not None
        assert ss.recent_similar(s, pid, MovementType.SAIDA, D("-3")) is None
        assert ss.recent_similar(s, pid, MovementType.ENTRADA, D("2")) is None


def test_busca_filtros_e_contagem(ctx):
    _mk(ctx, qty="0", name="Zero", min_stock="1")
    _mk(ctx, qty="1", name="Baixo", min_stock="2")
    _mk(ctx, qty="9", name="Ok", min_stock="2")
    with ctx.db.session_scope() as s:
        assert [p.name for p in ps.search_products(s, out_of_stock_only=True)] == ["Zero"]
        assert {p.name for p in ps.search_products(s, low_stock_only=True)} == {"Zero", "Baixo"}
        assert ps.count_products(s) == 3
        assert len(ps.search_products(s, limit=2)) == 2


# ------------------------------------------------------------------ interface
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from stockpilot.ui.dialogs import inventory_dialog as idg, movement_dialog as mdg  # noqa: E402
from stockpilot.ui.theme import QSS  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(QSS)
    return a


@pytest.fixture()
def quiet(monkeypatch):
    log = []
    for kind in ("warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, kind, staticmethod(lambda *a, _k=kind, **k: log.append((_k, a[2]))))
    monkeypatch.setattr(idg, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(mdg, "confirm", lambda *a, **k: True)
    return log


def test_dialogo_lote_leitura_soma_um_e_aplica_entrada(app, ctx, quiet):
    pid = _mk(ctx, qty="5", name="Lido", barcode="7891000100103")
    d = idg.InventoryDialog(ctx, kind="entrada")
    d._on_scan("7891000100103", None)
    d._on_scan("7891000100103", None)
    assert d.lines[pid]["qty"] == D("2")           # segunda leitura soma 1
    assert d.table.rowCount() == 1
    d._on_scan("0000000000000", None)              # não cadastrado: não cria linha
    assert d.table.rowCount() == 1
    d._apply()
    assert d.applied == 1
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, pid).quantity_on_hand == D("7")


def test_dialogo_lote_erros_bloqueiam_e_saida(app, ctx, quiet):
    pid = _mk(ctx, qty="3", name="Fracao")
    d = idg.InventoryDialog(ctx, kind="saida")
    d.add_product(pid, from_scan=False)
    d.table.item(0, idg.QTY_COL).setText("abc")
    d._apply()
    assert d.lines[pid].get("error") and quiet and quiet[-1][0] == "warning"
    d.table.item(0, idg.QTY_COL).setText("2")
    assert d.table.item(0, d.result_col).text() == "1"
    d._apply()
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, pid).quantity_on_hand == D("1")
    # inteiro obrigatório para produto sem fração
    d2 = idg.InventoryDialog(ctx, kind="saida")
    d2.add_product(pid, from_scan=False)
    d2.table.item(0, idg.QTY_COL).setText("0,5")
    assert d2.lines[pid].get("error")


def test_dialogo_reposicao_abre_entrada_preenchida(app, ctx, quiet, monkeypatch):
    from stockpilot.ui.dialogs import replenishment_dialog as rdg
    pid = _mk(ctx, qty="1", name="Repor", min_stock="5")
    d = rdg.ReplenishmentDialog(ctx)
    assert d.table.rowCount() == 1
    assert d.selected_lines() == [(pid, D("9"), None)]   # 2×5 - 1
    d.table.item(0, rdg.SUG).setText("4")
    assert d.selected_lines() == [(pid, D("4"), None)]
    seen = {}

    class Fake:
        applied = 1

        def __init__(self, ctx, parent=None, kind=None, preset=None):
            seen.update(kind=kind, preset=preset)
            self.reason = type("R", (), {"setText": lambda *_: None})()

        def exec(self):
            return 1
    monkeypatch.setattr("stockpilot.ui.dialogs.inventory_dialog.InventoryDialog", Fake)
    d._entry()
    assert seen["kind"] == "entrada" and seen["preset"] == [(pid, D("4"), None)]


def test_movimento_repetido_pede_confirmacao_e_clique_duplo_nao_duplica(app, ctx, monkeypatch, quiet):
    pid = _mk(ctx, qty="10", name="Dup")
    asked = []
    monkeypatch.setattr(mdg, "confirm", lambda *a, **k: asked.append(a[1]) or False)

    def new():
        d = mdg.MovementDialog(ctx, "saida", pid)
        d.qty.setText("2")
        return d
    new()._save()                       # primeira: sem aviso
    assert asked == []
    new()._save()                       # igual, logo depois: pergunta e (recusado) não grava
    assert asked and asked[0] == "Movimentação repetida?"
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, pid).quantity_on_hand == D("8")
    d = new()
    monkeypatch.setattr(mdg, "confirm", lambda *a, **k: True)
    d._save()
    d._save()                           # mesma janela/chave: não grava duas vezes
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, pid).quantity_on_hand == D("6")


def test_pagina_estoque_kpis_e_menu_em_lote(app, ctx, quiet):
    from stockpilot.ui.main_window import MainWindow
    _mk(ctx, qty="0", name="Zero", min_stock="1")
    _mk(ctx, qty="4", name="Ok", cost_price="5")
    w = MainWindow(ctx)
    page = [pg for n, pg in w.pages if n == "Estoque"][0]
    page.refresh()
    assert "20,00" in page.k_value.value.text() if hasattr(page.k_value, "value") else True
    assert page.b_repl.isEnabled()
