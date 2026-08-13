from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from finance_tracker.db.models import Base


def default_database_path() -> Path:
    override = os.getenv("FINANCE_TRACKER_DB_PATH")
    if override:
        return Path(override).expanduser()
    data_home = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "personal-finance-tracker" / "finance.db"


def build_engine(path: Path | None = None) -> Engine:
    database_path = path or default_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{database_path}", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = build_engine()
    return _engine


def create_schema(engine: Engine | None = None) -> None:
    target = engine or get_engine()
    Base.metadata.create_all(target)
    _add_missing_columns(target)


def _add_missing_columns(engine: Engine) -> None:
    statements = (
        ("recurring_expenses", "payment_debt_id", "INTEGER REFERENCES debts(id)"),
        ("one_time_events", "payment_debt_id", "INTEGER REFERENCES debts(id)"),
    )
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        for table, column, ddl in statements:
            if table not in tables:
                continue
            existing = {item["name"] for item in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

