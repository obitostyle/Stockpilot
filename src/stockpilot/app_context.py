"""Inicialização do aplicativo: pastas, log, banco e usuário padrão."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import paths
from .infra.database import Database
from .infra.logging_setup import setup_logging
from .services.finance_service import seed_finance
from .services.tax_rules import seed_tax_rules
from .services.user_service import ensure_default_user

log = logging.getLogger("stockpilot.app")


@dataclass
class AppContext:
    home: Path
    db: Database
    current_user_id: int

    def close(self) -> None:
        self.db.dispose()


def bootstrap(home: Path | None = None) -> AppContext:
    base = paths.ensure_dirs(home)
    setup_logging(paths.logs_dir(base))
    db = Database(paths.db_path(base))
    db.init_schema()
    if not db.integrity_check():
        log.error("Falha na verificação de integridade do banco: %s", db.path)
        raise RuntimeError("O banco de dados parece corrompido. Restaure um backup.")
    with db.session_scope() as s:
        user = ensure_default_user(s)
        uid = user.id
        seed_finance(s)
        seed_tax_rules(s)
    log.info("StockPilot %s iniciado. Banco: %s", __version__, db.path)
    return AppContext(home=base, db=db, current_user_id=uid)
