from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, Currency, Debt, RecurringExpense, Schedule, ScheduleType
from finance_tracker.services.projection_service import generate_events, project


def test_credit_payment_stops_at_zero_and_restores_available_credit(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    chequing = Account(name="Chequing", account_type="checking", current_balance=Decimal("500"), currency="CAD")
    schedule = Schedule(schedule_type=ScheduleType.EVERY_N_WEEKS.value, interval=1, anchor_date=date(2026, 8, 1))
    session.add_all([chequing, schedule])
    session.flush()
    card = Debt(name="Card", debt_type="credit_card", current_balance=Decimal("100"), currency="CAD",
                credit_limit=Decimal("1000"), minimum_payment=Decimal("150"),
                payment_schedule_id=schedule.id, payment_account_id=chequing.id)
    session.add(card)
    session.flush()
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 8))
    rows = project(Decimal("500"), events, Decimal("100"), Decimal("100"), Decimal("0"), Decimal("1000"))
    assert rows[0].reporting_amount == Decimal("-100.0000")
    assert rows[0].running_balance == Decimal("400.0000")
    assert rows[0].running_cards == Decimal("0")
    assert rows[0].running_available_credit == Decimal("1000.0000")
    assert rows[1].reporting_amount == Decimal("0")
    assert rows[1].running_balance == Decimal("400.0000")
    assert rows[1].running_debt == Decimal("0")


def test_expense_uses_primary_balance_then_backup(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    paypal = Account(name="PayPal", account_type="other", current_balance=Decimal("30"), currency="CAD")
    bank = Account(name="TD", account_type="checking", current_balance=Decimal("500"), currency="CAD")
    schedule = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 2))
    session.add_all([paypal, bank, schedule])
    session.flush()
    session.add(RecurringExpense(name="Service", amount=Decimal("50"), currency="CAD", schedule_id=schedule.id,
                                 payment_account_id=paypal.id, backup_account_id=bank.id))
    session.flush()
    event = generate_events(session, date(2026, 8, 1), date(2026, 8, 3))[0]
    row = project(Decimal("530"), [event])[0]
    assert row.running_balance == Decimal("480.0000")
    assert row.funding_summary == "PayPal 30.00; TD 20.00"
