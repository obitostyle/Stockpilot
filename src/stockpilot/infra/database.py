"""Acesso ao SQLite: PRAGMAs de segurança, transações explícitas e versão do esquema."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from .. import SCHEMA_VERSION
from ..domain.errors import DatabaseIncompatibleError
from ..models import Base, Setting

log = logging.getLogger("stockpilot.db")


def _configure_sqlite(engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _rec):
        # Desliga o controle implícito do driver para podermos usar BEGIN IMMEDIATE
        # (receita oficial do SQLAlchemy para pysqlite).
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")        # integridade referencial
        cur.execute("PRAGMA journal_mode=WAL")       # resiste melhor a quedas de energia
        cur.execute("PRAGMA synchronous=FULL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        # Toda transação adquire o lock de escrita no início: a verificação de
        # estoque e a gravação da movimentação acontecem de forma atômica.
        conn.exec_driver_sql("BEGIN IMMEDIATE")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{self.path}")
        _configure_sqlite(self.engine)
        self._factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Uma unidade de trabalho = uma transação. Erro => rollback completo."""
        session = self._factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def init_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.session_scope() as s:
            row = s.get(Setting, "schema_version")
            if row is None:
                s.add(Setting(key="schema_version", value=str(SCHEMA_VERSION)))
            elif int(row.value) > SCHEMA_VERSION:
                raise DatabaseIncompatibleError(
                    "Este banco de dados foi criado por uma versão mais nova do StockPilot. "
                    "Atualize o programa antes de abri-lo."
                )
            # Migrações futuras (row.value < SCHEMA_VERSION) entram aqui / Alembic.

    def integrity_check(self) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(text("PRAGMA integrity_check")).scalar() == "ok"

    def dispose(self) -> None:
        self.engine.dispose()
