from decimal import Decimal as D

import pytest
from openpyxl import Workbook

from stockpilot.domain.errors import BusinessError
from stockpilot.services import import_service as im, product_service, stock_service
from tests.conftest import make_product


def sheet(tmp_path, rows, headers=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Produtos"
    ws.append(headers or im.TEMPLATE_HEADERS)
    for r in rows:
        ws.append(r)
    p = tmp_path / "p.xlsx"
    wb.save(p)
    return p


def test_modelo_e_importacao_ok(session, uid, tmp_path):
    t = im.write_template(tmp_path / "modelo.xlsx")
    rep = im.import_products(session, t, uid)
    assert rep.ok and rep.created == 0 and rep.total_rows == 0   # a linha de exemplo é ignorada
    p = sheet(tmp_path, [["Arroz 5kg", "27,90", "18", 20, 5, "UN", "ARR5", "7891234567895", "Mercearia", None, None],
                         ["Queijo", 49.9, 30, "2,5", 1, "KG", None, None, "Frios", None, None]])
    rep = im.import_products(session, p, uid)
    assert rep.ok and rep.created == 2
    prods = {x.name: x for x in product_service.search_products(session)}
    assert prods["Arroz 5kg"].quantity_on_hand == D("20") and prods["Arroz 5kg"].sale_price == D("27.90")
    assert prods["Queijo"].quantity_on_hand == D("2.5") and prods["Queijo"].allows_fraction
    assert stock_service.verify_consistency(session) == []


def test_tudo_ou_nada_com_erros_por_linha(session, uid, tmp_path):
    p = sheet(tmp_path, [["Bom", "10", "5", 1, 0, "UN", "A1", None, None, None, None],
                         ["", "10", None, None, None, "UN", None, None, None, None, None],
                         ["Ruim", "abc", None, None, None, "UN", None, None, None, None, None],
                         ["Unid", "5", None, None, None, "XX", None, None, None, None, None],
                         ["Dup", "5", None, None, None, "UN", "A1", None, None, None, None]])
    rep = im.import_products(session, p, uid)
    assert not rep.ok and rep.created == 0
    txt = " | ".join(rep.errors)
    assert "linha 3" in txt and "linha 4" in txt and "linha 5" in txt and "linha 6" in txt
    assert product_service.search_products(session) == []     # nada foi gravado


def test_duplicado_com_banco(session, uid, tmp_path):
    make_product(session, uid, sku="X1")
    rep = im.import_products(session, sheet(tmp_path, [["Novo", "5", None, None, None, "UN", "X1", None, None, None, None]]), uid)
    assert not rep.ok


def test_cabecalho_ausente(session, uid, tmp_path):
    with pytest.raises(BusinessError, match="Nome"):
        im.import_products(session, sheet(tmp_path, [], headers=["Coluna", "Outra"]), uid)


def test_inventario_em_lote(session, uid):
    a = make_product(session, uid, qty="10", name="A")
    b = make_product(session, uid, qty="5", name="B")
    n = im.batch_inventory(session, {a.id: D("8"), b.id: D("5")}, uid)
    assert n == 1
    assert product_service.get_product(session, a.id).quantity_on_hand == D("8")
    assert stock_service.verify_consistency(session) == []
