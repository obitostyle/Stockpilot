"""Chave PÚBLICA do fabricante (Ed25519) usada para conferir licenças. Pode ficar no programa: ela só VERIFICA, não emite.

Para trocar por uma chave sua: python tools/license_tool.py gen-keys  (atualiza este arquivo e gera a chave privada).
A chave PRIVADA nunca deve ser colocada no instalador nem enviada a clientes.
"""
PUBLIC_KEY_B64 = "pf2mV0yvGpszmdE5/BtUgujjbm9X2faW3GVCFV0pn6Y="
