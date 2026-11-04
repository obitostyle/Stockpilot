from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import UserRole
from ..domain.errors import NotFoundError, ValidationError
from ..infra.security import hash_password, verify_password
from ..models import User


def ensure_default_user(session: Session) -> User:
    """Cria o usuário local padrão (sem senha) enquanto o login não for habilitado.

    Mesmo sem login, toda operação sensível fica atribuída a um usuário identificado.
    """
    user = session.scalar(select(User).where(User.username == "admin"))
    if user is None:
        user = User(username="admin", full_name="Administrador", role=UserRole.ADMIN)
        session.add(user)
        session.flush()
    return user


def set_password(session: Session, user_id: int, password: str) -> None:
    if len(password) < 6:
        raise ValidationError("A senha deve ter pelo menos 6 caracteres.")
    user = session.get(User, user_id)
    if not user:
        raise NotFoundError("Usuário não encontrado.")
    user.password_hash = hash_password(password)


def authenticate(session: Session, username: str, password: str) -> User | None:
    user = session.scalar(select(User).where(User.username == username, User.active.is_(True)))
    return user if user and verify_password(password, user.password_hash) else None


# ------------------------------------------------------------------ gestão de usuários e login
def _actor(session: Session, actor_id: int | None, *roles: UserRole) -> User:
    from ..domain.errors import PermissionDeniedError
    u = session.get(User, actor_id) if actor_id else None
    if u is None or not u.active or u.role not in roles:
        raise PermissionDeniedError("Apenas o Administrador pode gerenciar usuários e configurações de segurança.")
    return u


def list_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.full_name)))


def create_user(session: Session, actor_id: int | None, username: str, full_name: str, role: UserRole, password: str) -> User:
    _actor(session, actor_id, UserRole.ADMIN)
    username = (username or "").strip().lower()
    if not username or not (full_name or "").strip():
        raise ValidationError("Informe o login e o nome do usuário.")
    if " " in username:
        raise ValidationError("O login não pode ter espaços.")
    if session.scalar(select(User.id).where(User.username == username)):
        raise ValidationError("Já existe um usuário com esse login.")
    u = User(username=username, full_name=full_name.strip(), role=role)
    session.add(u)
    session.flush()
    set_password(session, u.id, password)
    return u


def _active_admins(session: Session, exclude_id: int | None = None) -> int:
    return len([u for u in list_users(session) if u.active and u.role == UserRole.ADMIN and u.id != exclude_id])


def update_user(session: Session, actor_id: int | None, user_id: int, *, role: UserRole | None = None,
                active: bool | None = None, new_password: str | None = None) -> User:
    _actor(session, actor_id, UserRole.ADMIN)
    u = session.get(User, user_id)
    if u is None:
        raise NotFoundError("Usuário não encontrado.")
    losing_admin = (role is not None and role != UserRole.ADMIN and u.role == UserRole.ADMIN) or (active is False and u.role == UserRole.ADMIN)
    if losing_admin and _active_admins(session, exclude_id=u.id) == 0:
        raise ValidationError("É preciso manter pelo menos um Administrador ativo.")
    if role is not None:
        u.role = role
    if active is not None:
        u.active = active
    if new_password:
        set_password(session, u.id, new_password)
    session.flush()
    return u


def set_login_required(session: Session, actor_id: int | None, enabled: bool) -> None:
    from .settings_service import set_setting
    _actor(session, actor_id, UserRole.ADMIN)
    if enabled:
        admins = [u for u in list_users(session) if u.active and u.role == UserRole.ADMIN]
        if not admins or any(not a.password_hash for a in admins):
            raise ValidationError("Antes de exigir login, defina uma senha para todos os administradores ativos.")
    set_setting(session, "login_required", "true" if enabled else "false")
