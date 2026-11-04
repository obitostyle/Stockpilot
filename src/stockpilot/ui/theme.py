"""Tema visual do StockPilot — modo escuro (padrão).

Toda cor, tipografia e espaçamento da interface vem daqui. As telas só usam
objectName/propriedades ("card", "kpiValue", role="primary"...) e as constantes abaixo.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette

# --- paleta -----------------------------------------------------------------
BG = "#0B0D12"          # fundo principal
SIDEBAR = "#0F1219"     # barra lateral
PANEL = "#141923"       # painéis / cartões
RAISED = "#191F2B"      # elementos elevados (campos, hover, cabeçalhos)
RAISED_2 = "#202838"    # hover sobre elevados
ROW_HOVER = "#1D2433"   # linha de tabela sob o mouse
BORDER = "#252D3A"      # bordas
BORDER_STRONG = "#334155"
TEXT = "#F1F5F9"        # texto principal
MUTED = "#94A3B8"       # texto secundário
SUBTLE = "#8291A7"      # texto terciário (contraste 5,5:1 sobre painéis — WCAG AA)
DISABLED = "#566173"    # texto desabilitado (isento de contraste mínimo)
ACCENT = "#4F8CFF"      # azul de destaque
ACCENT_HOVER = "#6B9FFF"
ACCENT_PRESS = "#3B78EC"
ACCENT_SOFT = "#1A2740"  # fundo de seleção / destaque suave
PRIMARY = "#2F6FE8"      # fundo do botão primário (texto branco 4,6:1)
PRIMARY_HOVER = "#2A66DA"
PRIMARY_PRESS = "#245BC4"
OK = "#34D399"
WARN = "#FBBF24"
DANGER = "#F87171"
DANGER_SOFT = "#2A1619"

# nomes antigos mantidos para compatibilidade com módulos existentes
NAVY = TEXT
BLUE = ACCENT
BLUE_LIGHT = ACCENT_SOFT
CARD = PANEL

FONT = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", sans-serif'
NUM_FONT = '"Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Variable Display", "Segoe UI", "Inter", "Noto Sans", sans-serif'
# Bahnschrift (fonte DIN que acompanha o Windows): títulos e números — a "assinatura" visual do StockPilot.
DISPLAY_FONT = NUM_FONT

# cores semânticas para texto em tabelas (situações que o sistema já identifica)
def color_positive() -> QColor: return QColor(OK)
def color_negative() -> QColor: return QColor(DANGER)
def color_inactive() -> QColor: return QColor(DISABLED)
def color_warning() -> QColor: return QColor(WARN)


QSS = f"""
* {{ font-family: {FONT}; font-size: 10pt; color: {TEXT}; outline: none; }}
QMainWindow, QDialog, QWidget#page, QStackedWidget {{ background: {BG}; }}
QWidget {{ selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QLabel {{ background: transparent; }}

/* ---------- barra lateral ---------- */
QFrame#sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ color: {TEXT}; font-size: 12.5pt; font-weight: 700; padding: 0; }}
QLabel#brandSub {{ color: {SUBTLE}; font-size: 8.5pt; padding: 0; }}
QLabel#navSection {{ color: {SUBTLE}; font-size: 7.5pt; font-weight: 700; padding: 14px 22px 6px 22px; }}
QLabel#version {{ color: {SUBTLE}; font-size: 8pt; padding: 12px 22px 16px 22px; }}
QPushButton#nav {{ color: {MUTED}; background: transparent; border: none; border-radius: 7px; text-align: left;
    padding: 7px 12px; margin: 1px 10px; font-size: 10pt; font-weight: 500; }}
QPushButton#nav:hover {{ background: {RAISED}; color: {TEXT}; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; font-weight: 600; }}

/* ---------- títulos e textos ---------- */
QLabel#pageTitle {{ font-size: 17pt; font-weight: 700; color: {TEXT}; }}
QLabel#pageSub {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#sectionTitle {{ font-size: 10.5pt; font-weight: 600; color: {TEXT}; }}
QLabel#error {{ color: {DANGER}; }}
QLabel#hint {{ background: {ACCENT_SOFT}; color: #C9DAFF; border: 1px solid #23365A; border-radius: 8px; padding: 10px 14px; }}
QDialog QLabel#hint {{ margin-bottom: 6px; }}

