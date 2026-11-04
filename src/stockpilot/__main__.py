from __future__ import annotations

import logging
import sys


def _selftest_impl() -> int:
    """Autoteste usado pelo build: abre todas as telas, gera relatório e backup num banco temporário. Código 0 = tudo certo."""
    import os
    import tempfile
    from datetime import date
    from pathlib import Path

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .app_context import bootstrap
    from .config import paths
    from .reports import builders
    from .reports.export import to_pdf, to_xlsx
    from .services import backup_service
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app = QApplication([])
    apply_theme(app)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        ctx = bootstrap(Path(tmp))
        win = MainWindow(ctx)
        for i in range(len(win.pages)):
            win.go(i)
            page = win.stack.currentWidget()
            for t in range(page.tabs.count() if hasattr(page, "tabs") else 0):
                page.tabs.setCurrentIndex(t)
                page.refresh()
        with ctx.db.session_scope() as s:
            rep = builders.estoque_atual(s)
        to_xlsx(rep, Path(tmp) / "r.xlsx")
        to_pdf(rep, Path(tmp) / "r.pdf")
        info = backup_service.create_backup(ctx.db, paths.backups_dir(ctx.home))
        assert backup_service.verify_backup(info.path)[0]
        win.close()
        ctx.close()
        # No Windows um arquivo aberto não pode ser apagado: fecha o log antes de remover a pasta temporária.
        root = logging.getLogger("stockpilot")
        for h in list(root.handlers):
            h.close()
            root.removeHandler(h)
    return 0


def selftest() -> int:
    """Roda o autoteste e grava o resultado em %TEMP%\\stockpilot-selftest.txt (o executável do Windows não tem console)."""
    import tempfile
    import traceback
    from pathlib import Path

    out = Path(tempfile.gettempdir()) / "stockpilot-selftest.txt"
    try:
        code = _selftest_impl()
        out.write_text("AUTOTESTE OK\n", encoding="utf-8")
        print("AUTOTESTE OK")
        return code
    except BaseException:
        out.write_text("AUTOTESTE FALHOU\n" + traceback.format_exc(), encoding="utf-8")
        return 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import APP_NAME
    from .app_context import bootstrap
    from .domain.errors import StockPilotError
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    from .ui.brand import app_icon
    app.setWindowIcon(app_icon())
    apply_theme(app)
    try:
        ctx = bootstrap()
    except (StockPilotError, RuntimeError) as exc:
        QMessageBox.critical(None, APP_NAME, str(exc))
        return 1

    def excepthook(exc_type, exc, tb):
        logging.getLogger("stockpilot").error("Exceção não tratada", exc_info=(exc_type, exc, tb))
        QMessageBox.critical(None, APP_NAME, "Ocorreu um erro inesperado. Os detalhes foram gravados no log.")
    sys.excepthook = excepthook

    from .config import paths
    from .services import backup_service, settings_service

    with ctx.db.session_scope() as s:
        need_login = settings_service.get_bool(s, "login_required")
    if need_login:
        from .ui.dialogs.login_dialog import LoginDialog
        dlg = LoginDialog(ctx)
        if not dlg.exec():
            ctx.close()
            return 0
        ctx.current_user_id = dlg.user_id
    backup_service.run_auto_backup(ctx.db, paths.backups_dir(ctx.home))  # no máximo 1 por dia; falhas só vão para o log
    window = MainWindow(ctx)
    window.show()
    code = app.exec()
    ctx.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
