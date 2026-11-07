from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ...domain.enums import UserRole
from ...domain.errors import PermissionDeniedError, ValidationError
from ...domain.formatting import parse_decimal_br
from ...models import User
from ...services import settings_service as st, user_service as us
from ...licensing import service as lic
from ..common import SortItem, make_table, primary, run_action, title_block
from ..widgets import form_dialog
from .base import Page

ROLE_HELP = {UserRole.ADMIN: "Administrador — acesso total", UserRole.GERENTE: "Gerente — tudo, exceto usuários, segurança e restauração de backup",
             UserRole.OPERADOR: "Operador — vendas, produtos, estoque, compras e fornecedores"}


class GeneralTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.neg = QCheckBox("Permitir estoque negativo (não recomendado: esconde erros de contagem)")
        self.disc = QLineEdit()
        self.disc.setPlaceholderText("10")
        self.rat = QLineEdit()
        self.terc = QLineEdit()
        for lab, w in (("", self.neg), ("Desconto máximo sem autorização do gerente (%)", self.disc),
                       ("Folha — alíquota RAT/FAP da empresa (%) — opcional", self.rat),
                       ("Folha — alíquota de terceiros/Sistema S (%) — opcional", self.terc)):
            if lab:
                l = QLabel(lab)
                l.setObjectName("kpiLabel")
                lay.addWidget(l)
            lay.addWidget(w)
        hint = QLabel("RAT/FAP e terceiros só são necessários para empresas fora do Simples Nacional (Anexos I, II, III e V). "
                      "Pergunte ao seu contador. Sem esses valores, o custo total do funcionário aparece como 'não calculado'.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        b = primary(QPushButton("Salvar configurações"))
        lay.addWidget(b, 0, Qt.AlignLeft)
        lay.addStretch()
        b.clicked.connect(self.save)
        for w in self.findChildren(QLineEdit):  # campos curtos para valores curtos
            w.setMaximumWidth(360)
        hint.setMaximumWidth(760)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            self.neg.setChecked(st.get_bool(s, "allow_negative_stock"))
            self.disc.setText(st.get_setting(s, "max_discount_percent"))
            self.rat.setText(st.get_setting(s, "rat_percent").replace(".", ","))
            self.terc.setText(st.get_setting(s, "terceiros_percent").replace(".", ","))

    def save(self) -> None:
        def work():
            def num(e, name, lo=0, hi=100):
                t = e.text().strip()
                if not t:
                    return ""
                try:
                    v = parse_decimal_br(t)
                except ValueError:
                    raise ValidationError(f"{name}: valor inválido.")
                if not lo <= v <= hi:
                    raise ValidationError(f"{name}: informe um valor entre {lo} e {hi}.")
                return str(v)
            d, r, t = num(self.disc, "Desconto máximo") or "10", num(self.rat, "RAT/FAP", 0, 20), num(self.terc, "Terceiros", 0, 20)
            with self.ctx.db.session_scope() as s:
                u = s.get(User, self.ctx.current_user_id)
                if not u or u.role != UserRole.ADMIN:
                    raise PermissionDeniedError("Apenas o Administrador altera as configurações.")
                st.set_setting(s, "allow_negative_stock", "true" if self.neg.isChecked() else "false")
                st.set_setting(s, "max_discount_percent", d)
                st.set_setting(s, "rat_percent", r)
                st.set_setting(s, "terceiros_percent", t)
        if run_action(self, work):
            QMessageBox.information(self, "Salvo", "Configurações salvas.")


class UsersTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.login = QCheckBox("Exigir login (usuário e senha) ao abrir o programa")
        lay.addWidget(self.login)
        bar = QHBoxLayout()
        self.b_new, self.b_pwd, self.b_role, self.b_act = primary(QPushButton("＋ Novo usuário")), QPushButton("Trocar senha…"), QPushButton("Mudar perfil…"), QPushButton("Ativar / desativar")
        bar.addStretch()
        for b in (self.b_act, self.b_role, self.b_pwd, self.b_new):
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = make_table(["Login", "Nome", "Perfil", "Situação", "Senha"], {0: 120, 2: 330, 3: 80, 4: 80}, stretch=(1,))
        lay.addWidget(self.table, 1)
        h = QLabel("Senhas são guardadas com hash scrypt (nunca em texto). Se o login estiver desligado, o programa abre direto como Administrador. "
                   "Se esquecer a única senha de administrador, restaure um backup anterior à ativação do login ou procure o suporte.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)
        self._loading = False
        self.login.toggled.connect(self._toggle_login)
        self.b_new.clicked.connect(self._new)
        self.b_pwd.clicked.connect(self._pwd)
        self.b_role.clicked.connect(self._role)
        self.b_act.clicked.connect(self._active)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            self._loading = True
            self.login.setChecked(st.get_bool(s, "login_required"))
            self._loading = False
            rows = [(u.id, u.username, u.full_name, ROLE_HELP[u.role], "Ativo" if u.active else "Inativo", "definida" if u.password_hash else "SEM SENHA") for u in us.list_users(s)]
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, v in enumerate(row[1:]):
                t.setItem(i, j, SortItem(v))
            t.item(i, 0).setData(Qt.UserRole, row[0])
        t.setSortingEnabled(True)

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione um usuário", "Clique em um usuário da lista primeiro.")
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _toggle_login(self, on: bool) -> None:
        if self._loading:
            return

        def work():
            with self.ctx.db.session_scope() as s:
                us.set_login_required(s, self.ctx.current_user_id, on)
        if not run_action(self, work):
            self._loading = True
            self.login.setChecked(not on)
            self._loading = False
        else:
            QMessageBox.information(self, "Login " + ("ativado" if on else "desativado"), "A mudança vale a partir da próxima vez que o programa for aberto.")

    def _new(self) -> None:
        login, name, pwd, role = QLineEdit(), QLineEdit(), QLineEdit(), QComboBox()
        pwd.setEchoMode(QLineEdit.Password)
        for r, t in ROLE_HELP.items():
            role.addItem(t, r.value)
        role.setCurrentIndex(2)

        def ok():
            with self.ctx.db.session_scope() as s:
                us.create_user(s, self.ctx.current_user_id, login.text(), name.text(), UserRole(role.currentData()), pwd.text())
        if form_dialog(self, "Novo usuário", [("Login *", login), ("Nome completo *", name), ("Perfil", role), ("Senha * (mín. 6)", pwd)], ok, min_width=520):
            self.refresh()

    def _pwd(self) -> None:
        uid = self._sel()
        if uid is None:
            return
        pwd = QLineEdit()
        pwd.setEchoMode(QLineEdit.Password)

        def ok():
            with self.ctx.db.session_scope() as s:
                us.update_user(s, self.ctx.current_user_id, uid, new_password=pwd.text())
        if form_dialog(self, "Trocar senha", [("Nova senha (mín. 6)", pwd)], ok):
            self.refresh()

    def _role(self) -> None:
        uid = self._sel()
        if uid is None:
            return
        role = QComboBox()
        for r, t in ROLE_HELP.items():
            role.addItem(t, r.value)

        def ok():
            with self.ctx.db.session_scope() as s:
                us.update_user(s, self.ctx.current_user_id, uid, role=UserRole(role.currentData()))
        if form_dialog(self, "Mudar perfil", [("Perfil", role)], ok, min_width=520):
            self.refresh()

    def _active(self) -> None:
        uid = self._sel()
        if uid is None:
            return

        def work():
            with self.ctx.db.session_scope() as s:
                u = s.get(User, uid)
                us.update_user(s, self.ctx.current_user_id, uid, active=not u.active)
        if run_action(self, work):
            self.refresh()


class LicenseTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        lay = QVBoxLayout(self)
        self.state = QLabel("")
        self.state.setObjectName("sectionTitle")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        lay.addWidget(self.detail)
        l = QLabel("ID desta instalação (informe ao fornecedor para receber a chave):")
        l.setObjectName("kpiLabel")
        lay.addWidget(l)
        row = QHBoxLayout()
        self.iid = QLineEdit()
        self.iid.setReadOnly(True)
        b_copy = QPushButton("Copiar")
        row.addWidget(self.iid, 1)
        row.addWidget(b_copy)
        lay.addLayout(row)
        l2 = QLabel("Chave de licença:")
        l2.setObjectName("kpiLabel")
        lay.addWidget(l2)
        from PySide6.QtWidgets import QPlainTextEdit
        self.key = QPlainTextEdit()
        self.key.setFixedHeight(90)
        self.key.setPlaceholderText("Cole aqui a chave recebida")
        lay.addWidget(self.key)
        bar = QHBoxLayout()
        self.b_act = primary(QPushButton("Ativar licença"))
        self.b_off = QPushButton("Remover licença deste computador")
        bar.addWidget(self.b_act)
        bar.addWidget(self.b_off)
        bar.addStretch()
        lay.addLayout(bar)
        h = QLabel("Licença de pagamento único, validada neste computador sem internet. Ao reinstalar o Windows ou trocar de computador, "
                   "mantenha a pasta de dados (ou restaure um backup) para conservar o ID; se o ID mudar, peça uma nova chave. "
                   "Seus dados nunca são bloqueados, com ou sem licença.")
        h.setObjectName("hint")
        h.setWordWrap(True)
        lay.addWidget(h)
        lay.addStretch()
        b_copy.clicked.connect(lambda: __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.clipboard().setText(self.iid.text()))
        self.b_act.clicked.connect(self._activate)
        self.b_off.clicked.connect(self._remove)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            self.iid.setText(lic.installation_id(s))
            st = lic.license_status(s)
        if st.ok:
            self.state.setText("✔ Licenciado")
            self.detail.setText(f"Cliente: {st.customer}   •   Edição: {st.edition}   •   Emitida em: {st.issued}")
        else:
            self.state.setText("Modo de avaliação" if st.state == "avaliacao" else "Licença inválida")
            self.detail.setText(st.message)

    def _activate(self) -> None:
        def work():
            with self.ctx.db.session_scope() as s:
                lic.activate(s, self.key.toPlainText())
        if run_action(self, work):
            self.key.clear()
            QMessageBox.information(self, "Licença ativada", "Obrigado! Licença ativada com sucesso.")
            self.refresh()

    def _remove(self) -> None:
        from ..common import confirm
        if confirm(self, "Remover licença", "O programa volta ao modo de avaliação neste computador. Guarde sua chave para reativar. Continuar?", "Remover"):
            with self.ctx.db.session_scope() as s:
                lic.deactivate(s)
            self.refresh()


class SettingsPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(10)
        root.addWidget(title_block("Configurações", "Regras de venda, folha e usuários — somente Administrador"))
        self.tabs = QTabWidget()
        self.parts = [("Geral", GeneralTab(ctx)), ("Usuários e segurança", UsersTab(ctx)), ("Licença", LicenseTab(ctx))]
        for n, w in self.parts:
            if n == "Licença" and not lic.LICENSING_ENABLED:
                continue  # produto vendido sem ativação por licença
            self.tabs.addTab(w, n)
        root.addWidget(self.tabs, 1)
        self.tabs.currentChanged.connect(lambda *_: self.refresh())

    def refresh(self) -> None:
        self.parts[self.tabs.currentIndex()][1].refresh()
