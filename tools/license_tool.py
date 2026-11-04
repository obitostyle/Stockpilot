#!/usr/bin/env python3
"""Ferramenta DO FABRICANTE para emitir licenças do StockPilot. NÃO inclua este arquivo nem a chave privada no instalador.

  python tools/license_tool.py gen-keys [--out chave_privada.pem]      cria um par de chaves e grava a pública no programa
  python tools/license_tool.py issue --key chave_privada.pem --id SP-XXXX-XXXX-XXXX-XXXX --customer "Mercado X" [--edition Comercial]
  python tools/license_tool.py check --id SP-... --license "<chave>"   confere uma chave com a chave pública do programa
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
PUBFILE = ROOT / "src" / "stockpilot" / "licensing" / "public_key.py"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def cmd_gen(a) -> int:
    out = Path(a.out)
    if out.exists():
        print(f"Recusado: {out} já existe (não sobrescrevo chaves).", file=sys.stderr)
        return 1
    k = Ed25519PrivateKey.generate()
    out.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    pub = base64.b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    text = PUBFILE.read_text(encoding="utf-8")
    import re
    PUBFILE.write_text(re.sub(r'PUBLIC_KEY_B64 = ".*"', f'PUBLIC_KEY_B64 = "{pub}"', text), encoding="utf-8")
    print(f"Chave privada: {out}  (GUARDE EM LOCAL SEGURO; quem a tem emite licenças)\nChave pública gravada em {PUBFILE}\nRecompile o programa para valer.")
    return 0


def cmd_issue(a) -> int:
    k = serialization.load_pem_private_key(Path(a.key).read_bytes(), password=None)
    payload = json.dumps({"v": 1, "id": a.id.strip().upper(), "customer": a.customer, "edition": a.edition,
                          "issued": date.today().isoformat()}, ensure_ascii=False, separators=(",", ":")).encode()
    print(b64u(payload) + "." + b64u(k.sign(payload)))
    return 0


def cmd_check(a) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from stockpilot.licensing.service import verify_key
    st = verify_key(a.license, a.id.strip().upper())
    print(st.state, "-", st.message, st.customer)
    return 0 if st.ok else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gen-keys")
    g.add_argument("--out", default="chave_privada.pem")
    g.set_defaults(fn=cmd_gen)
    i = sub.add_parser("issue")
    i.add_argument("--key", required=True)
    i.add_argument("--id", required=True)
    i.add_argument("--customer", required=True)
    i.add_argument("--edition", default="Comercial")
    i.set_defaults(fn=cmd_issue)
    c = sub.add_parser("check")
    c.add_argument("--id", required=True)
    c.add_argument("--license", required=True)
    c.set_defaults(fn=cmd_check)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
