from decimal import Decimal

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, Currency


def test_schema_contains_core_tables(engine):
    names = set(inspect(engine).get_table_names())
    assert {"accounts", "debts", "schedules", "investment_holdings", "exchange_rates"} <= names


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

