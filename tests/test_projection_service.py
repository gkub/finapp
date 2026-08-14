from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import (
    Account, Currency, Debt, Deposit, IncomeSource, InvestmentAccount, OneTimeEvent, RecurringExpense, Schedule,
    ScheduleType,
)
from finance_tracker.services.balance_service import record_debt_paydown
from finance_tracker.services.projection_service import (
    PositionDelta, committed_cash, generate_events, lowest_projected_balance, position_at, project, safe_to_spend,
)


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


def test_credit_card_charges_do_not_hit_operating_cash(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    chequing = Account(name="Chequing", account_type="checking", current_balance=Decimal("2000"), currency="CAD")
    charge_day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 10))
    pay_day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 20))
    session.add_all([chequing, charge_day, pay_day]); session.flush()
    visa = Debt(
        name="Visa", debt_type="credit_card", current_balance=Decimal("400"), currency="CAD",
        minimum_payment=Decimal("400"), payment_schedule_id=pay_day.id, payment_account_id=chequing.id,
    )
    session.add(visa); session.flush()
    session.add(RecurringExpense(
        name="Netflix", amount=Decimal("20"), currency="CAD", schedule_id=charge_day.id,
        payment_debt_id=visa.id,
    )); session.flush()
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 31))
    names = [event.description for event in events]
    assert any(name.startswith("Netflix") for name in names)
    assert "Visa" in names
    result = project(Decimal("2000"), events, starting_cards=Decimal("400"), starting_debt=Decimal("400"))
    assert result[-1].running_balance == Decimal("1600")
    assert result[-1].running_cards == Decimal("20")
    assert result[-1].running_debt == Decimal("20")
    netflix = next(event for event in result if event.description.startswith("Netflix"))
    assert netflix.event_type == "card_charge"
    assert netflix.running_balance == Decimal("2000")
    assert netflix.running_cards == Decimal("420")
    assert netflix.running_debt == Decimal("420")


def test_missing_fx_does_not_drop_cad_expenses(session: Session):
    session.add_all([
        Currency(code="CAD", name="Canadian Dollar", symbol="$"),
        Currency(code="USD", name="US Dollar", symbol="US$"),
    ]); session.flush()
    cad = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 15))
    usd = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 16))
    session.add_all([cad, usd]); session.flush()
    session.add_all([
        RecurringExpense(name="Rent", amount=Decimal("1500"), currency="CAD", schedule_id=cad.id),
        RecurringExpense(name="AWS", amount=Decimal("20"), currency="USD", schedule_id=usd.id),
    ]); session.flush()
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 31))
    assert [event.description for event in events] == ["Rent"]


def test_position_at_start_of_day_vs_end_of_day(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    account = Account(name="Chequing", account_type="checking", current_balance=Decimal("1000"), currency="CAD")
    pay = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 14))
    bill = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 15))
    session.add_all([account, pay, bill]); session.flush()
    session.add_all([
        IncomeSource(name="Salary", amount=Decimal("2000"), currency="CAD", schedule_id=pay.id, destination_account_id=account.id),
        RecurringExpense(name="Bill", amount=Decimal("500"), currency="CAD", schedule_id=bill.id, payment_account_id=account.id),
    ]); session.flush()
    rows = project(Decimal("1000"), generate_events(session, date(2026, 8, 14), date(2026, 8, 15)),
                   starting_investments=Decimal("5000"))
    args = (Decimal("1000"), Decimal("0"), Decimal("0"), Decimal("5000"), Decimal("6000"))
    before_pay = position_at(date(2026, 8, 14), rows, *args, inclusive=False)
    payday = position_at(date(2026, 8, 14), rows, *args, inclusive=True)
    after_bill = position_at(date(2026, 8, 15), rows, *args, inclusive=True)
    assert before_pay.cash == Decimal("1000")
    assert payday.cash == Decimal("3000")
    assert after_bill.cash == Decimal("2500")
    assert after_bill.investments == Decimal("5000")
    assert after_bill.net_worth == Decimal("7500")
    delta = PositionDelta.between(before_pay, after_bill)
    assert delta.cash == Decimal("1500")
    assert delta.net_worth == Decimal("1500")
    assert delta.investments == Decimal("0")


