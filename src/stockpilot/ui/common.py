from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..domain.errors import BusinessError, ValidationError
from ..domain.formatting import parse_decimal_br

log = logging.getLogger("stockpilot.ui")


class SortItem(QTableWidgetItem):
    """Item de tabela que ordena por um valor real (número/data) e não pelo texto."""

    def __init__(self, text: str, key=None, align_right: bool = False):
        super().__init__(text)
        self._key = key if key is not None else text.lower()
        self.setToolTip(text)  # texto completo quando a coluna estiver cortada
        if align_right:
            self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, SortItem):
            try:
                return self._key < other._key
            except TypeError:
                return str(self._key) < str(other._key)
        return super().__lt__(other)


class DataTable(QTableWidget):
    """Tabela padrão do sistema: mostra uma mensagem discreta quando não há linhas."""

    empty_text = "Nenhum registro para exibir"

    hover_row = -1

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        from .delegates import TableDelegate
        self.setItemDelegate(TableDelegate(self))
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):  # noqa: N802 — realce da linha sob o mouse
        from PySide6.QtCore import QEvent
        if obj is self.viewport():
            if ev.type() == QEvent.MouseMove:
                row = self.rowAt(int(ev.position().y()))
                if row != self.hover_row:
                    self.hover_row = row
                    self.viewport().update()
            elif ev.type() == QEvent.Leave and self.hover_row != -1:
                self.hover_row = -1
                self.viewport().update()
        return super().eventFilter(obj, ev)

    def setItem(self, row, col, item) -> None:  # noqa: N802 (API do Qt)
        if item is not None:
            head = self.horizontalHeaderItem(col)
            if head is not None:
                from .delegates import PILL_ROLE, tone_for
                tone = tone_for(head.text(), item.text())
                if tone:
                    item.setData(PILL_ROLE, tone)
        super().setItem(row, col, item)
        # o título da coluna segue o alinhamento dos dados (números à direita, texto à esquerda)
        if row == 0 and item is not None:
            head = self.horizontalHeaderItem(col)
            if head is not None:
                right = bool(item.textAlignment() & Qt.AlignRight)
                want = (Qt.AlignRight if right else Qt.AlignLeft) | Qt.AlignVCenter
                if int(head.textAlignment()) != int(want):
                    head.setTextAlignment(want)

    def paintEvent(self, e) -> None:  # noqa: N802 (API do Qt)
        super().paintEvent(e)
        if self.rowCount() == 0 and self.empty_text:
            from PySide6.QtGui import QColor, QPainter

            from .theme import SUBTLE
            p = QPainter(self.viewport())
            p.setPen(QColor(SUBTLE))
            p.drawText(self.viewport().rect(), Qt.AlignCenter, self.empty_text)
            p.end()


def make_table(headers: list[str], widths: dict[int, int] | None = None,
               stretch: tuple[int, ...] = (1,)) -> QTableWidget:
    """Colunas em `widths` têm largura inicial fixa (redimensionável pelo usuário);
    colunas em `stretch` dividem o espaço restante; as demais se ajustam ao conteúdo."""
    t = DataTable(0, len(headers))
    t.setMouseTracking(True)  # realce ao passar o mouse
    t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)  # rolagem suave
    t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(36)
    t.horizontalHeader().setSortIndicator(1, Qt.AscendingOrder)  # padrão: A→Z pela 2ª coluna
    t.setSortingEnabled(True)
    t.setShowGrid(False)
    t.setWordWrap(False)  # linhas de altura uniforme; texto longo termina em "…" e aparece completo na dica
    t.setTextElideMode(Qt.ElideRight)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    t.horizontalHeader().setHighlightSections(False)
    h = t.horizontalHeader()
    h.setMinimumSectionSize(50)
    h.setStretchLastSection(False)
    for col in range(len(headers)):
        if col in stretch:
            h.setSectionResizeMode(col, QHeaderView.Stretch)
        elif widths and col in widths:
            h.setSectionResizeMode(col, QHeaderView.Interactive)
            t.setColumnWidth(col, widths[col])
        else:
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
    return t


def title_block(title: str, subtitle: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    a = QLabel(title)
    a.setObjectName("pageTitle")
    lay.addWidget(a)
    if subtitle:
        b = QLabel(subtitle)
        b.setObjectName("pageSub")
        lay.addWidget(b)
    return w


def primary(btn: QPushButton) -> QPushButton:
    btn.setProperty("role", "primary")
    return btn


def danger(btn: QPushButton) -> QPushButton:
    btn.setProperty("role", "danger")
    return btn


def card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


def read_decimal(edit: QLineEdit, label: str, default: str | None = "0") -> Decimal:
    text = edit.text().strip()
    if not text:
        if default is None:
            raise ValidationError(f"{label}: informe um valor.")
        return Decimal(default)
    try:
        return parse_decimal_br(text)
    except ValueError:
        raise ValidationError(f"{label}: valor inválido ('{text}'). Exemplo: 1.234,56")


def run_action(parent: QWidget, fn: Callable[[], object]) -> bool:
    """Executa uma ação de UI tratando erros de forma compreensível. True = sucesso."""
    try:
        fn()
        return True
    except ValidationError as exc:
        QMessageBox.warning(parent, "Verifique os dados", "\n".join(f"• {m}" for m in exc.messages))
    except BusinessError as exc:
        QMessageBox.warning(parent, "Não foi possível concluir", str(exc))
    except Exception:  # erro inesperado: registra e informa sem mostrar traceback ao lojista
        log.exception("Erro inesperado na interface")
        QMessageBox.critical(
            parent, "Erro inesperado",
            "Ocorreu um erro inesperado e a operação foi desfeita. Nenhum dado foi alterado.\n"
            "Os detalhes foram gravados no arquivo de log para o suporte.",
        )
    return False


def confirm(parent: QWidget, title: str, text: str, yes_text: str = "Confirmar",
            destructive: bool = False, details: str = "") -> bool:
    """Confirmação padrão. Em ações destrutivas o botão fica vermelho e o padrão (Enter) é Cancelar."""
    box = QMessageBox(QMessageBox.Warning if destructive else QMessageBox.Question, title, text,
                      QMessageBox.NoButton, parent)
    if details:
        box.setInformativeText(details)
    cancel = box.addButton("Cancelar", QMessageBox.RejectRole)
    yes = box.addButton(yes_text, QMessageBox.AcceptRole)
    yes.setProperty("role", "danger-solid" if destructive else "primary")
    yes.style().unpolish(yes)
    yes.style().polish(yes)
    box.setDefaultButton(cancel if destructive else yes)
    box.setEscapeButton(cancel)
    box.exec()
    return box.clickedButton() is yes


def toast(parent: QWidget, text: str, kind: str = "success") -> None:
    """Aviso rápido e discreto no canto inferior da janela (some sozinho)."""
    from .toast import show_toast
    show_toast(parent, text, kind)


def scroll_body(page: QWidget) -> QWidget:
    """Coloca o conteúdo da página numa área rolável: em janelas baixas a tela rola em vez de espremer."""
    from PySide6.QtWidgets import QFrame, QScrollArea
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    inner = QWidget()
    inner.setObjectName("page")
    area.setWidget(inner)
    outer.addWidget(area)
    return inner
