"""Diretórios do aplicativo (Windows: %LOCALAPPDATA%\\StockPilot).

Dados do cliente ficam FORA da pasta de instalação, de modo que atualizações
e reinstalações nunca sobrescrevem o banco. Para desenvolvimento/testes use
a variável de ambiente STOCKPILOT_HOME.
"""
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir


def app_home() -> Path:
    override = os.environ.get("STOCKPILOT_HOME")
    if override:
        return Path(override)
    new = Path(user_data_dir("StockPilot", appauthor=False))
    # Instalações anteriores gravavam em "StockPilotAI": se só a pasta antiga existir, ela continua
    # sendo usada, para não perder nenhum dado já cadastrado.
    legacy = Path(user_data_dir("StockPilotAI", appauthor=False))
    if not new.exists() and (legacy / "data" / "stockpilot.db").exists():
        return legacy
    return new


def db_path(home: Path | None = None) -> Path:
    return (home or app_home()) / "data" / "stockpilot.db"


def logs_dir(home: Path | None = None) -> Path:
    return (home or app_home()) / "logs"


def backups_dir(home: Path | None = None) -> Path:
    return (home or app_home()) / "backups"


def ensure_dirs(home: Path | None = None) -> Path:
    base = home or app_home()
    for sub in ("data", "logs", "backups", "config"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base
