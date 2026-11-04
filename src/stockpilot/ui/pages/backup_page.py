from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from ...config import paths
from ...domain.enums import UserRole
from ...models import User
from ...services import backup_service as bs
from ...services.settings_service import get_setting, set_setting
from ..common import SortItem, card, confirm, make_table, primary, run_action, title_block
from .base import Page


class BackupPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self.dir = paths.backups_dir(ctx.home)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(12)
        root.addWidget(title_block("Backup e restauração", "Cópias de segurança do banco de dados, verificadas por assinatura SHA-256"))
        c = card()
        cl = QVBoxLayout(c)
        self.last = QLabel("")
        self.last.setObjectName("sectionTitle")
        cl.addWidget(self.last)
        self.where = QLabel(f"Pasta dos backups: {self.dir}")
        self.where.setObjectName("pageSub")
        self.where.setWordWrap(True)
        cl.addWidget(self.where)
        bar = QHBoxLayout()
        self.b_now = primary(QPushButton("Fazer backup agora"))
        self.b_copy = QPushButton("Salvar uma cópia em outro local…")
        self.b_ver = QPushButton("Verificar backup selecionado")
        self.b_rest = QPushButton("Restaurar backup selecionado…")
        self.b_file = QPushButton("Restaurar de um arquivo…")
        for b in (self.b_now, self.b_copy, self.b_ver, self.b_rest, self.b_file):
            bar.addWidget(b)
        bar.addStretch()
        cl.addLayout(bar)
        self.auto = QCheckBox("Backup automático (ao abrir e ao fechar o programa, no máximo 1 por dia; mantém os 14 mais recentes)")
        cl.addWidget(self.auto)
        root.addWidget(c)
        self.table = make_table(["Arquivo", "Tipo", "Criado em", "Tamanho"], {1: 100, 2: 150, 3: 100}, stretch=(0,))
        self.table.empty_text = "Nenhum backup ainda — clique em Fazer backup agora"
        root.addWidget(self.table, 1)
        note = QLabel("Dica: copie periodicamente a pasta de backups para um pen drive ou nuvem. Um backup só no mesmo computador não protege contra "
                      "perda ou roubo do equipamento. Ao restaurar, o programa guarda antes uma cópia de segurança do banco atual e fecha — abra-o novamente em seguida.")
        note.setObjectName("hint")
        note.setWordWrap(True)
        root.addWidget(note)
        self.b_now.clicked.connect(self._now)
        self.b_copy.clicked.connect(self._copy)
        self.b_ver.clicked.connect(self._verify)
        self.b_rest.clicked.connect(lambda: self._restore(self._sel()))
        self.b_file.clicked.connect(self._restore_file)
        self.auto.toggled.connect(self._auto)
        self._loading = False

    def _is_admin(self) -> bool:
        with self.ctx.db.session_scope() as s:
            u = s.get(User, self.ctx.current_user_id)
            return bool(u and u.role == UserRole.ADMIN)

    def refresh(self) -> None:
        with self.ctx.db.session_scope() as s:
            last = bs.last_backup_at(s)
            auto_on = get_setting(s, "auto_backup").lower() not in ("false", "0")
        self.last.setText("Último backup: " + (f"{last:%d/%m/%Y às %H:%M}" if last else "NENHUM backup feito ainda — faça um agora."))
        self._loading = True
        self.auto.setChecked(auto_on)
        self._loading = False
        admin = self._is_admin()
        self.b_rest.setEnabled(admin)
        self.b_file.setEnabled(admin)
        items = bs.list_backups(self.dir)
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(items))
        for i, b in enumerate(items):
            vals = [(b.path.name, b.path.name), ({"manual": "Manual", "auto": "Automático", "seguranca": "Segurança (antes de restaurar)"}.get(b.kind, "Outro"), b.kind),
                    (f"{b.created:%d/%m/%Y %H:%M}", b.created), (f"{b.size / 1024 / 1024:.2f} MB", b.size)]
            for j, (txt, k) in enumerate(vals):
                t.setItem(i, j, SortItem(txt, k, j == 3))
            t.item(i, 0).setData(Qt.UserRole, str(b.path))
        t.setSortingEnabled(True)
        t.sortByColumn(2, Qt.DescendingOrder)

    def _sel(self):
        r = self.table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Selecione um backup", "Clique em um backup da lista primeiro.")
            return None
        return Path(self.table.item(r, 0).data(Qt.UserRole))

    def _now(self) -> None:
        def work():
            info = bs.create_backup(self.ctx.db, self.dir, "manual")
            with self.ctx.db.session_scope() as s:
                bs.record_backup(s, info.created)
            self._done = info
        if run_action(self, work):
            QMessageBox.information(self, "Backup concluído", f"Backup criado e verificado:\n{self._done.path}")
            self.refresh()

    def _copy(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar cópia do banco", f"stockpilot-copia-{datetime.now():%Y%m%d}.db", "Banco StockPilot (*.db)")
        if path:
            def work():
                info = bs.create_backup(self.ctx.db, self.dir, "manual", dest=Path(path))
                with self.ctx.db.session_scope() as s:
                    bs.record_backup(s, info.created)
            if run_action(self, work):
                QMessageBox.information(self, "Cópia salva", f"Arquivo salvo em:\n{path}")
                self.refresh()

    def _verify(self) -> None:
        p = self._sel()
        if p:
            ok, msg = bs.verify_backup(p)
            (QMessageBox.information if ok else QMessageBox.warning)(self, "Verificação do backup", msg)

    def _restore_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Escolher backup para restaurar", str(self.dir), "Banco StockPilot (*.db)")
        if path:
            self._restore(Path(path))

    def _restore(self, p) -> None:
        if p is None:
            return
        ok, msg = bs.verify_backup(p)
        if not ok:
            QMessageBox.warning(self, "Backup recusado", msg)
            return
        if not confirm(self, "Restaurar backup",
                       f"ATENÇÃO: os dados atuais serão SUBSTITUÍDOS pelo conteúdo de:\n{p.name}\n\n"
                       "Tudo que foi feito depois desse backup será perdido (uma cópia de segurança do estado atual é guardada antes).\n"
                       "O programa será fechado ao terminar. Deseja continuar?", "Restaurar e fechar"):
            return

        def work():
            self._safety = bs.restore_backup(self.ctx.db, p, self.dir)
        if run_action(self, work):
            QMessageBox.information(self, "Restauração concluída",
                                    f"Backup restaurado. O estado anterior foi guardado em:\n{self._safety}\n\nO programa será fechado; abra-o novamente.")
            QApplication.quit()

    def _auto(self, on: bool) -> None:
        if self._loading:
            return
        with self.ctx.db.session_scope() as s:
            set_setting(s, "auto_backup", "true" if on else "false")
