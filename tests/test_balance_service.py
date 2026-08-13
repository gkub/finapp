from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, BalanceSnapshot, Currency, Debt, InvestmentAccount, InvestmentHolding, SecurityPrice
from finance_tracker.services.balance_service import (
    current_balance_sheet, estimated_overdraft_interest, overdraft_headroom, update_account_balance,
)


def test_balance_sheet_keeps_cash_investments_and_debt_distinct(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    session.add(Account(name="Cash", account_type="checking", current_balance=Decimal("10000"), currency="CAD"))
    tfsa = InvestmentAccount(name="TFSA", account_type="tfsa", cash_balance=Decimal("0"), cash_currency="CAD")
    session.add(tfsa); session.flush()
    session.add(InvestmentHolding(investment_account_id=tfsa.id, symbol="XEQT", name="XEQT", asset_type="etf",
                                  quantity=Decimal("100"), quote_currency="CAD"))
    session.add(SecurityPrice(symbol="XEQT", price=Decimal("200"), currency="CAD", price_date=date(2026, 8, 1)))
    session.add(Debt(name="Student Loan", debt_type="student_loan", current_balance=Decimal("70000"), currency="CAD"))
    session.flush()
    result = current_balance_sheet(session)
    assert result.operating_cash == Decimal("10000")
    assert result.investments == Decimal("20000.00000000000000")
    assert result.net_worth == Decimal("-40000.00000000000000")


def test_negative_balance_snapshot_and_overdraft_headroom(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    account = Account(name="Chequing", account_type="checking", current_balance=Decimal("100"), currency="CAD",
                      overdraft_limit=Decimal("1000"), overdraft_interest_rate=Decimal("0.20"))
    session.add(account); session.flush()
    update_account_balance(session, account, Decimal("-250"), date(2026, 8, 12)); session.flush()
    assert session.scalar(select(BalanceSnapshot)).balance == Decimal("-250.0000")
    assert overdraft_headroom(account) == Decimal("750.0000")
    assert estimated_overdraft_interest(account, 30).quantize(Decimal("0.01")) == Decimal("4.11")
