from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finance_tracker.db.models import (
    Account, BalanceSnapshot, Currency, IncomeSource, RecurringExpense,
    Schedule, ScheduleType, SpendingEntry,
)
from finance_tracker.services.spending_service import summarize_spending


def test_spending_summary_reconciles_unknown_outflow(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", current_balance=Decimal("2100"), currency="CAD")
    session.add(account)
    session.flush()
    session.add_all([
        BalanceSnapshot(account_id=account.id, balance=Decimal("1000"), currency="CAD", snapshot_date=date(2026, 8, 1)),
        BalanceSnapshot(account_id=account.id, balance=Decimal("2100"), currency="CAD", snapshot_date=date(2026, 8, 15)),
    ])
    payday = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 5))
    bill_day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 10))
    session.add_all([payday, bill_day])
    session.flush()
    session.add(IncomeSource(name="Pay", amount=Decimal("2000"), currency="CAD", schedule_id=payday.id, destination_account_id=account.id))
    session.add(RecurringExpense(name="Rent", amount=Decimal("500"), currency="CAD", schedule_id=bill_day.id, payment_account_id=account.id))
    session.add(SpendingEntry(entry_date=date(2026, 8, 12), amount=Decimal("100"), currency="CAD", entry_type="category"))
    session.flush()

    result = summarize_spending(session, date(2026, 8, 1), date(2026, 8, 15))

    assert result.balance_change == Decimal("1100.0000")
    assert result.expected_cash_change == Decimal("1500.0000")
    assert result.known_spending == Decimal("500.0000")
    assert result.estimated_general_spending == Decimal("400.0000")
    assert result.allocated_general_spending == Decimal("100.0000")
    assert result.unallocated_general_spending == Decimal("300.0000")
    assert result.total_spending == Decimal("900.0000")


def test_spending_without_two_snapshots_uses_optional_checkins(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    session.add(SpendingEntry(entry_date=date(2026, 8, 12), amount=Decimal("75"), currency="CAD"))
    session.flush()
    result = summarize_spending(session, date(2026, 8, 1), date(2026, 8, 15))
    assert not result.has_balance_observation
    assert result.estimated_general_spending is None
    assert result.total_spending == Decimal("75.0000")