/* ---------- cartões e indicadores ---------- */
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#card QLabel {{ background: transparent; }}
QLabel#kpiLabel {{ color: {MUTED}; font-size: 9pt; font-weight: 500; }}
QLabel#kpiValue {{ color: {TEXT}; font-family: {NUM_FONT}; font-size: 19pt; font-weight: 600; }}
QLabel#kpiNote {{ color: {SUBTLE}; font-size: 8.5pt; }}
QFrame#kpiAccent {{ background: {ACCENT}; border: none; border-radius: 1px; }}

/* ---------- campos ---------- */
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit, QSpinBox, QDoubleSpinBox {{
    background: {RAISED}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 10px; color: {TEXT};
    selection-background-color: {ACCENT}; selection-color: white; min-height: 18px; }}
QLineEdit:hover, QComboBox:hover, QPlainTextEdit:hover, QTextEdit:hover, QDateEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {BORDER_STRONG}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus, QDateEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {ACCENT}; background: #1B2232; }}
QLineEdit:read-only {{ background: {PANEL}; color: {MUTED}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {SUBTLE}; background: {PANEL}; }}
QLineEdit[echoMode="2"] {{ lineedit-password-character: 9679; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: none; width: 24px; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url(@ICONS@/down.svg); width: 10px; height: 10px; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 4px;
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: transparent; border: none; width: 16px; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url(@ICONS@/up.svg); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url(@ICONS@/down.svg); width: 9px; height: 9px; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {TEXT}; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; background: {RAISED}; border: 1px solid {BORDER_STRONG}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(@ICONS@/check.svg); }}
QRadioButton::indicator:checked {{ background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
    stop:0 white, stop:0.35 white, stop:0.45 {ACCENT}, stop:1 {ACCENT}); border-color: {ACCENT}; }}

QGroupBox {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px; padding: 14px 12px 10px 12px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {MUTED}; font-weight: 600; }}

