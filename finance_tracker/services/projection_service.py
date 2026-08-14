from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, Debt, Deposit, IncomeSource, OneTimeEvent, RecurringExpense, Schedule
from finance_tracker.services.currency_service import RateUnavailable, convert
from finance_tracker.services.schedule_service import InvalidSchedule, occurrences


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
    debt_type: str | None = None
    running_balance: Decimal = Decimal("0")
    running_cards: Decimal = Decimal("0")
    running_debt: Decimal = Decimal("0")
    running_investments: Decimal = Decimal("0")
    investment_delta: Decimal = Decimal("0")
    category: str | None = None


_ORDER = {"income": 0, "deposit": 1, "adjustment": 1, "expense": 2, "card_charge": 2, "debt_payment": 3}
_CASH_EVENT_TYPES = frozenset({"income", "expense", "debt_payment", "adjustment", "deposit"})


def _in_cash(session: Session, account_id: int | None) -> bool:
    if account_id is None:
        return False
    account = session.get(Account, account_id)
    return bool(account and account.active and account.include_in_cash)


def _deposit_impacts(session: Session, deposit: Deposit, converted: Decimal) -> tuple[Decimal, Decimal]:
    """Return (cash_delta, investment_delta) in reporting currency."""
    to_investment = deposit.destination_investment_id is not None
    source_cash = _in_cash(session, deposit.source_account_id)
    dest_cash = _in_cash(session, deposit.destination_account_id)
    if to_investment:
        return (-converted if source_cash else Decimal("0"), converted)
    if dest_cash and not source_cash:
        return converted, Decimal("0")
    if source_cash and not dest_cash:
        return -converted, Decimal("0")
    return Decimal("0"), Decimal("0")


def _debt_type(session: Session, debt_id: int | None) -> str | None:
    if debt_id is None:
        return None
    debt = session.get(Debt, debt_id)
    return debt.debt_type if debt is not None else "credit_card"


def _converted(amount: Decimal, currency: str, reporting_currency: str, session: Session, on_date: date) -> Decimal | None:
    try:
        return convert(amount, currency, reporting_currency, session, on_date)
    except RateUnavailable:
        return None


def _occurrence_dates(schedule: Schedule | None, range_start: date, range_end: date) -> list[date]:
    if schedule is None:
        return []
    try:
        return occurrences(schedule, range_start, range_end)
    except InvalidSchedule:
        return []


def generate_events(
    session: Session,
    range_start: date,
    range_end: date,
    reporting_currency: str = "CAD",
    exclude_expense_ids: frozenset[int] | None = None,
) -> list[ProjectionEvent]:
    events: list[ProjectionEvent] = []

    incomes = session.scalars(select(IncomeSource).where(IncomeSource.active.is_(True))).all()
    for income in incomes:
        for on_date in _occurrence_dates(session.get(Schedule, income.schedule_id), range_start, range_end):
            if income.start_date and on_date < income.start_date or income.end_date and on_date > income.end_date:
                continue
            amount = _converted(income.amount, income.currency, reporting_currency, session, on_date)
            if amount is None:
                continue
            events.append(ProjectionEvent(on_date, income.name, income.amount, income.currency, amount,
                                          "income", income.id, income.destination_account_id))

    deposits = session.scalars(select(Deposit).where(Deposit.active.is_(True))).all()
    for deposit in deposits:
        for on_date in _occurrence_dates(session.get(Schedule, deposit.schedule_id), range_start, range_end):
            converted = _converted(deposit.amount, deposit.currency, reporting_currency, session, on_date)
            if converted is None:
                continue
            cash_delta, investment_delta = _deposit_impacts(session, deposit, converted)
            events.append(ProjectionEvent(
                on_date, deposit.name, deposit.amount, deposit.currency, cash_delta,
                "deposit", deposit.id, deposit.source_account_id,
                investment_delta=investment_delta,
            ))

    skip_expenses = exclude_expense_ids or frozenset()
    expenses = session.scalars(select(RecurringExpense).where(RecurringExpense.active.is_(True))).all()
    for expense in expenses:
        if expense.id in skip_expenses:
            continue
        for on_date in _occurrence_dates(session.get(Schedule, expense.schedule_id), range_start, range_end):
            if expense.start_date and on_date < expense.start_date or expense.end_date and on_date > expense.end_date:
                continue
            native = -expense.amount
            amount = _converted(native, expense.currency, reporting_currency, session, on_date)
            if amount is None:
                continue
            charged = expense.payment_debt_id is not None
            label = f"{expense.name} (card)" if charged else expense.name
            charge_type = _debt_type(session, expense.payment_debt_id) if charged else None
            events.append(ProjectionEvent(on_date, label, native, expense.currency, amount,
                                          "card_charge" if charged else "expense", expense.id,
                                          expense.payment_account_id, charge_type))

    debts = session.scalars(select(Debt).where(
        Debt.active.is_(True),
        Debt.minimum_payment.is_not(None),
        Debt.minimum_payment > 0,
        Debt.payment_schedule_id.is_not(None),
    )).all()
    for debt in debts:
        for on_date in _occurrence_dates(session.get(Schedule, debt.payment_schedule_id), range_start, range_end):
            native = -debt.minimum_payment
            amount = _converted(native, debt.currency, reporting_currency, session, on_date)
            if amount is None:
                continue
            events.append(ProjectionEvent(on_date, debt.name, native, debt.currency, amount,
                                          "debt_payment", debt.id, debt.payment_account_id, debt.debt_type))

    one_time = session.scalars(select(OneTimeEvent).where(OneTimeEvent.event_date.between(range_start, range_end))).all()
    for item in one_time:
        if item.event_type == "debt_payment":
            if item.applied:
                continue
            native = -item.amount
            amount = _converted(native, item.currency, reporting_currency, session, item.event_date)
            if amount is None:
                continue
            events.append(ProjectionEvent(
                item.event_date, item.name, native, item.currency, amount,
                "debt_payment", item.id, item.account_id, _debt_type(session, item.payment_debt_id),
            ))
            continue
        native = item.amount if item.event_type == "income" else -item.amount
        amount = _converted(native, item.currency, reporting_currency, session, item.event_date)
        if amount is None:
            continue
        charged = item.payment_debt_id is not None and item.event_type != "income"
        label = f"{item.name} (card)" if charged else item.name
        charge_type = _debt_type(session, item.payment_debt_id) if charged else None
        events.append(ProjectionEvent(item.event_date, label, native, item.currency, amount,
                                      "card_charge" if charged else item.event_type, item.id,
                                      item.account_id, charge_type))

    return sorted(events, key=lambda event: (event.date, _ORDER.get(event.event_type, 4), event.description.casefold(), event.source_record_id))


