import pytest

from stockpilot.domain.enums import UserRole
from stockpilot.domain.errors import PermissionDeniedError, ValidationError
from stockpilot.services import settings_service as st, user_service as us


def test_criar_usuario_e_autenticar(session, uid):
    u = us.create_user(session, uid, "Maria", "Maria Souza", UserRole.OPERADOR, "segredo1")
    assert u.username == "maria" and u.password_hash and "segredo1" not in u.password_hash
    assert us.authenticate(session, "maria", "segredo1")
    assert not us.authenticate(session, "maria", "errada")
    with pytest.raises(ValidationError, match="login"):
        us.create_user(session, uid, "maria", "Outra", UserRole.OPERADOR, "segredo1")
    with pytest.raises(ValidationError, match="6 caracteres"):
        us.create_user(session, uid, "joao", "João", UserRole.OPERADOR, "123")


def test_so_admin_gerencia(session, uid):
    op = us.create_user(session, uid, "op", "Op", UserRole.OPERADOR, "segredo1")
    with pytest.raises(PermissionDeniedError):
        us.create_user(session, op.id, "x", "X", UserRole.OPERADOR, "segredo1")
    with pytest.raises(PermissionDeniedError):
        us.set_login_required(session, op.id, True)


def test_login_exige_senha_do_admin_e_mantem_um_admin(session, uid):
    with pytest.raises(ValidationError, match="senha"):
        us.set_login_required(session, uid, True)
    us.update_user(session, uid, uid, new_password="admin123")
    us.set_login_required(session, uid, True)
    assert st.get_bool(session, "login_required")
    with pytest.raises(ValidationError, match="pelo menos um Administrador"):
        us.update_user(session, uid, uid, active=False)
    with pytest.raises(ValidationError, match="pelo menos um Administrador"):
        us.update_user(session, uid, uid, role=UserRole.GERENTE)
