from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QScrollArea, QLabel, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..app_context import AppContext
from ..config import paths
from ..licensing import service as license_service
from ..domain.enums import UserRole
from ..models import User
from ..domain.validators import format_cnpj
from ..services import backup_service, company_service
from . import motion
from .brand import app_icon, lockup
from .common import primary
from .theme import ACCENT, SUBTLE
from .icons import glyph, nav_icon
from .pages.backup_page import BackupPage
from .pages.company_page import CompanyPage
from .pages.dashboard_page import DashboardPage
from .pages.finance_page import FinancePage
from .pages.payroll_page import PayrollPage
from .pages.products_page import ProductsPage
from .pages.purchases_page import PurchasesPage
from .pages.reports_page import ReportsPage
from .pages.settings_page import SettingsPage
from .pages.sales_page import SalesPage
from .pages.stock_page import StockPage
from .pages.suppliers_page import SuppliersPage
from .pages.tax_page import TaxPage


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1260, 760)
        self.setMinimumSize(1100, 640)

        side = QFrame()
        side.setObjectName("sidebarNav")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        # indicador da seção ativa: desliza até o item escolhido (a única animação de destaque do produto)
        self.nav_indicator = QFrame(side)
        self.nav_indicator.setObjectName("navIndicator")
        bar = QFrame(self.nav_indicator)
        bar.setObjectName("navIndicatorBar")
        bar.setGeometry(0, 9, 3, 16)
        self.nav_indicator.hide()
        self._nav_anim = None
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(20, 22, 16, 10)
        hl.addWidget(lockup(34))

        self.stack = QStackedWidget()
        self.pages = [
            ("Painel", DashboardPage(ctx)), ("Vendas (PDV)", SalesPage(ctx)), ("Produtos", ProductsPage(ctx)),
            ("Estoque", StockPage(ctx)), ("Compras", PurchasesPage(ctx)), ("Fornecedores", SuppliersPage(ctx)),
            ("Financeiro", FinancePage(ctx)), ("Tributário", TaxPage(ctx)), ("Funcionários", PayrollPage(ctx)),
            ("Relatórios", ReportsPage(ctx)), ("Backup", BackupPage(ctx)), ("Empresa", CompanyPage(ctx)),
            ("Configurações", SettingsPage(ctx)),
        ]
        group = QButtonGroup(self)
        group.setExclusive(True)
        self._sections = {}
        for i, (name, page) in enumerate(self.pages):
            if name in self.NAV_SECTIONS:
                lbl = QLabel(self.NAV_SECTIONS[name])
                lbl.setObjectName("navSection")
                sl.addWidget(lbl)
                self._sections[name] = lbl
            btn = QPushButton("   " + name)
            btn.setIcon(nav_icon(name))
            btn.setIconSize(QSize(18, 18))
            if i < 9:
                btn.setToolTip(f"{name} — atalho Ctrl+{i + 1}")
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)  # alcançável pelo Tab; o clique não rola o menu
            group.addButton(btn, i)
            sl.addWidget(btn)
            self.stack.addWidget(page)
            if i < 9:
                QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go(i))
        sl.addStretch()
        ver = QLabel(f"Versão {__version__}")
        ver.setObjectName("version")
        sl.addWidget(ver)
        group.idClicked.connect(self.go)
        self.group = group
        self._apply_role()
        next(p for _, p in self.pages if isinstance(p, CompanyPage)).saved.connect(self._company_saved)
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.stack.currentWidget().refresh())


        top = QFrame()
        top.setObjectName("topbar")
        top.setFixedHeight(52)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(32, 0, 24, 0)
        self.crumb = QLabel("")
        self.crumb.setObjectName("crumb")
        self.crumb.setTextFormat(Qt.RichText)
        tl.addWidget(self.crumb)
        tl.addStretch()
        self.chip = QPushButton()
        self.chip.setObjectName("companyChip")
        self.chip.setCursor(Qt.PointingHandCursor)
        self.chip.setIconSize(QSize(15, 15))
        self.chip.clicked.connect(self._chip_clicked)
        tl.addWidget(self.chip)

        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(top)
        cl.addWidget(self.stack, 1)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side_scroll = QScrollArea()  # em janelas baixas só o menu rola; o logotipo fica fixo no topo
        side_scroll.setObjectName("sideScroll")
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232)
        sbl = QVBoxLayout(sidebar)
        sbl.setContentsMargins(0, 0, 0, 0)
        sbl.setSpacing(0)
        sbl.addWidget(head)
        sbl.addWidget(side_scroll, 1)
        lay.addWidget(sidebar)
        lay.addWidget(content, 1)
        self.setCentralWidget(central)
        self._update_status()
        self.go(self.first_allowed)

    # Perfis: o que cada um enxerga no menu (a regra também é aplicada nos serviços sensíveis)
    ROLE_PAGES = {
        UserRole.ADMIN: None,
        UserRole.GERENTE: {"Painel", "Vendas (PDV)", "Produtos", "Estoque", "Compras", "Fornecedores", "Financeiro", "Tributário",
                           "Funcionários", "Relatórios", "Backup", "Empresa"},
        UserRole.OPERADOR: {"Vendas (PDV)", "Produtos", "Estoque", "Compras", "Fornecedores"},
    }

    # Títulos de grupo do menu (apenas visuais; não mudam destinos nem permissões)
    NAV_SECTIONS = {"Painel": "Operação", "Financeiro": "Gestão", "Backup": "Sistema"}

    def _apply_role(self) -> None:
        with self.ctx.db.session_scope() as s:
            u = s.get(User, self.ctx.current_user_id)
            role = u.role if u else UserRole.OPERADOR
            self.user_name = u.full_name if u else ""
        allowed = self.ROLE_PAGES[role]
        self.first_allowed = 0
        for i, (name, _) in enumerate(self.pages):
            ok = allowed is None or name in allowed
            self.group.button(i).setVisible(ok)
            if not ok and i == self.first_allowed:
                self.first_allowed = i + 1
        names = [n for n, _ in self.pages]
        starts = [names.index(n) for n in self.NAV_SECTIONS] + [len(names)]
        for k, start in enumerate(starts[:-1]):
            vis = any(allowed is None or n in allowed for n in names[start:starts[k + 1]])
            self._sections[names[start]].setVisible(vis)

    def _company_saved(self) -> None:
        self._update_status()

    def closeEvent(self, event) -> None:
        backup_service.run_auto_backup(self.ctx.db, paths.backups_dir(self.ctx.home))
        super().closeEvent(event)

    def go(self, index: int) -> None:
        if not self.group.button(index).isVisible() and self.isVisible():
            return
        name = self.pages[index][0]
        self.group.button(index).setChecked(True)
        target = self.pages[index][1]
        changed = self.stack.currentWidget() is not target
        self.stack.setCurrentWidget(target)
        target.refresh()
        section = ""
        for k, v in self.NAV_SECTIONS.items():
            if [n for n, _ in self.pages].index(k) <= index:
                section = v
        self.crumb.setText(f"{section}&nbsp;&nbsp;/&nbsp;&nbsp;<span style='color:#F1F5F9; font-weight:600'>{name}</span>")
        if changed and self.isVisible():
            motion.fade_in(target)
        self._move_indicator(animate=self.isVisible())

    def current_page_name(self) -> str:
        return self.pages[self.group.checkedId()][0] if self.group.checkedId() >= 0 else ""

    def _move_indicator(self, animate: bool = True) -> None:
        from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect
        btn = self.group.checkedButton()
        if btn is None or not btn.isVisible():
            self.nav_indicator.hide()
            return
        g = btn.geometry()
        dest = QRect(g.x() + 10, g.y() + 1, g.width() - 20, g.height() - 2)
        bar = self.nav_indicator.findChild(QFrame, "navIndicatorBar")
        bar.move(0, (dest.height() - bar.height()) // 2)
        self.nav_indicator.lower()
        self.nav_indicator.show()
        if self._nav_anim is not None:
            self._nav_anim.stop()
        if not animate or self.nav_indicator.geometry().isEmpty():
            self.nav_indicator.setGeometry(dest)
            return
        anim = QPropertyAnimation(self.nav_indicator, b"geometry", self)
        anim.setDuration(motion.NAV_MS)
        anim.setStartValue(self.nav_indicator.geometry())
        anim.setEndValue(dest)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._nav_anim = anim

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, lambda: self._move_indicator(animate=False))

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if hasattr(self, "nav_indicator"):
            QTimer.singleShot(0, lambda: self._move_indicator(animate=False))

    def _chip_clicked(self) -> None:
        emp = [n for n, _ in self.pages].index("Empresa")
        if self.group.button(emp).isVisible():
            self.go(emp)

    def _update_status(self) -> None:
        with self.ctx.db.session_scope() as s:
            c = company_service.get_company(s)
            name = (c.trade_name or c.legal_name) if c else "Empresa não cadastrada"
            has_company = c is not None
            cnpj = format_cnpj(c.cnpj) if c else ""
        if has_company:
            self.chip.setText(f"  {name}     {cnpj}")
            self.chip.setIcon(glyph("building", ACCENT, 15))
            self.chip.setProperty("warn", False)
            self.chip.setToolTip("Dados da empresa")
        else:
            self.chip.setText("  Cadastrar empresa")
            self.chip.setIcon(glyph("building", SUBTLE, 15))
            self.chip.setProperty("warn", False)
            self.chip.setToolTip("Abrir o cadastro da empresa")
        self.chip.style().unpolish(self.chip)
        self.chip.style().polish(self.chip)
        if license_service.LICENSING_ENABLED:
            with self.ctx.db.session_scope() as s:
                st = license_service.license_status(s)
            lic = "Licenciado para " + st.customer if st.ok else ("Avaliação — " + st.message if st.state == "avaliacao" else st.message)
        else:
            from .. import __version__
            lic = f"StockPilot {__version__}"
        self.statusBar().showMessage(f"{lic}   •   Banco de dados: {self.ctx.db.path}")

