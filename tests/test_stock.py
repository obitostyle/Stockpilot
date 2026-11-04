import decimal
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from stockpilot.domain.enums import MovementType
from stockpilot.domain.errors import (
    DuplicateError, InsufficientStockError, NotFoundError, ValidationError,
)
from stockpilot.models import StockMovement
from stockpilot.services import product_service as ps
from stockpilot.services import settings_service as st
from stockpilot.services import stock_service as ss
from stockpilot.services.schemas import ProductInput, build
from conftest import make_product


# ---------------- cadastro ----------------
def test_cadastro_gera_codigo_e_saldo_inicial(session, uid):
    p = make_product(session, uid, qty="5", name="Camiseta", cost_price="12.5")
    assert p.internal_code == "P000001" and p.quantity_on_hand == D("5")
    hist = ss.history(session, product_id=p.id)
    assert len(hist) == 1 and hist[0].reason == "Saldo inicial" and hist[0].balance_after == D("5")


def test_codigos_unicos(session):
    make_product(session, sku="ABC", barcode="7891234567895", internal_code="X1")
    for kw in ({"sku": "ABC"}, {"barcode": "7891234567895"}, {"internal_code": "X1"}):
        with pytest.raises(DuplicateError):
            make_product(session, name="Outro", **kw)


def test_validacoes_de_produto():
    for kw in ({"name": ""}, {"sale_price": "-1"}, {"sale_price": "1.999"}, {"cost_price": "abc"},
               {"barcode": "12ab"}, {"min_stock": "-2"}):
        with pytest.raises(ValidationError):
            build(ProductInput, **{"name": "x", **kw})


def test_margem_e_estoque_baixo(session):
    p = make_product(session, cost_price="60", sale_price="100", min_stock="3", qty="3")
    assert p.margin_percent == D("40") and p.is_low_stock
    z = make_product(session, name="Grátis", cost_price="5", sale_price="0")
    assert z.margin_percent is None


def test_busca_filtros_e_ordenacao(session):
    a = make_product(session, name="Caderno Azul", sku="CAD-1", barcode="7890000000001", category_name="Papelaria")
    make_product(session, name="Caneta Preta", category_name="Papelaria", min_stock="5", qty="1")
    make_product(session, name="Bola 100%", category_name="Esporte")
    assert [p.name for p in ps.search_products(session, "cad")] == ["Caderno Azul"]
    assert ps.search_products(session, "7890000000001")[0].id == a.id
    assert len(ps.search_products(session, category_id=a.category_id)) == 2
    assert [p.name for p in ps.search_products(session, low_stock_only=True)] == ["Caneta Preta"]
    assert [p.name for p in ps.search_products(session, "100%")] == ["Bola 100%"]  # % não vira curinga
    assert [p.name for p in ps.search_products(session, "%")] == ["Bola 100%"]  # % é literal, não curinga
    ps.set_active(session, a.id, False)
    assert a.id not in [p.id for p in ps.search_products(session)]
    assert a.id in [p.id for p in ps.search_products(session, only_active=False)]


def test_editar_produto_nao_altera_saldo(session, uid):
    p = make_product(session, uid, qty="4")
    ps.update_product(session, p.id, build(ProductInput, name="Novo nome", sale_price="30", cost_price="10"))
    assert p.name == "Novo nome" and p.quantity_on_hand == D("4")


# ---------------- entrada / saída ----------------
def test_entrada_saida_e_historico(session, uid):
    p = make_product(session, uid)
    ss.register_entry(session, p.id, 10, "8", reason="Compra balcão", user_id=uid)
    ss.register_exit(session, p.id, 4, reason="Uso interno", user_id=uid)
    assert p.quantity_on_hand == D("6")
    h = ss.history(session, product_id=p.id)
    assert [(m.movement_type, m.quantity_delta, m.balance_after) for m in h] == [
        (MovementType.SAIDA, D("-4"), D("6")), (MovementType.ENTRADA, D("10"), D("10"))]
    assert h[0].unit_cost == p.cost_price  # custo registrado na saída
    assert ss.verify_consistency(session) == []


def test_estoque_insuficiente_nao_grava_nada(session, uid):
    p = make_product(session, uid, qty="2")
    with pytest.raises(InsufficientStockError):
        ss.register_exit(session, p.id, 3)
    assert p.quantity_on_hand == D("2") and len(ss.history(session)) == 1


