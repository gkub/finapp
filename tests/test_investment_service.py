from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import Currency, InvestmentAccount, InvestmentHolding, SecurityPrice
from finance_tracker.services.investment_service import latest_price, upsert_price, value_account


def test_upsert_price_updates_same_symbol_and_date(session: Session):
    session.add(Currency(code="USD", name="US Dollar", symbol="US$")); session.flush()
    first = upsert_price(session, "AAPL", Decimal("300.00"), "USD", date(2026, 8, 12))
    session.flush()
    second = upsert_price(session, "AAPL", Decimal("300.69"), "USD", date(2026, 8, 12))
    session.flush()
    rows = session.scalars(select(SecurityPrice).where(SecurityPrice.symbol == "AAPL")).all()
    assert len(rows) == 1
    assert first.id == second.id
    assert latest_price(session, "AAPL").price == Decimal("300.6900")


def test_value_account_skips_usd_holding_without_fx(session: Session):
    session.add_all([
        Currency(code="CAD", name="Canadian Dollar", symbol="$"),
        Currency(code="USD", name="US Dollar", symbol="US$"),
    ]); session.flush()
    account = InvestmentAccount(name="TFSA", account_type="tfsa", cash_balance=Decimal("10"), cash_currency="CAD")
    session.add(account); session.flush()
    session.add(InvestmentHolding(
        investment_account_id=account.id, symbol="AAPL", name="Apple", asset_type="stock",
        quantity=Decimal("1"), quote_currency="USD",
    ))
    upsert_price(session, "AAPL", Decimal("300"), "USD", date(2026, 8, 12))
    session.flush()
    assert value_account(session, account) == Decimal("10.0000")