def project(
    starting_cash: Decimal,
    events: list[ProjectionEvent],
    starting_cards: Decimal = Decimal("0"),
    starting_debt: Decimal = Decimal("0"),
    starting_investments: Decimal = Decimal("0"),
) -> list[ProjectionEvent]:
    cash, cards, debt, investments = starting_cash, starting_cards, starting_debt, starting_investments
    projected: list[ProjectionEvent] = []
    for event in events:
        if event.event_type in _CASH_EVENT_TYPES:
            cash += event.reporting_amount
        if event.event_type == "card_charge":
            charged = -event.reporting_amount
            debt += charged
            if event.debt_type == "credit_card":
                cards += charged
        elif event.event_type == "debt_payment":
            paid = -event.reporting_amount
            debt -= paid
            if event.debt_type == "credit_card":
                cards -= paid
        investments += event.investment_delta
        projected.append(replace(
            event, running_balance=cash, running_cards=cards, running_debt=debt, running_investments=investments,
        ))
    return projected


def lowest_projected_balance(starting_cash: Decimal, events: list[ProjectionEvent]) -> Decimal:
    balances = [starting_cash, *(event.running_balance for event in project(starting_cash, events))]
    return min(balances)


def committed_cash(events: list[ProjectionEvent]) -> Decimal:
    return -sum(
        (event.reporting_amount for event in events
         if event.event_type in {"expense", "debt_payment", "deposit"} and event.reporting_amount < 0),
        Decimal("0"),
    )


def safe_to_spend(starting_cash: Decimal, events: list[ProjectionEvent], reserve: Decimal, clamp: bool = True) -> Decimal:
    value = lowest_projected_balance(starting_cash, events) - reserve
    return max(value, Decimal("0")) if clamp else value


@dataclass(frozen=True, slots=True)
class ProjectedPosition:
    on_date: date
    cash: Decimal
    cards: Decimal
    debt: Decimal
    investments: Decimal
    net_worth: Decimal


@dataclass(frozen=True, slots=True)
class PositionDelta:
    cash: Decimal
    cards: Decimal
    debt: Decimal
    investments: Decimal
    net_worth: Decimal

    @classmethod
    def between(cls, start: ProjectedPosition, end: ProjectedPosition) -> PositionDelta:
        return cls(
            end.cash - start.cash,
            end.cards - start.cards,
            end.debt - start.debt,
            end.investments - start.investments,
            end.net_worth - start.net_worth,
        )


def position_at(
    on_date: date,
    rows: list[ProjectionEvent],
    starting_cash: Decimal,
    starting_cards: Decimal,
    starting_debt: Decimal,
    investments: Decimal,
    net_worth: Decimal,
    inclusive: bool = True,
) -> ProjectedPosition:
    """Balances after events on on_date (inclusive) or strictly before it."""
    if inclusive:
        applicable = [event for event in rows if event.date <= on_date]
    else:
        applicable = [event for event in rows if event.date < on_date]
    if not applicable:
        cash, cards, debt, invested = starting_cash, starting_cards, starting_debt, investments
    else:
        last = applicable[-1]
        cash, cards, debt, invested = last.running_balance, last.running_cards, last.running_debt, last.running_investments
    projected_net = net_worth + (cash - starting_cash) - (debt - starting_debt) + (invested - investments)
    return ProjectedPosition(on_date, cash, cards, debt, invested, projected_net)

