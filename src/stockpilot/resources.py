from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    """Caminho de um recurso (ícone etc.) tanto em desenvolvimento quanto no executável do PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / relative
