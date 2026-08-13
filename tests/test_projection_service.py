from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, Currency, IncomeSource, RecurringExpense, Schedule, ScheduleType
from finance_tracker.services.projection_service import committed_cash, generate_events, lowest_projected_balance, project, safe_to_spend


def test_projection_running_balance_and_same_day_order(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$"))
    session.flush()
    account = Account(name="Chequing", account_type="checking", current_balance=Decimal("1000"), currency="CAD")
    pay = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 14))
    bill = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 15))
    session.add_all([account, pay, bill]); session.flush()
    session.add_all([
        IncomeSource(name="Salary", amount=Decimal("2000"), currency="CAD", schedule_id=pay.id, destination_account_id=account.id),
        RecurringExpense(name="Bill", amount=Decimal("500"), currency="CAD", schedule_id=bill.id, payment_account_id=account.id),
    ]); session.flush()
    events = generate_events(session, date(2026, 8, 14), date(2026, 8, 15))
    result = project(Decimal("1000"), events)
    assert [event.running_balance for event in result] == [Decimal("3000"), Decimal("2500")]
    assert lowest_projected_balance(Decimal("1000"), events) == Decimal("1000")
    assert committed_cash(events) == Decimal("500")
    assert safe_to_spend(Decimal("1000"), events, Decimal("750")) == Decimal("250")


def test_projection_can_go_negative(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    schedule = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 15))
    session.add(schedule); session.flush()
    session.add(RecurringExpense(name="Rent", amount=Decimal("1500"), currency="CAD", schedule_id=schedule.id)); session.flush()
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 31))
    assert project(Decimal("1000"), events)[0].running_balance == Decimal("-500")
    assert safe_to_spend(Decimal("1000"), events, Decimal("0"), clamp=False) == Decimal("-500")