def test_excluding_a_subscription_does_not_change_saved_expenses(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    chequing = Account(name="Chequing", account_type="checking", current_balance=Decimal("2000"), currency="CAD")
    charge_day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 10))
    pay_day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 20))
    session.add_all([chequing, charge_day, pay_day]); session.flush()
    visa = Debt(
        name="Visa", debt_type="credit_card", current_balance=Decimal("400"), currency="CAD",
        minimum_payment=Decimal("400"), payment_schedule_id=pay_day.id, payment_account_id=chequing.id,
    )
    session.add(visa); session.flush()
    netflix = RecurringExpense(
        name="Netflix", amount=Decimal("20"), currency="CAD", schedule_id=charge_day.id, payment_debt_id=visa.id,
    )
    session.add(netflix); session.flush()
    skipped = generate_events(session, date(2026, 8, 1), date(2026, 8, 31), exclude_expense_ids={netflix.id})
    assert all(not event.description.startswith("Netflix") for event in skipped)
    result = project(Decimal("2000"), skipped, Decimal("400"), Decimal("400"))
    assert result[-1].running_balance == Decimal("1600")
    assert result[-1].running_cards == Decimal("0")
    assert result[-1].running_debt == Decimal("0")
    still_there = session.get(RecurringExpense, netflix.id)
    assert still_there is not None and still_there.active is True


def test_zero_scheduled_debt_payment_is_not_projected(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    chequing = Account(name="Chequing", account_type="checking", current_balance=Decimal("2000"), currency="CAD")
    pay_day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 20))
    session.add_all([chequing, pay_day]); session.flush()
    session.add(Debt(
        name="Visa", debt_type="credit_card", current_balance=Decimal("400"), currency="CAD",
        minimum_payment=Decimal("0"), payment_schedule_id=pay_day.id, payment_account_id=chequing.id,
    )); session.flush()
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 31))
    assert events == []


def test_manual_paydown_plan_moves_cash_and_cards_in_projection(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    chequing = Account(name="Chequing", account_type="checking", current_balance=Decimal("2000"), currency="CAD")
    session.add(chequing); session.flush()
    visa = Debt(name="Visa", debt_type="credit_card", current_balance=Decimal("400"), currency="CAD")
    session.add(visa); session.flush()
    record_debt_paydown(session, visa, Decimal("150"), date(2026, 8, 20), chequing, today=date(2026, 8, 13))
    session.flush()
    assert chequing.current_balance == Decimal("2000")
    assert visa.current_balance == Decimal("400")
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 31))
    assert [event.event_type for event in events] == ["debt_payment"]
    result = project(Decimal("2000"), events, Decimal("400"), Decimal("400"))
    assert result[-1].running_balance == Decimal("1850")
    assert result[-1].running_cards == Decimal("250")
    assert result[-1].running_debt == Decimal("250")
    booked = record_debt_paydown(session, visa, Decimal("150"), date(2026, 8, 20), chequing, today=date(2026, 8, 20))
    session.flush()
    assert booked.applied is True
    assert session.scalars(select(OneTimeEvent)).all() == [booked]
    assert chequing.current_balance == Decimal("1850")
    assert visa.current_balance == Decimal("250")
    assert generate_events(session, date(2026, 8, 20), date(2026, 8, 31)) == []


def test_deposit_to_investment_from_chequing_is_a_transfer(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    chequing = Account(name="Chequing", account_type="checking", current_balance=Decimal("2000"), currency="CAD")
    tfsa = InvestmentAccount(name="TFSA", account_type="tfsa", cash_balance=Decimal("100"), cash_currency="CAD")
    day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 15))
    session.add_all([chequing, tfsa, day]); session.flush()
    session.add(Deposit(
        name="TFSA contribution", amount=Decimal("500"), currency="CAD", schedule_id=day.id,
        source_account_id=chequing.id, destination_investment_id=tfsa.id,
    )); session.flush()
    events = generate_events(session, date(2026, 8, 1), date(2026, 8, 31))
    assert [event.event_type for event in events] == ["deposit"]
    result = project(Decimal("2000"), events, starting_investments=Decimal("10000"))
    assert result[-1].running_balance == Decimal("1500")
    assert result[-1].running_investments == Decimal("10500")
    position = position_at(
        date(2026, 8, 15), result, Decimal("2000"), Decimal("0"), Decimal("0"),
        Decimal("10000"), Decimal("12000"), inclusive=True,
    )
    assert position.cash == Decimal("1500")
    assert position.investments == Decimal("10500")
    assert position.net_worth == Decimal("12000")


def test_new_money_deposit_to_investment_does_not_hit_cash(session: Session):
    session.add(Currency(code="CAD", name="Canadian Dollar", symbol="$")); session.flush()
    tfsa = InvestmentAccount(name="FHSA", account_type="fhsa", cash_balance=Decimal("0"), cash_currency="CAD")
    day = Schedule(schedule_type=ScheduleType.ONE_TIME.value, anchor_date=date(2026, 8, 15))
    session.add_all([tfsa, day]); session.flush()
    session.add(Deposit(
        name="FHSA deposit", amount=Decimal("200"), currency="CAD", schedule_id=day.id,
        destination_investment_id=tfsa.id,
    )); session.flush()
    result = project(Decimal("800"), generate_events(session, date(2026, 8, 1), date(2026, 8, 31)),
                     starting_investments=Decimal("1000"))
    assert result[-1].running_balance == Decimal("800")
    assert result[-1].running_investments == Decimal("1200")

