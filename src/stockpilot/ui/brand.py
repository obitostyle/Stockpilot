"""Identidade visual do StockPilot: símbolo (caixa de estoque com seta de navegação) e assinatura.

Tudo é desenhado a partir de SVG embutido — nada depende de internet ou de arquivos externos.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import APP_NAME

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5B95FF"/><stop offset="1" stop-color="#2F62E0"/></linearGradient></defs>
<rect width="256" height="256" rx="60" fill="url(#g)"/>
<path d="M128 48 L198 86 L128 124 L58 86 Z" fill="#FFFFFF"/>
<path d="M58 104 L120 138 L120 210 L58 176 Z" fill="#FFFFFF" fill-opacity="0.78"/>
<path d="M136 138 L198 104 L198 176 L136 210 Z" fill="#FFFFFF" fill-opacity="0.5"/>
<path d="M128 62 L156 88 L128 80 L100 88 Z" fill="#2F62E0"/>
</svg>"""

TAGLINE = "Gestão para o seu comércio"


def logo_pixmap(size: int) -> QPixmap:
    scale = 2
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(LOGO_SVG.encode())).render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(s))
    return icon


def logo_label(size: int) -> QLabel:
    lbl = QLabel()
    lbl.setPixmap(logo_pixmap(size))
    lbl.setFixedSize(size, size)
    lbl.setObjectName("logoMark")
    return lbl


def lockup(size: int = 34, tagline: bool = True, large: bool = False) -> QWidget:
    """Símbolo + nome StockPilot (+ linha de apoio)."""
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(12 if large else 10)
    h.addWidget(logo_label(size))
    v = QVBoxLayout()
    v.setSpacing(0)
    name = QLabel(APP_NAME)
    name.setObjectName("brandLarge" if large else "brand")
    v.addWidget(name)
    if tagline:
        sub = QLabel(TAGLINE)
        sub.setObjectName("brandSub")
        v.addWidget(sub)
    h.addLayout(v, 1)
    return w
