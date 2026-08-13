from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import Debt, IncomeSource, OneTimeEvent, RecurringExpense, Schedule
from finance_tracker.services.currency_service import convert
from finance_tracker.services.schedule_service import occurrences


@dataclass(frozen=True, slots=True)
class ProjectionEvent:
    date: date
    description: str
    amount: Decimal
    currency: str
    reporting_amount: Decimal
    event_type: str
    source_record_id: int
    account_id: int | None
    running_balance: Decimal = Decimal("0")
    category: str | None = None


_ORDER = {"income": 0, "adjustment": 1, "expense": 2, "debt_payment": 3}


def _converted(amount: Decimal, currency: str, reporting_currency: str, session: Session, on_date: date) -> Decimal:
    return convert(amount, currency, reporting_currency, session, on_date)


def generate_events(
    session: Session,
    range_start: date,
    range_end: date,
    reporting_currency: str = "CAD",
) -> list[ProjectionEvent]:
    events: list[ProjectionEvent] = []

    incomes = session.scalars(select(IncomeSource).where(IncomeSource.active.is_(True))).all()
    for income in incomes:
        schedule = session.get(Schedule, income.schedule_id)
        if schedule is None:
            continue
        for on_date in occurrences(schedule, range_start, range_end):
            if income.start_date and on_date < income.start_date or income.end_date and on_date > income.end_date:
                continue
            amount = _converted(income.amount, income.currency, reporting_currency, session, on_date)
            events.append(ProjectionEvent(on_date, income.name, income.amount, income.currency, amount,
                                          "income", income.id, income.destination_account_id))

    expenses = session.scalars(select(RecurringExpense).where(RecurringExpense.active.is_(True))).all()
    for expense in expenses:
        schedule = session.get(Schedule, expense.schedule_id)
        if schedule is None:
            continue
        for on_date in occurrences(schedule, range_start, range_end):
            if expense.start_date and on_date < expense.start_date or expense.end_date and on_date > expense.end_date:
                continue
            native = -expense.amount
            amount = _converted(native, expense.currency, reporting_currency, session, on_date)
            events.append(ProjectionEvent(on_date, expense.name, native, expense.currency, amount,
                                          "expense", expense.id, expense.payment_account_id))

    debts = session.scalars(select(Debt).where(Debt.active.is_(True), Debt.minimum_payment.is_not(None),
                                                Debt.payment_schedule_id.is_not(None))).all()
    for debt in debts:
        schedule = session.get(Schedule, debt.payment_schedule_id)
        if schedule is None:
            continue
        for on_date in occurrences(schedule, range_start, range_end):
            native = -debt.minimum_payment
            amount = _converted(native, debt.currency, reporting_currency, session, on_date)
            events.append(ProjectionEvent(on_date, debt.name, native, debt.currency, amount,
                                          "debt_payment", debt.id, debt.payment_account_id))

    one_time = session.scalars(select(OneTimeEvent).where(OneTimeEvent.event_date.between(range_start, range_end))).all()
    for item in one_time:
        native = item.amount if item.event_type == "income" else -item.amount
        amount = _converted(native, item.currency, reporting_currency, session, item.event_date)
        events.append(ProjectionEvent(item.event_date, item.name, native, item.currency, amount,
                                      item.event_type, item.id, item.account_id))

    return sorted(events, key=lambda event: (event.date, _ORDER.get(event.event_type, 4), event.description.casefold(), event.source_record_id))


def project(starting_cash: Decimal, events: list[ProjectionEvent]) -> list[ProjectionEvent]:
    running = starting_cash
    projected: list[ProjectionEvent] = []
    for event in events:
        running += event.reporting_amount
        projected.append(replace(event, running_balance=running))
    return projected


def lowest_projected_balance(starting_cash: Decimal, events: list[ProjectionEvent]) -> Decimal:
    balances = [starting_cash, *(event.running_balance for event in project(starting_cash, events))]
    return min(balances)


def committed_cash(events: list[ProjectionEvent]) -> Decimal:
    return -sum((event.reporting_amount for event in events if event.reporting_amount < 0), Decimal("0"))


def safe_to_spend(starting_cash: Decimal, events: list[ProjectionEvent], reserve: Decimal, clamp: bool = True) -> Decimal:
    value = lowest_projected_balance(starting_cash, events) - reserve
    return max(value, Decimal("0")) if clamp else value

