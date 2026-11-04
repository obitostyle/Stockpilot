from __future__ import annotations

from PySide6.QtWidgets import QWidget

from ...app_context import AppContext


class Page(QWidget):
    def __init__(self, ctx: AppContext, parent=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.ctx = ctx

    def refresh(self) -> None:  # sobrescrito pelas páginas
        pass
