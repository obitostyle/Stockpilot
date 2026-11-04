"""Gráfico de vendas por dia: área suave com linha, cursor ao passar o mouse e balão com o valor.

Desenhado com QPainter (sem dependências externas). Mostra apenas os valores recebidos em set_data.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..domain.formatting import format_brl
from .theme import ACCENT, BG, BORDER, BORDER_STRONG, MUTED, RAISED, SUBTLE, TEXT


class BarChart(QWidget):
    """Mantém o nome usado pelas telas; o desenho é um gráfico de área."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data: list[tuple[date, Decimal]] = []
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._hover = -1

    def set_data(self, data: list[tuple[date, Decimal]]) -> None:
        self.data = data
        self._hover = -1
        self.update()

    def _geometry(self) -> QRectF:
        left, right, top, bottom = 52, 14, 18, 26
        return QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))

    def _x(self, r: QRectF, i: int) -> float:
        n = len(self.data)
        return r.left() + (r.width() * i / (n - 1) if n > 1 else r.width() / 2)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        r = self._geometry()
        if self.data and r.adjusted(-10, -10, 10, 10).contains(e.position()):
            n = len(self.data)
            i = round((e.position().x() - r.left()) / (r.width() / max(1, n - 1)))
            i = max(0, min(n - 1, i))
            if i != self._hover:
                self._hover = i
                self.update()
        elif self._hover != -1:
            self._hover = -1
            self.update()

    def leaveEvent(self, e) -> None:  # noqa: N802
        self._hover = -1
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._geometry()
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        if not self.data or all(v == 0 for _, v in self.data):
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "Sem vendas nos últimos 30 dias.\nO gráfico aparece quando houver vendas.")
            return
        top = float(max(v for _, v in self.data)) * 1.12

        # grade e eixo Y
        for i in range(4):
            y = r.bottom() - r.height() * i / 3
            p.setPen(QPen(QColor(BORDER), 1, Qt.SolidLine if i == 0 else Qt.DotLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(QColor(SUBTLE))
            p.drawText(QRectF(0, y - 8, r.left() - 10, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{top * i / 3:,.0f}".replace(",", "."))

        pts = [QPointF(self._x(r, i), r.bottom() - r.height() * float(v) / top) for i, (_, v) in enumerate(self.data)]
        line = QPainterPath(pts[0])
        for a, b in zip(pts, pts[1:]):  # curva suave (pontos de controle no meio do intervalo)
            mx = (a.x() + b.x()) / 2
            line.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
        area = QPainterPath(line)
        area.lineTo(pts[-1].x(), r.bottom())
        area.lineTo(pts[0].x(), r.bottom())
        area.closeSubpath()
        grad = QLinearGradient(0, r.top(), 0, r.bottom())
        c1 = QColor(ACCENT)
        c1.setAlpha(70)
        c2 = QColor(ACCENT)
        c2.setAlpha(0)
        grad.setColorAt(0, c1)
        grad.setColorAt(1, c2)
        p.fillPath(area, grad)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(line)

        # datas no eixo X
        n = len(self.data)
        p.setPen(QColor(SUBTLE))
        for i, (d, _) in enumerate(self.data):
            if i % 5 == 0 or i == n - 1:
                x = self._x(r, i)
                p.drawText(QRectF(x - 24, r.bottom() + 6, 48, 16), Qt.AlignHCenter, f"{d:%d/%m}")

        # cursor + balão
        if 0 <= self._hover < n:
            d, v = self.data[self._hover]
            pt = pts[self._hover]
            p.setPen(QPen(QColor(BORDER_STRONG), 1, Qt.DashLine))
            p.drawLine(QPointF(pt.x(), r.top()), QPointF(pt.x(), r.bottom()))
            p.setPen(QPen(QColor(BG), 2))
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(pt, 4.5, 4.5)
            label = f"{d:%d/%m}   {format_brl(v)}"
            fb = QFont(f)
            fb.setPointSizeF(8.5)
            fb.setWeight(QFont.DemiBold)
            p.setFont(fb)
            w = p.fontMetrics().horizontalAdvance(label) + 20
            bx = min(max(pt.x() - w / 2, r.left()), r.right() - w)
            by = max(r.top() - 6, pt.y() - 36)
            box = QRectF(bx, by, w, 24)
            p.setPen(QPen(QColor(BORDER_STRONG), 1))
            p.setBrush(QColor(RAISED))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor(TEXT))
            p.drawText(box, Qt.AlignCenter, label)
