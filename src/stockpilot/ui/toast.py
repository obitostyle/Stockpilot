"""Notificação flutuante (toast): feedback imediato após uma ação concluída, sem exigir clique."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from .icons import glyph
from .theme import DANGER, OK, WARN

_COLORS = {"success": OK, "error": DANGER, "warning": WARN}
_ICONS = {"success": "check", "error": "alert", "warning": "alert"}


def show_toast(parent: QWidget, text: str, kind: str = "success", ms: int = 2600) -> QFrame:
    host = parent.window()
    t = QFrame(host)
    t.setObjectName("toast")
    t.setProperty("kind", kind)
    t.setAttribute(Qt.WA_TransparentForMouseEvents)
    lay = QHBoxLayout(t)
    lay.setContentsMargins(14, 10, 18, 10)
    lay.setSpacing(10)
    icon = QLabel()
    icon.setPixmap(glyph(_ICONS.get(kind, "check"), _COLORS.get(kind, OK), 16))
    lay.addWidget(icon)
    msg = QLabel(text)
    msg.setObjectName("toastText")
    msg.setWordWrap(True)
    msg.setMaximumWidth(420)
    lay.addWidget(msg)
    t.adjustSize()
    t.move(host.width() - t.width() - 32, host.height() - t.height() - 96)  # acima da linha de botões
    eff = QGraphicsOpacityEffect(t)
    t.setGraphicsEffect(eff)
    t.show()
    t.raise_()
    fade = QPropertyAnimation(eff, b"opacity", t)
    fade.setDuration(160)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.OutCubic)
    fade.start()

    def close():
        out = QPropertyAnimation(eff, b"opacity", t)
        out.setDuration(220)
        out.setStartValue(1.0)
        out.setEndValue(0.0)
        out.finished.connect(t.deleteLater)
        out.start()
        t._out = out  # mantém referência viva
    QTimer.singleShot(ms, close)
    t._fade = fade
    return t
