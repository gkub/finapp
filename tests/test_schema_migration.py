from sqlalchemy import create_engine, inspect, text

from finance_tracker.db.database import create_schema


def test_existing_database_receives_credit_and_funding_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE debts (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE recurring_expenses (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE one_time_events (id INTEGER PRIMARY KEY)"))
    create_schema(engine)
    inspector = inspect(engine)
    assert "credit_limit" in {item["name"] for item in inspector.get_columns("debts")}
    recurring = {item["name"] for item in inspector.get_columns("recurring_expenses")}
    one_time = {item["name"] for item in inspector.get_columns("one_time_events")}
    assert {"backup_account_id", "funding_strategy"} <= recurring
    assert {"backup_account_id", "funding_strategy"} <= one_time
    assert "spending_entries" in inspector.get_table_names()