/* ---------- botões ---------- */
QPushButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 7px; padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ background: {RAISED_2}; border-color: {BORDER_STRONG}; }}
QPushButton:pressed {{ background: {PANEL}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {SUBTLE}; background: {PANEL}; border-color: {BORDER}; }}
QPushButton[role="primary"] {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[role="primary"]:pressed {{ background: {ACCENT_PRESS}; }}
QPushButton[role="primary"]:disabled {{ background: #22314D; color: #7C8DAD; border-color: #22314D; }}
QPushButton[role="danger"] {{ background: transparent; color: {DANGER}; border: 1px solid #4A2328; }}
QPushButton[role="danger"]:hover {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}
QDialogButtonBox QPushButton {{ min-width: 84px; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 4px; color: {MUTED}; }}
QToolButton:hover {{ background: {RAISED}; color: {TEXT}; }}

/* ---------- tabelas e listas ---------- */
QTableWidget, QTableView, QTreeView {{ background: {PANEL}; alternate-background-color: #161C27; border: 1px solid {BORDER};
    border-radius: 10px; gridline-color: {BORDER}; color: {TEXT};
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QTableWidget::item, QTableView::item {{ padding: 0 10px; border: none; border-bottom: 1px solid #1C2330; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {PANEL}; color: {MUTED}; padding: 9px 10px; border: none;
    border-bottom: 1px solid {BORDER}; font-size: 8.5pt; font-weight: 600; }}
QHeaderView::section:hover {{ color: {TEXT}; }}
QHeaderView::up-arrow, QHeaderView::down-arrow {{ width: 8px; height: 8px; subcontrol-position: center right; padding-right: 6px; }}
QTableCornerButton::section {{ background: {PANEL}; border: none; }}

QListWidget {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; padding: 6px; outline: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; color: {MUTED}; }}
QListWidget::item:hover:!selected {{ background: {RAISED}; color: {TEXT}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; font-weight: 600; }}

/* ---------- abas ---------- */
QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; top: -1px; background: transparent; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {MUTED}; padding: 9px 4px; margin-right: 22px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

/* ---------- calendário (seleção de datas) ---------- */
QCalendarWidget QWidget {{ alternate-background-color: {RAISED}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {RAISED}; border-bottom: 1px solid {BORDER}; }}
QCalendarWidget QToolButton {{ color: {TEXT}; font-weight: 600; padding: 4px 8px; }}
QCalendarWidget QMenu {{ background: {RAISED}; }}
QCalendarWidget QAbstractItemView {{ background: {PANEL}; color: {TEXT}; selection-background-color: {ACCENT};
    selection-color: white; outline: none; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {SUBTLE}; }}

/* ---------- menus, dicas, mensagens ---------- */
QMenu {{ background: {RAISED}; border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; border-radius: 6px; padding: 6px 9px; }}
QMessageBox {{ background: {PANEL}; }}
QMessageBox QLabel {{ color: {TEXT}; }}
QProgressBar {{ background: {RAISED}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}

/* ---------- barra de status ---------- */
QStatusBar {{ background: {SIDEBAR}; border-top: 1px solid {BORDER}; color: {SUBTLE}; font-size: 8.5pt; }}
QStatusBar QLabel {{ color: {SUBTLE}; }}

/* ---------- rolagem ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2A3343; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3A4659; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2A3343; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: #3A4659; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {BORDER}; }}

/* ---------- refinamentos v0.3 ---------- */
QPushButton[role="danger-solid"] {{ background: #DC4C4C; color: white; border: 1px solid #DC4C4C; font-weight: 600; }}
QPushButton[role="danger-solid"]:hover {{ background: {DANGER}; border-color: {DANGER}; }}
QPushButton[role="danger"] {{ padding-left: 12px; }}
QMessageBox {{ background: {PANEL}; }}
QMessageBox QLabel {{ color: {TEXT}; font-size: 10pt; min-width: 300px; }}
QMessageBox QLabel#qt_msgbox_informativelabel {{ color: {MUTED}; font-size: 9.5pt; }}
QMessageBox QPushButton {{ min-width: 92px; padding: 7px 16px; }}
QMessageBox QPushButton[role="danger-solid"] {{ background: #DC4C4C; color: white; border: 1px solid #DC4C4C; font-weight: 600; }}
QMessageBox QPushButton[role="danger-solid"]:hover {{ background: {DANGER}; }}
QMessageBox QPushButton[role="primary"] {{ background: {ACCENT}; color: white; border: 1px solid {ACCENT}; font-weight: 600; }}
QMessageBox QPushButton[role="primary"]:hover {{ background: {ACCENT_HOVER}; }}
QFrame#toast {{ background: {RAISED}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; }}
QFrame#toast[kind="success"] {{ border-left: 3px solid {OK}; }}
QFrame#toast[kind="error"] {{ border-left: 3px solid {DANGER}; }}
QFrame#toast[kind="warning"] {{ border-left: 3px solid {WARN}; }}
QLabel#toastText {{ color: {TEXT}; font-size: 9.5pt; font-weight: 500; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; }}
QLabel#kpiValue[tone="negative"] {{ color: {DANGER}; }}
QLabel#kpiValue[tone="positive"] {{ color: {TEXT}; }}
QLabel#kpiNote[tone="warn"] {{ color: {WARN}; }}
QFrame#kpiCard {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#kpiCard:hover {{ border-color: {BORDER_STRONG}; background: #161C28; }}
QFrame#kpiCard[hero="true"] {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17213A, stop:1 {PANEL});
    border-color: #26365A; }}
QLabel#kpiValue[hero="true"] {{ font-size: 22pt; }}
QPushButton#nav:checked {{ background: {ACCENT_SOFT}; color: {TEXT}; font-weight: 600; border-left: 2px solid {ACCENT};
    border-top-left-radius: 2px; border-bottom-left-radius: 2px; padding-left: 10px; }}
QLabel#navSection {{ padding-top: 14px; }}
QStatusBar::item {{ border: none; }}
QScrollArea#sideScroll, QFrame#sidebarNav {{ background: {SIDEBAR}; border: none; }}
QScrollArea#sideScroll QScrollBar:vertical {{ width: 6px; }}

/* ---------- marca, barra superior e bloqueio ---------- */
QLabel#logoMark {{ background: transparent; }}
QLabel#brandLarge {{ color: {TEXT}; font-size: 20pt; font-weight: 700; }}
QFrame#topbar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QLabel#crumb {{ color: {SUBTLE}; font-size: 9pt; }}
QLabel#crumbCurrent {{ color: {TEXT}; font-size: 9pt; font-weight: 600; }}
QPushButton#companyChip {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 15px; padding: 5px 14px 5px 10px;
    color: {TEXT}; font-size: 9pt; font-weight: 500; text-align: left; }}
QPushButton#companyChip:hover {{ border-color: {BORDER_STRONG}; background: {RAISED}; }}
QPushButton#companyChip[warn="true"] {{ color: {WARN}; border-color: #4A3B17; background: #1E1A10; }}

/* ---------- formulários destacados ---------- */
QLabel#fieldLabel {{ color: {TEXT}; font-size: 9.5pt; font-weight: 600; }}
QLabel#fieldError {{ color: {DANGER}; font-size: 8.5pt; }}
QLabel#fieldError[ok="true"] {{ color: {OK}; }}
QLineEdit#bigInput {{ padding: 10px 12px; font-size: 10.5pt; border-radius: 8px; }}
QLineEdit[state="error"] {{ border: 1px solid {DANGER}; }}
QLineEdit[state="ok"] {{ border: 1px solid #1F6B52; }}
QPushButton#bigPrimary {{ padding: 11px 14px; font-size: 10.5pt; border-radius: 8px; }}
QPushButton#linkButton {{ background: transparent; border: none; color: {MUTED}; padding: 6px 10px; }}
QPushButton#linkButton:hover {{ color: {TEXT}; background: transparent; }}

/* ================= design system v0.4 — "Precision Dark" =================
   Escala tipográfica: título de página 19pt Bahnschrift · seção 11pt 600 · corpo 10pt · auxiliar 9pt
   Espaçamento: 4 · 8 · 12 · 16 · 24 · 32   |   Raios: campos/botões 6px · painéis 10px
   O azul de destaque só aparece em ação primária, item ativo, foco e seleção. */
QLabel#pageTitle {{ font-family: {DISPLAY_FONT}; font-size: 19pt; font-weight: 600; color: {TEXT}; }}
QLabel#pageSub {{ color: {MUTED}; font-size: 9.5pt; }}
QLabel#sectionTitle {{ font-size: 11pt; font-weight: 600; color: {TEXT}; }}
QLabel#sectionNote {{ color: {SUBTLE}; font-size: 9pt; }}
QLabel#navSection {{ color: {SUBTLE}; font-size: 8.5pt; font-weight: 600; padding: 16px 22px 6px 22px; }}
QLabel#brand {{ font-family: {DISPLAY_FONT}; font-size: 13.5pt; font-weight: 600; }}

QPushButton {{ border-radius: 6px; min-height: 18px; }}
QPushButton[role="primary"] {{ background: {PRIMARY}; border: 1px solid {PRIMARY}; color: white; }}
QPushButton[role="primary"]:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
QPushButton[role="primary"]:pressed {{ background: {PRIMARY_PRESS}; }}
QPushButton[role="primary"]:focus {{ border: 1px solid {ACCENT_HOVER}; }}
QPushButton[role="ghost"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton[role="ghost"]:hover {{ background: {RAISED}; color: {TEXT}; border-color: {BORDER}; }}
QPushButton[role="ghost"]:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled, QPushButton[role="danger"]:disabled, QPushButton[role="ghost"]:disabled {{ color: {DISABLED}; }}
QMessageBox QPushButton[role="primary"] {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
QLineEdit, QComboBox, QDateEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{ border-radius: 6px; }}
QLineEdit[state="error"], QComboBox[state="error"] {{ border: 1px solid {DANGER}; }}

/* avisos: neutros, com um fio azul à esquerda — informam sem competir com o conteúdo */
QLabel#hint {{ background: {PANEL}; color: {MUTED}; border: 1px solid {BORDER}; border-left: 2px solid {ACCENT};
    border-radius: 6px; padding: 10px 14px; }}

/* faixas de indicadores (painel inicial): um só painel dividido por fios, em vez de vários cartões */
QFrame#strip {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#stripDivider {{ background: {BORDER}; border: none; max-width: 1px; min-width: 1px; }}
QFrame#kpiCell {{ background: transparent; border: none; }}
QLabel#formLabel {{ color: {MUTED}; font-size: 9pt; font-weight: 500; padding-top: 10px; }}
QLabel#scanStatus {{ font-size: 9pt; padding: 2px 0; color: {MUTED}; }}
QLabel#scanStatus[tone="ok"] {{ color: {OK}; }}
QLabel#scanStatus[tone="warn"] {{ color: {WARN}; }}
QLabel#scanStatus[tone="error"] {{ color: {DANGER}; }}
QLineEdit[state="ok"] {{ border: 1px solid #1F6B52; }}
QFrame#hDivider {{ background: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}
QLabel#kpiValue {{ font-family: {NUM_FONT}; font-size: 20pt; font-weight: 600; color: {TEXT}; }}
QLabel#kpiValue[hero="true"] {{ font-size: 24pt; }}
QLabel#kpiLabel {{ color: {MUTED}; font-size: 9pt; font-weight: 500; }}
QLabel#kpiNote {{ color: {SUBTLE}; font-size: 8.5pt; }}
QFrame#card {{ border-radius: 10px; }}

/* tabelas: cabeçalho discreto alinhado aos dados, linhas de 36px, sem grade */
QHeaderView::section {{ background: {PANEL}; color: {SUBTLE}; font-size: 8.5pt; font-weight: 600; padding: 9px 10px;
    border: none; border-bottom: 1px solid {BORDER}; }}
QTableWidget::item, QTableView::item {{ border-bottom: 1px solid #1A202B; }}
QTableWidget::item:selected, QTableView::item:selected {{ background: #1B2A45; }}

/* barra superior e identificação da empresa */
QPushButton#companyChip {{ border-radius: 6px; padding: 6px 12px; }}
QLabel#version {{ color: {DISABLED}; }}
QPushButton#nav:focus {{ border: 1px solid {ACCENT}; }}
QPushButton#nav:checked {{ background: transparent; border-left: none; padding-left: 12px; color: {TEXT}; font-weight: 600; }}
QFrame#navIndicator {{ background: {ACCENT_SOFT}; border: 1px solid #22355A; border-radius: 7px; }}
QFrame#navIndicatorBar {{ background: {ACCENT}; border: none; border-radius: 1px; }}
QStatusBar {{ color: {SUBTLE}; }}
"""


def dark_palette() -> QPalette:
    """Paleta nativa do Qt alinhada ao tema (cobre partes que o QSS não alcança)."""
    p = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: PANEL, QPalette.AlternateBase: "#161C27",
        QPalette.ToolTipBase: RAISED, QPalette.ToolTipText: TEXT, QPalette.Text: TEXT, QPalette.Button: RAISED,
        QPalette.ButtonText: TEXT, QPalette.BrightText: "#FFFFFF", QPalette.Highlight: ACCENT,
        QPalette.HighlightedText: "#FFFFFF", QPalette.Link: ACCENT, QPalette.PlaceholderText: SUBTLE,
        QPalette.Light: RAISED_2, QPalette.Midlight: RAISED, QPalette.Mid: BORDER, QPalette.Dark: SIDEBAR,
        QPalette.Shadow: "#000000",
    }
    for role, col in roles.items():
        p.setColor(role, QColor(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor(SUBTLE))
    return p


_SVG = {
    "down.svg": '<path d="M6 9l6 6 6-6"/>',
    "up.svg": '<path d="M18 15l-6-6-6 6"/>',
    "check.svg": '<path d="M20 6L9 17l-5-5"/>',
}


def _icon_dir() -> str:
    """Grava as pequenas setas/marcas usadas pelo QSS numa pasta temporária (QSS só aceita arquivos)."""
    import tempfile
    from pathlib import Path

    d = Path(tempfile.gettempdir()) / "stockpilot-theme"
    d.mkdir(parents=True, exist_ok=True)
    for name, body in _SVG.items():
        color = "#FFFFFF" if name == "check.svg" else MUTED
        width = "3" if name == "check.svg" else "2.2"
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
               f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')
        f = d / name
        if not f.exists() or f.read_text(encoding="utf-8") != svg:
            f.write_text(svg, encoding="utf-8")
    return d.as_posix()


def stylesheet() -> str:
    try:
        return QSS.replace("@ICONS@", _icon_dir())
    except OSError:  # sem pasta temporária gravável: segue sem os ícones das setas
        return QSS


def apply_theme(app) -> None:
    """Aplica o tema escuro a toda a aplicação (estilo Fusion + paleta + QSS)."""
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(stylesheet())
    from . import motion
    motion.install(app)
