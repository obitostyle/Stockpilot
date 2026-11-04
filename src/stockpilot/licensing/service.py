"""Licenciamento OFFLINE por pagamento único.

Modelo: o cliente informa o "ID da instalação"; o fabricante gera uma chave assinada (Ed25519) para esse ID.
O programa só confere a assinatura com a chave pública — não precisa de internet nem de servidor.

Decisões de comportamento (v1):
* sem licença válida = "Modo de avaliação": todas as funções continuam disponíveis e um aviso é exibido;
* NUNCA se bloqueia o acesso aos dados, relatórios, exportações ou backup, com ou sem licença;
* ENFORCE_AFTER_EVAL=False: o que acontece após o período de avaliação é uma DECISÃO COMERCIAL pendente.
Limitações: um usuário determinado que edite o código pode burlar qualquer verificação local. O objetivo é
a conformidade honesta do cliente, não proteção anticópia.
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.orm import Session

from ..domain.errors import ValidationError
from ..services.settings_service import get_setting, set_setting
from .public_key import PUBLIC_KEY_B64

EVAL_DAYS = 30
ENFORCE_AFTER_EVAL = False   # decisão comercial pendente: ver docstring


def _b64d(t: str) -> bytes:
    return base64.urlsafe_b64decode(t + "=" * (-len(t) % 4))


def format_installation_id(raw: str) -> str:
    h = hashlib.sha256(raw.encode()).hexdigest().upper()[:16]
    return "SP-" + "-".join(h[i:i + 4] for i in range(0, 16, 4))


def installation_id(session: Session) -> str:
    """ID estável desta instalação (guardado no banco, que fica em %LOCALAPPDATA% e sobrevive a atualizações)."""
    raw = get_setting(session, "installation_uuid")
    if not raw:
        raw = str(uuid.uuid4())
        set_setting(session, "installation_uuid", raw)
        set_setting(session, "first_run_date", date.today().isoformat())
    return format_installation_id(raw)


@dataclass
class LicenseStatus:
    state: str            # 'licenciada' | 'avaliacao' | 'invalida'
    message: str
    customer: str = ""
    edition: str = ""
    issued: str = ""
    eval_days_left: int | None = None

    @property
    def ok(self) -> bool:
        return self.state == "licenciada"


def verify_key(key: str, expected_id: str, public_key_b64: str = PUBLIC_KEY_B64) -> LicenseStatus:
    key = "".join((key or "").split())
    if "." not in key:
        return LicenseStatus("invalida", "Formato de chave inválido.")
    try:
        payload_b64, sig_b64 = key.split(".", 1)
        payload_raw, sig = _b64d(payload_b64), _b64d(sig_b64)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(sig, payload_raw)
        payload = json.loads(payload_raw)
    except (InvalidSignature, ValueError, KeyError, TypeError):
        return LicenseStatus("invalida", "Chave de licença inválida (assinatura não confere).")
    if payload.get("v") != 1:
        return LicenseStatus("invalida", "Versão de licença não suportada. Atualize o programa.")
    if payload.get("id") != expected_id:
        return LicenseStatus("invalida", f"Esta chave foi emitida para outra instalação ({payload.get('id')}).")
    return LicenseStatus("licenciada", "Licença válida.", payload.get("customer", ""), payload.get("edition", ""), payload.get("issued", ""))


def license_status(session: Session, public_key_b64: str = PUBLIC_KEY_B64, today: date | None = None) -> LicenseStatus:
    iid = installation_id(session)
    key = get_setting(session, "license_key")
    if key:
        st = verify_key(key, iid, public_key_b64)
        if st.ok:
            return st
        st.message += " O programa continua funcionando em modo de avaliação; reative a licença."
        return st
    first = date.fromisoformat(get_setting(session, "first_run_date") or date.today().isoformat())
    left = EVAL_DAYS - ((today or date.today()) - first).days
    if left >= 0:
        return LicenseStatus("avaliacao", f"Modo de avaliação: {left} dia(s) restante(s) do período inicial. Todas as funções estão liberadas.", eval_days_left=left)
    return LicenseStatus("avaliacao", "Período de avaliação encerrado. Informe sua chave de licença. Seus dados continuam acessíveis.", eval_days_left=0)


def activate(session: Session, key: str, public_key_b64: str = PUBLIC_KEY_B64) -> LicenseStatus:
    st = verify_key(key, installation_id(session), public_key_b64)
    if not st.ok:
        raise ValidationError(st.message)
    set_setting(session, "license_key", "".join(key.split()))
    set_setting(session, "license_activated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    return st


def deactivate(session: Session) -> None:
    set_setting(session, "license_key", "")
