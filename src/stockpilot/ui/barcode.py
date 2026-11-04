"""Leitores de código de barras USB (modo teclado / HID).

Esses leitores "digitam" o código muito rápido (poucos milissegundos entre as teclas) e quase
sempre enviam Enter (às vezes Tab) no final. O ScanDetector reconhece essa rajada em qualquer
campo da tela, impede que o Enter final dispare o botão padrão (ex.: salvar o cadastro antes da
hora) e entrega o código limpo à tela. Digitação humana é bem mais lenta e não é confundida.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

MAX_GAP = 0.060      # intervalo máximo entre teclas de uma leitura (s)
MIN_LEN = 4          # códigos de barras do sistema têm de 4 a 14 dígitos
_BARCODE = re.compile(r"\d{4,14}")


def normalize_scan(text: str | None) -> str:
    """Remove espaços e caracteres de controle que alguns leitores enviam (prefixo/sufixo)."""
    return re.sub(r"[\s\x00-\x1f\x7f]", "", text or "")


def looks_like_barcode(text: str | None) -> bool:
    return bool(_BARCODE.fullmatch(normalize_scan(text)))


class ScanDetector(QObject):
    """Observa o teclado enquanto `scope` (uma tela ou diálogo) está ativa e reconhece leituras.

    on_scan(code, source) é chamado com o código e o campo que recebeu os caracteres (ou None).
    Se o campo de origem não é o destino da leitura, os caracteres da rajada são retirados dele.
    """

    def __init__(self, scope: QWidget, on_scan: Callable[[str, QWidget | None], None],
                 keep_in: Callable[[QWidget | None], bool] | None = None):
        super().__init__(scope)
        self.scope = scope
        self.on_scan = on_scan
        self.keep_in = keep_in or (lambda w: False)  # campos onde o texto lido pode ficar
        self._buf: list[str] = []
        self._last = 0.0
        self._source: QWidget | None = None
        _hub().add(self)
        scope.destroyed.connect(lambda *_: _hub().remove(self))

    def _active(self) -> bool:
        try:
            if not self.scope.isVisible():
                return False
            fw = QApplication.focusWidget()
            win = self.scope.window()
            return fw is not None and fw.window() is win and (fw is self.scope or self.scope.isAncestorOf(fw))
        except RuntimeError:  # objeto Qt já destruído
            return False

    def handle(self, obj, ev) -> bool:
        if not self._active():
            return False
        now = time.monotonic()
        key = ev.key()
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab):
            burst = len(self._buf) >= MIN_LEN and (now - self._last) <= MAX_GAP * 2
            code = normalize_scan("".join(self._buf))
            source = self._source
            self._buf.clear()
            if burst and code:
                if isinstance(source, QLineEdit) and not self.keep_in(source):
                    t = source.text()
                    if t.endswith(code):  # devolve o campo como estava antes da leitura
                        source.setText(t[: len(t) - len(code)])
                self.on_scan(code, source)
                return True  # o Enter do leitor não aciona o botão padrão da janela
            return False
        text = ev.text()
        if len(text) == 1 and text.isprintable() and not (ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier)):
            if now - self._last > MAX_GAP:
                self._buf = []
                self._source = obj
            self._buf.append(text)
            self._last = now
        else:
            self._buf.clear()
        return False


class _Hub(QObject):
    """Um único filtro de teclado no aplicativo, repassado só às telas com leitor ativo."""

    def __init__(self):
        super().__init__(QApplication.instance())
        self.detectors: list[ScanDetector] = []
        QApplication.instance().installEventFilter(self)

    def add(self, d: ScanDetector) -> None:
        self.detectors.append(d)

    def remove(self, d: ScanDetector) -> None:
        if d in self.detectors:
            self.detectors.remove(d)

    def eventFilter(self, obj, ev):  # noqa: N802 (API do Qt)
        if ev.type() != QEvent.KeyPress or not self.detectors or obj is not QApplication.focusWidget():
            return False
        for d in reversed(self.detectors):  # o mais recente (ex.: um diálogo aberto) tem prioridade
            if d._active():
                return d.handle(obj, ev)
        return False


_HUB: _Hub | None = None


def _hub() -> _Hub:
    global _HUB
    if _HUB is None:
        _HUB = _Hub()
    return _HUB
