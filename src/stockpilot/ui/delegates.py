"""Células desenhadas das tabelas: realce da linha inteira, selos de situação e medidor de estoque.

Tudo é pintado com QPainter (sem dependências). Os dados e a ordenação das tabelas não mudam:
os selos e medidores só apresentam o texto/valores que a tela já colocou na célula.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .theme import ACCENT, BORDER, DANGER, MUTED, OK, ROW_HOVER, SUBTLE, WARN

PILL_ROLE = Qt.UserRole + 20   # tipo do selo: "ok" | "warn" | "danger" | "neutral" | "accent"
LEVEL_ROLE = Qt.UserRole + 21  # (quantidade, mínimo) para o medidor de estoque

_PILL_COLORS = {"ok": OK, "warn": WARN, "danger": DANGER, "neutral": SUBTLE, "accent": ACCENT}

# Situações que o sistema já exibe → tom do selo
STATUS_TONES = {
    "ativo": "ok", "ativa": "ok", "concluída": "ok", "confirmada": "ok", "quitada": "ok", "paga": "ok", "pago": "ok",
    "rascunho": "warn", "em aberto": "warn", "em férias": "warn", "afastado": "warn", "parcial": "warn",
    "cancelada": "danger", "cancelado": "danger", "vencida": "danger", "vencido": "danger",
    "estornada": "danger", "estornado": "danger",
    "inativo": "neutral", "inativa": "neutral", "desligado": "neutral", "desligada": "neutral",
}
MOVEMENT_TONES = {"entrada": "ok", "saída": "neutral", "ajuste": "accent", "inventário": "accent", "estorno": "warn"}


def tone_for(header: str, text: str) -> str | None:
    t = (text or "").strip().lower()
    if header == "Situação":
        return STATUS_TONES.get(t)
    if header == "Tipo":
        return MOVEMENT_TONES.get(t)
    return None


class TableDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        table = self.parent()
        selected = bool(option.state & QStyle.State_Selected)
        if not selected and getattr(table, "hover_row", -1) == index.row():
            painter.fillRect(option.rect, QColor(ROW_HOVER))  # a linha inteira acende, não só a célula
        tone = index.data(PILL_ROLE)
        level = index.data(LEVEL_ROLE)
        if not tone and not level:
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        opt.widget.style().drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget) if opt.widget else None
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if tone:
            self._pill(painter, option, text, tone)
        else:
            self._level(painter, option, text, level, index)
        painter.restore()

    @staticmethod
    def _pill(p: QPainter, option, text: str, tone: str) -> None:
        col = QColor(_PILL_COLORS.get(tone, SUBTLE))
        f = QFont(option.font)
        f.setPointSizeF(max(7.5, f.pointSizeF() - 1.2))
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        h = 20
        w = fm.horizontalAdvance(text) + 26
        r = QRectF(option.rect.left() + 8, option.rect.center().y() - h / 2 + 0.5, w, h)
        bg = QColor(col)
        bg.setAlpha(30)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setBrush(col)
        p.drawEllipse(QRectF(r.left() + 9, r.center().y() - 2.5, 5, 5))
        p.setPen(col if tone != "neutral" else QColor(MUTED))
        p.setFont(f)
        p.drawText(r.adjusted(18, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, text)

    @staticmethod
    def _level(p: QPainter, option, text: str, level, index) -> None:
        qty, minimum = (float(level[0]), float(level[1]))
        rect = option.rect
        if qty <= 0:
            col = QColor(DANGER)
        elif minimum > 0 and qty < minimum:
            col = QColor(WARN)
        else:
            col = QColor(OK)
        # trilho + preenchimento: referência = 2× o mínimo (cheio = folga confortável)
        ref = minimum * 2 if minimum > 0 else max(qty, 1)
        frac = max(0.0, min(1.0, qty / ref)) if ref else 0
        bar_w = 34
        track = QRectF(rect.left() + 10, rect.center().y() - 2, bar_w, 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BORDER))
        p.drawRoundedRect(track, 2, 2)
        if frac > 0:
            p.setBrush(col)
            p.drawRoundedRect(QRectF(track.left(), track.top(), max(4.0, bar_w * frac), 4), 2, 2)
        p.setPen(col if qty <= 0 or (minimum > 0 and qty < minimum) else option.palette.text().color())
        p.setFont(option.font)
        p.drawText(rect.adjusted(bar_w + 16, 0, -10, 0), Qt.AlignVCenter | Qt.AlignRight, text)
