"""Produto vendido sem licença: nenhuma tela mostra avaliação, chave ou período encerrado."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication  # noqa: E402

from stockpilot import __version__  # noqa: E402
from stockpilot.licensing import service as lic  # noqa: E402
from stockpilot.ui.main_window import MainWindow  # noqa: E402
from stockpilot.ui.theme import QSS  # noqa: E402


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setStyleSheet(QSS)
    return a


def test_sem_licenca_nao_aparece_avaliacao_nem_aba(app, ctx):
    assert lic.LICENSING_ENABLED is False
    w = MainWindow(ctx)
    msg = w.statusBar().currentMessage().split("Banco de dados")[0]  # o caminho do banco pode conter qualquer texto
    assert f"StockPilot {__version__}" in msg
    assert "valiação" not in msg and "licen" not in msg.lower()
    page = [pg for n, pg in w.pages if n == "Configurações"][0]
    names = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    assert "Licença" not in names and "Geral" in names
