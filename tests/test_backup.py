from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from stockpilot.app_context import bootstrap
from stockpilot.config import paths
from stockpilot.domain.errors import BusinessError
from stockpilot.services import backup_service as bs, product_service
from tests.conftest import make_product


def test_backup_verificar_e_restaurar(ctx, tmp_path):
    bdir = paths.backups_dir(ctx.home)
    with ctx.db.session_scope() as s:
        make_product(s, ctx.current_user_id, qty="5", name="Antes")
    info = bs.create_backup(ctx.db, bdir)
    assert info.path.exists() and bs._sidecar(info.path).exists()
    ok, msg = bs.verify_backup(info.path)
    assert ok, msg
    # altera dados depois do backup
    with ctx.db.session_scope() as s:
        make_product(s, ctx.current_user_id, qty="1", name="Depois")
    with ctx.db.session_scope() as s:
        assert len(product_service.search_products(s)) == 2
    safety = bs.restore_backup(ctx.db, info.path, bdir)
    assert safety.exists() and safety.name.startswith("seguranca-")
    c2 = bootstrap(ctx.home)
    try:
        with c2.db.session_scope() as s:
            names = [p.name for p in product_service.search_products(s)]
        assert names == ["Antes"]
    finally:
        c2.close()


def test_backup_adulterado_e_recusado(ctx):
    bdir = paths.backups_dir(ctx.home)
    info = bs.create_backup(ctx.db, bdir)
    with open(info.path, "r+b") as fh:
        fh.seek(2000)
        fh.write(b"\x00\x01\x02garbage")
    ok, msg = bs.verify_backup(info.path)
    assert not ok and "SHA-256" in msg
    with pytest.raises(BusinessError, match="recusado"):
        bs.restore_backup(ctx.db, info.path, bdir)


def test_arquivo_que_nao_e_banco(ctx, tmp_path):
    f = tmp_path / "x.db"
    f.write_text("não sou um banco")
    ok, _ = bs.verify_backup(f)
    assert not ok


def test_rotacao_so_apaga_automaticos(ctx):
    bdir = paths.backups_dir(ctx.home)
    manual = bs.create_backup(ctx.db, bdir, "manual")
    for i in range(4):
        bs.create_backup(ctx.db, bdir, "auto", dest=bdir / f"auto-20260101-00000{i}.db")
    removed = bs.rotate_auto(bdir, keep=2)
    assert len(removed) == 2
    assert manual.path.exists()
    assert len([b for b in bs.list_backups(bdir) if b.kind == "auto"]) == 2


def test_backup_automatico_vencimento(ctx):
    bdir = paths.backups_dir(ctx.home)
    with ctx.db.session_scope() as s:
        assert bs.auto_backup_due(s)
    assert bs.run_auto_backup(ctx.db, bdir) is not None
    assert bs.run_auto_backup(ctx.db, bdir) is None      # ainda não venceu
    with ctx.db.session_scope() as s:
        assert not bs.auto_backup_due(s)
        assert bs.auto_backup_due(s, now=datetime.now() + timedelta(hours=25))
        from stockpilot.services.settings_service import set_setting
        set_setting(s, "auto_backup", "false")
        assert not bs.auto_backup_due(s, now=datetime.now() + timedelta(days=9))
