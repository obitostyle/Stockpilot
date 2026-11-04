from decimal import Decimal as D

import pytest

from stockpilot.domain.errors import DatabaseIncompatibleError
from stockpilot.infra.database import Database
from stockpilot.infra.security import hash_password, verify_password
from stockpilot.models import Setting
from stockpilot.services import dashboard_service as dash
from stockpilot.services import user_service as us
from conftest import make_product


def test_dashboard_vazio_so_zeros(session):
    d = dash.load_dashboard(session)
    assert (d.total_products, d.low_stock_count, d.stock_value_at_cost, d.has_company) == (0, 0, D("0"), False)


def test_dashboard_com_dados(session, uid):
    make_product(session, uid, qty="4", cost_price="12.50", min_stock="5")
    make_product(session, uid, qty="2.5", name="B", unit="KG", cost_price="10")
    make_product(session, uid, qty="0", name="Zerado")
    d = dash.load_dashboard(session)
    assert d.total_products == 3 and d.low_stock_count == 1 and d.out_of_stock_count == 1
    assert d.stock_value_at_cost == D("75.00")  # 4*12,5 + 2,5*10


def test_senha_scrypt():
    h = hash_password("segredo123")
    assert "segredo123" not in h and h.startswith("scrypt$")
    assert verify_password("segredo123", h) and not verify_password("errada", h)
    assert not verify_password("x", None) and not verify_password("x", "lixo")


def test_autenticacao(session):
    u = us.ensure_default_user(session)
    assert us.ensure_default_user(session).id == u.id
    us.set_password(session, u.id, "minhasenha")
    assert us.authenticate(session, "admin", "minhasenha").id == u.id
    assert us.authenticate(session, "admin", "outra") is None


def test_banco_de_versao_mais_nova_e_recusado(tmp_path):
    db = Database(tmp_path / "x.db")
    db.init_schema()
    with db.session_scope() as s:
        s.get(Setting, "schema_version").value = "999"
    with pytest.raises(DatabaseIncompatibleError):
        db.init_schema()
