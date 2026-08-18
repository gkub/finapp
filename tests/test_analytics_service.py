from datetime import date
from decimal import Decimal

from finance_tracker.db.models import Account, BalanceSnapshot, Currency, Debt, DebtSnapshot
from finance_tracker.services.analytics_service import progress_metrics


def test_progress_metrics_calculate_savings_and_debt_pace(session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    savings = Account(name="Savings", account_type="savings", currency="CAD", current_balance=Decimal("1600"))
    debt = Debt(name="Loan", debt_type="student_loan", currency="CAD", current_balance=Decimal("700"))
    session.add_all([savings, debt])
    session.flush()
    session.add_all([
        BalanceSnapshot(account_id=savings.id, balance=Decimal("1000"), currency="CAD", snapshot_date=date(2026, 1, 1)),
        BalanceSnapshot(account_id=savings.id, balance=Decimal("1600"), currency="CAD", snapshot_date=date(2026, 4, 1)),
        DebtSnapshot(debt_id=debt.id, balance=Decimal("1000"), snapshot_date=date(2026, 1, 1)),
        DebtSnapshot(debt_id=debt.id, balance=Decimal("700"), snapshot_date=date(2026, 4, 1)),
    ])
    session.flush()

    metrics = {item.key: item for item in progress_metrics(
        session, date(2026, 1, 1), date(2026, 4, 1), 6,
    )}

    assert metrics["savings"].change == Decimal("600.0000")
    assert metrics["savings"].monthly_pace == Decimal("202.9166666666666666666666667")
    assert metrics["savings"].projected_value == Decimal("2817.500000000000000000000000")
    assert metrics["debt"].change == Decimal("300.0000")
    assert metrics["debt"].projected_value == Decimal("91.2500000000000000000000002")


def test_net_worth_history_forward_fills_staggered_snapshot_dates(session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", currency="CAD", current_balance=Decimal("1500"))
    debt = Debt(name="Loan", debt_type="student_loan", currency="CAD", current_balance=Decimal("600"))
    session.add_all([account, debt])
    session.flush()
    session.add_all([
        BalanceSnapshot(account_id=account.id, balance=Decimal("1000"), currency="CAD", snapshot_date=date(2026, 1, 1)),
        BalanceSnapshot(account_id=account.id, balance=Decimal("1500"), currency="CAD", snapshot_date=date(2026, 4, 1)),
        DebtSnapshot(debt_id=debt.id, balance=Decimal("900"), snapshot_date=date(2026, 1, 5)),
        DebtSnapshot(debt_id=debt.id, balance=Decimal("600"), snapshot_date=date(2026, 4, 5)),
    ])
    session.flush()

    metric = next(item for item in progress_metrics(
        session, date(2026, 1, 1), date(2026, 4, 5), 3,
    ) if item.key == "net_worth")

    assert metric.observed_start == date(2026, 1, 5)
    assert metric.observed_end == date(2026, 4, 5)
    assert metric.start_value == Decimal("100.0000")
    assert metric.end_value == Decimal("900.0000")
    assert metric.change == Decimal("800.0000")


def test_partial_debt_history_is_labeled_and_does_not_fake_net_worth(session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    tracked = Debt(name="Tracked", debt_type="student_loan", currency="CAD", current_balance=Decimal("800"))
    untracked = Debt(name="Untracked", debt_type="other", currency="CAD", current_balance=Decimal("500"))
    session.add_all([tracked, untracked])
    session.flush()
    session.add_all([
        DebtSnapshot(debt_id=tracked.id, balance=Decimal("1000"), snapshot_date=date(2026, 1, 1)),
        DebtSnapshot(debt_id=tracked.id, balance=Decimal("800"), snapshot_date=date(2026, 4, 1)),
    ])
    session.flush()

    metrics = {item.key: item for item in progress_metrics(
        session, date(2026, 1, 1), date(2026, 4, 1), 3,
    )}

    assert metrics["debt"].available
    assert metrics["debt"].covered_entities == 1
    assert metrics["debt"].total_entities == 2
    assert not metrics["net_worth"].available
