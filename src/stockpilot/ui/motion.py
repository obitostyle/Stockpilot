"""Animações discretas e rápidas (sem atrasar operações): troca de tela e abertura de diálogos."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QDialog, QGraphicsOpacityEffect, QMessageBox, QPushButton, QWidget

PAGE_MS = 140
DIALOG_MS = 110
NAV_MS = 180


def fade_in(widget: QWidget, ms: int = PAGE_MS) -> None:
    """Esmaece a tela de 0 a 1. O efeito é removido no fim para não custar desempenho."""
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeleteWhenStopped)


class _DialogFader(QObject):
    def eventFilter(self, obj, event):  # noqa: N802 (API do Qt)
        if event.type() == QEvent.Polish and isinstance(obj, QPushButton) and not obj.property("_glyph"):
            obj.setProperty("_glyph", True)
            _glyph_to_icon(obj)
        if event.type() == QEvent.Show and isinstance(obj, QDialog) and not obj.property("_faded"):
            obj.setProperty("_faded", True)
            lay = obj.layout()
            if lay is not None and not isinstance(obj, QMessageBox):
                m = lay.contentsMargins()  # respiro padrão em todos os formulários
                if max(m.left(), m.top(), m.right(), m.bottom()) < 20:
                    lay.setContentsMargins(24, 22, 24, 20)
                if lay.spacing() < 10:
                    lay.setSpacing(12)
            obj.setWindowOpacity(0.0)
            anim = QPropertyAnimation(obj, b"windowOpacity", obj)
            anim.setDuration(DIALOG_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        return False


_GLYPHS = {"＋": "plus", "+": "plus", "−": "minus", "-": "minus"}


def _glyph_to_icon(btn: QPushButton) -> None:
    """Troca "＋ Novo…" / "− Saída" por um ícone de traço fino, no padrão dos demais ícones."""
    text = btn.text()
    head, _, rest = text.partition(" ")
    name = _GLYPHS.get(head)
    if not name or not rest or not btn.icon().isNull():
        return
    from .icons import action_icon
    from .theme import MUTED, TEXT
    primary = btn.property("role") == "primary"
    btn.setText(rest.strip())
    btn.setIcon(action_icon(name, "#FFFFFF" if primary else MUTED, None if primary else TEXT, 14))
    btn.setIconSize(QSize(14, 14))


_fader: _DialogFader | None = None


def install(app) -> None:
    """Abertura suave de todas as janelas de diálogo (inclui mensagens de confirmação)."""
    global _fader
    if _fader is None:
        _fader = _DialogFader(app)
        app.installEventFilter(_fader)
