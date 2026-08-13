import pytest
from sqlalchemy.orm import Session

from finance_tracker.db.database import build_engine, create_schema


@pytest.fixture
def engine(tmp_path):
    value = build_engine(tmp_path / "test.db")
    create_schema(value)
    yield value
    value.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as value:
        yield value
        value.rollback()