def test_estoque_negativo_so_com_configuracao(session):
    p = make_product(session)
    st.set_setting(session, "allow_negative_stock", "true")
    ss.register_exit(session, p.id, 1)
    assert p.quantity_on_hand == D("-1")


def test_quantidade_invalida(session):
    p = make_product(session, qty="1")
    for q in (0, -1, "1.5", D("1.5"), D("NaN"), D("Infinity"), D("1000000000")):
        with pytest.raises(ValidationError):
            ss.register_entry(session, p.id, q)  # zero, negativo, fração em produto unitário, NaN, limite
    with pytest.raises(decimal.InvalidOperation):
        ss.register_entry(session, p.id, "abc")
    with pytest.raises(TypeError):
        ss.register_entry(session, p.id, 1.5)  # float proibido
    with pytest.raises(NotFoundError):
        ss.register_entry(session, 999, 1)


def test_produto_fracionado_por_peso(session, uid):
    p = make_product(session, uid, name="Queijo", unit="KG", cost_price="40", qty="2.250")
    assert p.allows_fraction
    ss.register_exit(session, p.id, D("0.350"), user_id=uid)
    assert p.quantity_on_hand == D("1.900")
    with pytest.raises(ValidationError):
        ss.register_exit(session, p.id, D("0.0001"))


def test_custo_medio_ponderado(session):
    p = make_product(session, cost_price="10")
    ss.register_entry(session, p.id, 10, "10")
    ss.register_entry(session, p.id, 10, "20")
    assert p.cost_price == D("15.0000")
    ss.register_entry(session, p.id, 20, "30")
    assert p.cost_price == D("22.5000")
    ss.register_exit(session, p.id, 40)
    ss.register_entry(session, p.id, 3, "7.3333")  # saldo zero: custo = novo custo
    assert p.cost_price == D("7.3333")


def test_custo_medio_sem_erro_de_ponto_flutuante(session):
    p = make_product(session, cost_price="0")
    for _ in range(3):
        ss.register_entry(session, p.id, 1, "0.1")
    assert p.cost_price == D("0.1000")


def test_idempotencia_evita_entrada_duplicada(session):
    p = make_product(session)
    m1 = ss.register_entry(session, p.id, 5, "3", idempotency_key="compra:42")
    m2 = ss.register_entry(session, p.id, 5, "3", idempotency_key="compra:42")
    assert m1.id == m2.id and p.quantity_on_hand == D("5")


# ---------------- ajuste / inventário / estorno ----------------
def test_ajuste_exige_usuario_e_motivo(session, uid):
    p = make_product(session, uid, qty="5")
    with pytest.raises(ValidationError):
        ss.adjust(session, p.id, -1, "quebra", None)
    with pytest.raises(ValidationError):
        ss.adjust(session, p.id, -1, " ", uid)
    m = ss.adjust(session, p.id, -2, "Produto danificado", uid)
    assert p.quantity_on_hand == D("3") and m.user_id == uid and m.movement_type == MovementType.AJUSTE
    with pytest.raises(InsufficientStockError):
        ss.adjust(session, p.id, -10, "erro", uid)


def test_inventario_fisico(session, uid):
    p = make_product(session, uid, qty="10")
    assert ss.inventory_count(session, p.id, 10, "Contagem", uid) is None  # sem divergência
    m = ss.inventory_count(session, p.id, 7, "Contagem mensal", uid)
    assert m.quantity_delta == D("-3") and p.quantity_on_hand == D("7")
    m = ss.inventory_count(session, p.id, 12, "Recontagem", uid)
    assert m.quantity_delta == D("5") and m.movement_type == MovementType.INVENTARIO
    assert ss.inventory_count(session, p.id, 0, "Zerado", uid).balance_after == D("0")


def test_estorno_rastreavel(session, uid):
    p = make_product(session, uid, qty="10")
    saida = ss.register_exit(session, p.id, 4, user_id=uid)
    est = ss.reverse_movement(session, saida.id, "Lançamento errado", uid)
    assert p.quantity_on_hand == D("10") and est.reverses_movement_id == saida.id
    assert est.movement_type == MovementType.ESTORNO
    assert ss.is_reversed(session, saida.id)
    assert len(ss.history(session, product_id=p.id)) == 3  # original NÃO foi apagada
    with pytest.raises(ValidationError):
        ss.reverse_movement(session, saida.id, "de novo", uid)  # estorno duplo
    with pytest.raises(ValidationError):
        ss.reverse_movement(session, est.id, "estornar estorno", uid)
    with pytest.raises(ValidationError):
        ss.reverse_movement(session, saida.id, "sem usuario", None)


