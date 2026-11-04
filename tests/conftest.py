import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stockpilot.app_context import bootstrap  # noqa: E402
from stockpilot.services import product_service as ps  # noqa: E402
from stockpilot.services.schemas import ProductInput, build  # noqa: E402


@pytest.fixture()
def ctx(tmp_path):
    c = bootstrap(tmp_path / "home")
    yield c
    c.close()


@pytest.fixture()
def session(ctx):
    with ctx.db.session_scope() as s:
        yield s


@pytest.fixture()
def uid(ctx):
    return ctx.current_user_id


def make_product(session, uid=None, qty="0", **kw):
    data = dict(name="Produto Teste", cost_price="10", sale_price="25", min_stock="0")
    data.update(kw)
    return ps.create_product(session, build(ProductInput, **data), Decimal(qty), uid)


@pytest.fixture(autouse=True, scope="session")
def _qt_cleanup():
    """Encerra o Qt de forma ordenada no fim da sessão (evita falha de memória no desligamento do interpretador)."""
    yield
    try:
        import gc

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            app.closeAllWindows()
            for w in app.topLevelWidgets():
                w.deleteLater()
            app.processEvents()
            gc.collect()
            app.processEvents()
    except ImportError:
        pass
