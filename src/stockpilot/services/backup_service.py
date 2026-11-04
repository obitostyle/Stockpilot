"""Backup e restauração do banco SQLite.

* Cópia consistente via API de backup do SQLite (segura mesmo com o banco em uso/WAL).
* Cada backup recebe um arquivo .sha256; a verificação confere hash + integrity_check + versão do esquema.
* Restaurar SEMPRE cria antes uma cópia de segurança do banco atual.
* Backups automáticos giram (mantém os N mais recentes); backups manuais nunca são apagados pelo programa.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .. import SCHEMA_VERSION
from ..domain.errors import BusinessError, ValidationError
from ..infra.database import Database
from .settings_service import get_setting, set_setting

log = logging.getLogger("stockpilot.backup")
PREFIXES = ("manual", "auto", "seguranca")


@dataclass
class BackupInfo:
    path: Path
    kind: str
    created: datetime
    size: int
    verified: bool | None = None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sidecar(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".sha256")


def _copy_db(src_path: Path, dest: Path) -> None:
    src = sqlite3.connect(str(src_path))
    try:
        dst = sqlite3.connect(str(dest))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _check_file(path: Path) -> tuple[bool, str]:
    """integrity_check + versão do esquema. Retorna (ok, mensagem)."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False, "O arquivo está corrompido (falha na verificação de integridade)."
            try:
                row = con.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
            except sqlite3.Error:
                return False, "O arquivo não é um banco do StockPilot."
            if row is None:
                return False, "O arquivo não é um banco do StockPilot."
            if int(row[0]) > SCHEMA_VERSION:
                return False, "O backup foi criado por uma versão mais nova do programa. Atualize o StockPilot."
        finally:
            con.close()
    except sqlite3.Error as exc:
        return False, f"Não foi possível abrir o arquivo como banco de dados ({exc})."
    return True, "ok"


def create_backup(db: Database, backups_dir: Path, kind: str = "manual", dest: Path | None = None) -> BackupInfo:
    if kind not in PREFIXES:
        raise ValueError(kind)
    backups_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    out = dest or backups_dir / f"{kind}-{now:%Y%m%d-%H%M%S}.db"
    if out.exists():
        raise ValidationError("Já existe um arquivo com esse nome.")
    tmp = out.with_suffix(".tmp")
    try:
        _copy_db(db.path, tmp)
        ok, msg = _check_file(tmp)
        if not ok:
            raise BusinessError("O backup gerado não passou na verificação: " + msg)
        tmp.replace(out)
    finally:
        if tmp.exists():
            tmp.unlink()
    _sidecar(out).write_text(f"{_sha256(out)}  {out.name}\n", encoding="utf-8")
    log.info("Backup %s criado: %s", kind, out)
    return BackupInfo(out, kind, now, out.stat().st_size, True)


def verify_backup(path: Path) -> tuple[bool, str]:
    path = Path(path)
    if not path.exists():
        return False, "Arquivo não encontrado."
    side = _sidecar(path)
    if side.exists():
        expected = side.read_text(encoding="utf-8").split()[0]
        if _sha256(path) != expected:
            return False, "O arquivo foi alterado ou está danificado (a assinatura SHA-256 não confere)."
        note = "Assinatura SHA-256 conferida. "
    else:
        note = "Sem arquivo de assinatura (.sha256): só a integridade interna foi conferida. "
    ok, msg = _check_file(path)
    return (True, note + "Banco íntegro e compatível.") if ok else (False, msg)


def list_backups(backups_dir: Path) -> list[BackupInfo]:
    out = []
    for p in sorted(backups_dir.glob("*.db")) if backups_dir.exists() else []:
        kind = p.name.split("-")[0]
        out.append(BackupInfo(p, kind if kind in PREFIXES else "outro", datetime.fromtimestamp(p.stat().st_mtime), p.stat().st_size))
    return sorted(out, key=lambda b: b.created, reverse=True)


def rotate_auto(backups_dir: Path, keep: int = 14) -> list[Path]:
    autos = [b for b in list_backups(backups_dir) if b.kind == "auto"]
    removed = []
    for b in autos[keep:]:
        b.path.unlink(missing_ok=True)
        _sidecar(b.path).unlink(missing_ok=True)
        removed.append(b.path)
    return removed


def record_backup(session, when: datetime | None = None) -> None:
    set_setting(session, "last_backup_at", (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"))


def last_backup_at(session) -> datetime | None:
    v = get_setting(session, "last_backup_at")
    return datetime.strptime(v, "%Y-%m-%d %H:%M:%S") if v else None


def auto_backup_due(session, max_age_hours: int = 24, now: datetime | None = None) -> bool:
    if get_setting(session, "auto_backup").lower() in ("false", "0", "nao", "não"):
        return False
    last = last_backup_at(session)
    return last is None or (now or datetime.now()) - last >= timedelta(hours=max_age_hours)


def run_auto_backup(db: Database, backups_dir: Path, keep: int = 14) -> BackupInfo | None:
    """Faz o backup automático se estiver vencido. Nunca levanta erro para o usuário: falha vai para o log."""
    try:
        with db.session_scope() as s:
            if not auto_backup_due(s):
                return None
        info = create_backup(db, backups_dir, "auto")
        rotate_auto(backups_dir, keep)
        with db.session_scope() as s:
            record_backup(s, info.created)
        return info
    except Exception:
        log.exception("Falha no backup automático")
        return None


def restore_backup(db: Database, backup_path: Path, backups_dir: Path) -> Path:
    """Substitui o banco atual pelo backup. Cria antes uma cópia de segurança.

    O chamador deve fechar todo uso do banco e REINICIAR o programa em seguida.
    Retorna o caminho da cópia de segurança do banco que estava em uso.
    """
    backup_path = Path(backup_path)
    ok, msg = verify_backup(backup_path)
    if not ok:
        raise BusinessError("Backup recusado: " + msg)
    safety = create_backup(db, backups_dir, "seguranca")
    db.dispose()
    for suffix in ("-wal", "-shm"):
        Path(str(db.path) + suffix).unlink(missing_ok=True)
    tmp = db.path.with_suffix(".restore")
    _copy_db(backup_path, tmp)
    ok, msg = _check_file(tmp)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise BusinessError("A cópia restaurada falhou na verificação; o banco atual foi mantido. " + msg)
    tmp.replace(db.path)
    log.warning("Banco restaurado de %s (segurança em %s)", backup_path, safety.path)
    return safety.path
