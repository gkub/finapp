from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from finance_tracker.db.database import default_database_path
from finance_tracker.db.models import Account, Currency


def test_database_path_respects_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FINANCE_TRACKER_DB_PATH", str(tmp_path / "custom.db"))
    assert default_database_path() == tmp_path / "custom.db"


def test_database_path_macos_default(monkeypatch):
    monkeypatch.delenv("FINANCE_TRACKER_DB_PATH", raising=False)
    monkeypatch.setattr("finance_tracker.db.database.sys.platform", "darwin")
    assert default_database_path() == (
        Path.home() / "Library" / "Application Support" / "personal-finance-tracker" / "finance.db"
    )


def test_database_path_prefers_synced_git_repo(monkeypatch, tmp_path):
    monkeypatch.delenv("FINANCE_TRACKER_DB_PATH", raising=False)
    monkeypatch.delenv("FINANCE_TRACKER_SYNC", raising=False)
    monkeypatch.setenv("FINANCE_DATA_DIR", str(tmp_path))
    (tmp_path / ".git").mkdir()
    assert default_database_path() == tmp_path / "finance.db"


def test_schema_contains_core_tables(engine):
    names = set(inspect(engine).get_table_names())
    assert {"accounts", "debts", "schedules", "investment_holdings", "exchange_rates", "one_time_events", "deposits", "material_assets"} <= names
    event_columns = {item["name"] for item in inspect(engine).get_columns("one_time_events")}
    assert {"payment_debt_id", "applied", "account_id"} <= event_columns


def test_account_can_have_negative_overdraft_balance(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", current_balance=Decimal("-250.75"),
                      currency="CAD", overdraft_limit=Decimal("1000"), overdraft_interest_rate=Decimal("0.2199"))
    session.add(account)
    session.flush()
    session.expire(account)
    assert account.current_balance == Decimal("-250.7500")
    assert account.overdraft_limit == Decimal("1000.0000")
    assert account.overdraft_interest_rate == Decimal("0.2199000000")