def test_estorno_de_entrada_respeita_estoque_minimo_zero(session, uid):
    p = make_product(session, uid)
    ent = ss.register_entry(session, p.id, 5, user_id=uid)
    ss.register_exit(session, p.id, 5, user_id=uid)
    with pytest.raises(InsufficientStockError):
        ss.reverse_movement(session, ent.id, "erro de digitação", uid)


def test_filtros_de_historico(session, uid):
    a = make_product(session, uid, name="Alfa", qty="5")
    b = make_product(session, uid, name="Beta", qty="5")
    ss.register_exit(session, a.id, 1)
    assert len(ss.history(session, product_id=a.id)) == 2
    assert len(ss.history(session, types=[MovementType.SAIDA])) == 1
    assert {m.product.name for m in ss.history(session, text="bet")} == {"Beta"}


# ---------------- integridade ----------------
def test_movimentacao_e_imutavel_no_banco(ctx, uid):
    with ctx.db.session_scope() as s:
        p = make_product(s, uid, qty="3")
        mid = ss.history(s)[0].id
    for sql in (f"UPDATE stock_movements SET reason='x' WHERE id={mid}",
                f"DELETE FROM stock_movements WHERE id={mid}"):
        with pytest.raises(DBAPIError) as e:
            with ctx.db.engine.begin() as conn:
                conn.execute(text(sql))
        assert "imutáveis" in str(e.value) or "não podem ser apagadas" in str(e.value)


def test_rollback_completo_em_erro(ctx, uid):
    with ctx.db.session_scope() as s:
        pid = make_product(s, uid, qty="5").id
    with pytest.raises(InsufficientStockError):
        with ctx.db.session_scope() as s:
            ss.register_entry(s, pid, 10)
            ss.register_exit(s, pid, 100)  # falha => a entrada acima também é desfeita
    with ctx.db.session_scope() as s:
        assert ps.get_product(s, pid).quantity_on_hand == D("5")
        assert ss.verify_consistency(s) == []


def test_valores_nao_viram_float_no_banco(ctx, uid):
    with ctx.db.session_scope() as s:
        make_product(s, uid, cost_price="0.1", sale_price="0.2")
    with ctx.db.engine.connect() as c:
        assert c.execute(text("SELECT typeof(cost_price), cost_price FROM products")).one() == ("integer", 1000)


def test_dados_persistem_apos_reabrir(tmp_path, uid):
    from stockpilot.app_context import bootstrap
    c1 = bootstrap(tmp_path / "h")
    with c1.db.session_scope() as s:
        make_product(s, c1.current_user_id, qty="7", name="Persistente")
    c1.close()
    c2 = bootstrap(tmp_path / "h")
    with c2.db.session_scope() as s:
        p = ps.search_products(s, "Persistente")[0]
        assert p.quantity_on_hand == D("7") and len(ss.history(s)) == 1
    c2.close()


def test_produtos_sem_movimentacao(session, uid):
    from datetime import timedelta
    from stockpilot.models import utcnow
    old = make_product(session, uid, qty="1", name="Parado")
    make_product(session, uid, qty="1", name="Girando")
    session.execute(text("DROP TRIGGER trg_stock_movements_no_update"))  # só para simular data antiga
    session.execute(text("UPDATE stock_movements SET created_at = :d WHERE product_id = :p"),
                    {"d": utcnow() - timedelta(days=200), "p": old.id})
    assert [p.name for p in ps.products_without_movement(session, 90)] == ["Parado"]
    session.rollback()


def test_exportar_excel(session, tmp_path):
    from openpyxl import load_workbook
    make_product(session, name="Item", qty="2", sale_price="10", cost_price="4")
    out = ps.export_products_xlsx(session, tmp_path / "p.xlsx")
    ws = load_workbook(out).active
    assert ws["B2"].value == "Item" and ws["I2"].value == 10 and ws["K2"].value == 2
