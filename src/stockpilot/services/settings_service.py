from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import Setting

DEFAULTS = {
    "allow_negative_stock": "false",
    "login_required": "false",
    "max_discount_percent": "10",
    "auto_backup": "true",
    "license_key": "",
    "installation_uuid": "",
    "first_run_date": "",
    "last_backup_at": "",
    "rat_percent": "",
    "terceiros_percent": "",
}


def get_setting(session: Session, key: str) -> str:
    row = session.get(Setting, key)
    return row.value if row else DEFAULTS.get(key, "")


def set_setting(session: Session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row:
        row.value = value
    else:
        session.add(Setting(key=key, value=value))


def get_bool(session: Session, key: str) -> bool:
    return get_setting(session, key).strip().lower() in {"1", "true", "sim", "yes"}
