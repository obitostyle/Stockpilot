import base64
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from stockpilot.domain.errors import ValidationError
from stockpilot.licensing import service as lic
from stockpilot.licensing.public_key import PUBLIC_KEY_B64

ROOT = Path(__file__).resolve().parents[1]


def b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@pytest.fixture()
def keypair():
    k = Ed25519PrivateKey.generate()
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return k, pub


def issue(k, iid, customer="Cliente X", v=1):
    payload = json.dumps({"v": v, "id": iid, "customer": customer, "edition": "Comercial", "issued": "2026-11-01"}).encode()
    return b64u(payload) + "." + b64u(k.sign(payload))


def test_id_estavel_e_formatado(session):
    a = lic.installation_id(session)
    assert a == lic.installation_id(session)
    assert a.startswith("SP-") and len(a) == 22


def test_avaliacao_nao_bloqueia(session):
    st = lic.license_status(session)
    assert st.state == "avaliacao" and st.eval_days_left == 30
    late = lic.license_status(session, today=date.today() + timedelta(days=90))
    assert late.state == "avaliacao" and "continuam acessíveis" in late.message


def test_ativar_licenca_valida(session, keypair):
    k, pub = keypair
    iid = lic.installation_id(session)
    st = lic.activate(session, issue(k, iid), pub)
    assert st.ok and st.customer == "Cliente X"
    assert lic.license_status(session, pub).ok
    lic.deactivate(session)
    assert lic.license_status(session, pub).state == "avaliacao"


def test_chaves_invalidas(session, keypair):
    k, pub = keypair
    iid = lic.installation_id(session)
    with pytest.raises(ValidationError, match="outra instalação"):
        lic.activate(session, issue(k, "SP-AAAA-BBBB-CCCC-DDDD"), pub)
    outra = Ed25519PrivateKey.generate()
    with pytest.raises(ValidationError, match="assinatura"):
        lic.activate(session, issue(outra, iid), pub)
    key = issue(k, iid)
    forged = key[:10] + ("A" if key[10] != "A" else "B") + key[11:]
    with pytest.raises(ValidationError):
        lic.activate(session, forged, pub)
    with pytest.raises(ValidationError, match="Formato"):
        lic.activate(session, "lixo", pub)
    with pytest.raises(ValidationError, match="não suportada"):
        lic.activate(session, issue(k, iid, v=2), pub)


def test_ferramenta_do_fabricante_ponta_a_ponta(tmp_path, session):
    """Emite com a chave PRIVADA embarcada no projeto de desenvolvimento? Não: gera par novo numa cópia e confere."""
    pem = tmp_path / "k.pem"
    k = Ed25519PrivateKey.generate()
    pem.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "license_tool.py"), "issue", "--key", str(pem), "--id", "sp-1111-2222-3333-4444",
                          "--customer", "Loja"], capture_output=True, text=True, check=True).stdout.strip()
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    assert lic.verify_key(out, "SP-1111-2222-3333-4444", pub).ok


def test_chave_publica_embarcada_e_valida():
    assert len(base64.b64decode(PUBLIC_KEY_B64)) == 32
