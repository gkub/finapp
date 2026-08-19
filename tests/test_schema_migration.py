from sqlalchemy import create_engine, inspect, text

from finance_tracker.db.database import create_schema


def test_existing_database_receives_credit_and_funding_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("CREATE TABLE income_sources (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("CREATE TABLE debts (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE recurring_expenses (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE one_time_events (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO accounts (id, name) VALUES (1, 'Legacy account')"))
        connection.execute(text("INSERT INTO income_sources (id, name) VALUES (1, 'Legacy income')"))
        connection.execute(text("INSERT INTO recurring_expenses (id) VALUES (1)"))
        connection.execute(text("INSERT INTO one_time_events (id) VALUES (1)"))
    create_schema(engine)
    inspector = inspect(engine)
    assert "credit_limit" in {item["name"] for item in inspector.get_columns("debts")}
    recurring = {item["name"] for item in inspector.get_columns("recurring_expenses")}
    one_time = {item["name"] for item in inspector.get_columns("one_time_events")}
    accounts = {item["name"] for item in inspector.get_columns("accounts")}
    income = {item["name"] for item in inspector.get_columns("income_sources")}
    assert {"backup_account_id", "funding_strategy"} <= recurring
    assert {"backup_account_id", "funding_strategy"} <= one_time
    assert "purpose" in accounts
    assert "purpose" in income
    assert "purpose" in recurring
    assert "purpose" in one_time
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT purpose FROM accounts WHERE id = 1")) == "personal"
        assert connection.scalar(text("SELECT purpose FROM income_sources WHERE id = 1")) == "personal"
        assert connection.scalar(text("SELECT purpose FROM recurring_expenses WHERE id = 1")) == "personal"
        assert connection.scalar(text("SELECT purpose FROM one_time_events WHERE id = 1")) == "personal"
    assert "spending_entries" in inspector.get_table_names()
