from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from ... import APP_NAME
from ...services import user_service
from ..brand import lockup
from ..common import primary


class LoginDialog(QDialog):
    MAX_TRIES = 5

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.user_id: int | None = None
        self.tries = 0
        self.setWindowTitle(f"{APP_NAME} — Entrar")
        self.setMinimumWidth(420)
        self.user = QLineEdit()
        self.pwd = QLineEdit()
        self.pwd.setEchoMode(QLineEdit.Password)
        self.err = QLabel("")
        self.err.setObjectName("error")
        self.err.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Usuário", self.user)
        form.addRow("Senha", self.pwd)
        ok = primary(QPushButton("Entrar"))
        cancel = QPushButton("Sair")
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        cancel.setObjectName("linkButton")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 30, 32, 24)
        lay.setSpacing(14)
        lay.addWidget(lockup(40, tagline=True, large=True))
        sub = QLabel("Entre com seu usuário para continuar.")
        sub.setObjectName("pageSub")
        lay.addWidget(sub)
        form.setSpacing(10)
        lay.addLayout(form)
        lay.addWidget(self.err)
        lay.addLayout(row)
        ok.setDefault(True)
        ok.clicked.connect(self._try)
        cancel.clicked.connect(self.reject)

    def _try(self) -> None:
        with self.ctx.db.session_scope() as s:
            u = user_service.authenticate(s, self.user.text().strip().lower(), self.pwd.text())
            uid = u.id if u else None
        if uid:
            self.user_id = uid
            self.accept()
            return
        self.tries += 1
        self.pwd.clear()
        if self.tries >= self.MAX_TRIES:
            self.err.setText("Muitas tentativas. O programa será fechado.")
            self.reject()
        else:
            self.err.setText(f"Usuário ou senha incorretos. Tentativa {self.tries} de {self.MAX_TRIES}.")
