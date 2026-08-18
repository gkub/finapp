from datetime import date
from decimal import Decimal

from finance_tracker.db.models import Account, BalanceSnapshot, Currency, Debt, DebtSnapshot, OneTimeEvent
from finance_tracker.services.analytics_service import progress_metrics, scheduled_metrics


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
    assert metrics["debt"].label == "Total debt"
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


def test_one_day_balance_change_is_not_annualized(session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", currency="CAD", current_balance=Decimal("1000"))
    session.add(account)
    session.flush()
    session.add_all([
        BalanceSnapshot(account_id=account.id, balance=Decimal("0"), currency="CAD", snapshot_date=date(2026, 8, 13)),
        BalanceSnapshot(account_id=account.id, balance=Decimal("1000"), currency="CAD", snapshot_date=date(2026, 8, 14)),
    ])
    session.flush()

    metric = next(item for item in progress_metrics(
        session, date(2026, 7, 15), date(2026, 8, 14), 24,
    ) if item.key == "cash")

    assert not metric.available
    assert metric.monthly_pace is None
    assert metric.projected_value is None


def test_scheduled_forecast_uses_events_instead_of_snapshot_pace(session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", currency="CAD", current_balance=Decimal("1000"))
    session.add(account)
    session.flush()
    session.add(OneTimeEvent(
        name="Refund", event_date=date(2026, 9, 1), amount=Decimal("500"),
        currency="CAD", event_type="income", account_id=account.id,
    ))
    session.flush()

    forecast = scheduled_metrics(session, date(2026, 8, 1), 3)["cash"]

    assert forecast.current_value == Decimal("1000.0000")
    assert forecast.future_value == Decimal("1500.0000")
    assert forecast.change == Decimal("500.0000")


def test_historical_metrics_keep_partial_debt_history_out_of_totals(session):
    from finance_tracker.services.analytics_service import historical_metrics

    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    tracked_cash = Account(name="Tracked cash", account_type="checking", currency="CAD",
                           current_balance=Decimal("1200"))
    untracked_cash = Account(name="Untracked cash", account_type="checking", currency="CAD",
                             current_balance=Decimal("500"))
    tracked_debt = Debt(name="Tracked debt", debt_type="credit_card", currency="CAD",
                        current_balance=Decimal("800"))
    untracked_debt = Debt(name="Untracked debt", debt_type="other", currency="CAD",
                          current_balance=Decimal("500"))
    session.add_all([tracked_cash, untracked_cash, tracked_debt, untracked_debt])
    session.flush()
    session.add_all([
        BalanceSnapshot(account_id=tracked_cash.id, balance=Decimal("1000"), currency="CAD",
                        snapshot_date=date(2026, 8, 13)),
        BalanceSnapshot(account_id=tracked_cash.id, balance=Decimal("1200"), currency="CAD",
                        snapshot_date=date(2026, 8, 14)),
        DebtSnapshot(debt_id=tracked_debt.id, balance=Decimal("1000"), snapshot_date=date(2026, 8, 13)),
        DebtSnapshot(debt_id=tracked_debt.id, balance=Decimal("800"), snapshot_date=date(2026, 8, 14)),
    ])
    session.flush()

    metrics = historical_metrics(session, date(2026, 7, 15), date(2026, 8, 14))
    cash = next(item for item in metrics if item.key == "cash")
    debt_total = next(item for item in metrics if item.key == "debt_total")
    tracked = next(item for item in metrics if item.key == f"debt:{tracked_debt.id}")
    untracked = next(item for item in metrics if item.key == f"debt:{untracked_debt.id}")
    net_worth = next(item for item in metrics if item.key == "net_worth")

    assert cash.start_value is None
    assert cash.coverage == "Incomplete: 1/2 tracked"
    assert debt_total.start_value is None
    assert debt_total.coverage == "Incomplete: 1/2 tracked"
    assert tracked.balance_change == Decimal("-200.0000")
    assert tracked.improvement == Decimal("200.0000")
    assert tracked.monthly_pace is None
    assert untracked.start_value is None
    assert untracked.quality == "No history"
    assert net_worth.start_value is None


def test_forecast_interval_reconciles_payments_charges_and_boundaries(session):
    from finance_tracker.services.analytics_service import forecast_interval

    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", currency="CAD",
                      current_balance=Decimal("1000"))
    debt = Debt(name="Card", debt_type="credit_card", currency="CAD",
                current_balance=Decimal("1000"), credit_limit=Decimal("5000"))
    session.add_all([account, debt])
    session.flush()
    session.add_all([
        OneTimeEvent(name="Before-window payment", event_date=date(2026, 8, 10), amount=Decimal("100"),
                     currency="CAD", event_type="debt_payment", account_id=account.id,
                     payment_debt_id=debt.id),
        OneTimeEvent(name="New purchase", event_date=date(2026, 8, 20), amount=Decimal("150"),
                     currency="CAD", event_type="expense", payment_debt_id=debt.id),
        OneTimeEvent(name="Window payment", event_date=date(2026, 8, 25), amount=Decimal("300"),
                     currency="CAD", event_type="debt_payment", account_id=account.id,
                     payment_debt_id=debt.id),
    ])
    session.flush()

    result = forecast_interval(session, date(2026, 8, 15), date(2026, 8, 31), today=date(2026, 8, 1))
    row = result.debts[0]
    debt_total = next(item for item in result.summary if item.key == "debt")

    assert row.start_balance == Decimal("900.0000")
    assert row.payments == Decimal("300.0000")
    assert row.charges == Decimal("150.0000")
    assert row.net_reduction == Decimal("150.0000")
    assert row.end_balance == Decimal("750.0000")
    assert debt_total.start_value == Decimal("900.0000")
    assert debt_total.end_value == Decimal("750.0000")
    assert debt_total.improvement == Decimal("150.0000")
