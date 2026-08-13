from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, BalanceSnapshot, Debt, DebtSnapshot, InvestmentAccount
from finance_tracker.services.currency_service import RateUnavailable, convert
from finance_tracker.services.investment_service import value_account


@dataclass(frozen=True, slots=True)
class BalanceSheet:
    operating_cash: Decimal
    ordinary_assets: Decimal
    investments: Decimal
    debts: Decimal
    net_worth: Decimal
    credit_cards: Decimal


def operating_cash(session: Session, reporting_currency: str = "CAD", on_date: date | None = None) -> Decimal:
    accounts = session.scalars(select(Account).where(Account.active.is_(True), Account.include_in_cash.is_(True))).all()
    return sum((convert(item.current_balance, item.currency, reporting_currency, session, on_date) for item in accounts), Decimal("0"))


OVERDRAFT_ACCOUNT_TYPES = frozenset({"checking"})


def supports_overdraft(account_type: str) -> bool:
    """Chequing/checking accounts can overdraft; credit cards are debts, not cash accounts."""
    return account_type in OVERDRAFT_ACCOUNT_TYPES


def overdraft_headroom(account: Account) -> Decimal:
    """Amount that can still be withdrawn before an account's overdraft limit."""
    if not supports_overdraft(account.account_type) or account.overdraft_limit is None:
        return max(account.current_balance, Decimal("0"))
    return max(account.current_balance + account.overdraft_limit, Decimal("0"))


def estimated_overdraft_interest(account: Account, days: int) -> Decimal:
    """Estimate simple daily interest; the institution's posted charge remains authoritative."""
    if days < 0:
        raise ValueError("days must not be negative")
    if not supports_overdraft(account.account_type):
        return Decimal("0")
    if account.current_balance >= 0 or account.overdraft_interest_rate is None:
        return Decimal("0")
    return -account.current_balance * account.overdraft_interest_rate * Decimal(days) / Decimal("365")


def current_balance_sheet(session: Session, reporting_currency: str = "CAD", on_date: date | None = None) -> BalanceSheet:
    accounts = session.scalars(select(Account).where(Account.active.is_(True), Account.include_in_net_worth.is_(True))).all()
    ordinary = sum((convert(item.current_balance, item.currency, reporting_currency, session, on_date) for item in accounts), Decimal("0"))
    investment_accounts = session.scalars(select(InvestmentAccount).where(
        InvestmentAccount.active.is_(True), InvestmentAccount.include_in_net_worth.is_(True))).all()
    investments = sum((value_account(session, item, reporting_currency, on_date) for item in investment_accounts), Decimal("0"))
    debts = session.scalars(select(Debt).where(Debt.active.is_(True))).all()
    total_debt = Decimal("0")
    cards = Decimal("0")
    for item in debts:
        try:
            value = convert(item.current_balance, item.currency, reporting_currency, session, on_date)
        except RateUnavailable:
            continue
        total_debt += value
        if item.debt_type == "credit_card":
            cards += value
    cash = operating_cash(session, reporting_currency, on_date)
    return BalanceSheet(cash, ordinary, investments, total_debt, ordinary + investments - total_debt, cards)


def update_account_balance(session: Session, account: Account, balance: Decimal, snapshot_date: date) -> BalanceSnapshot:
    account.current_balance = balance
    snapshot = BalanceSnapshot(account=account, balance=balance, currency=account.currency, snapshot_date=snapshot_date)
    session.add(snapshot)
    return snapshot


def update_debt_balance(session: Session, debt: Debt, balance: Decimal, snapshot_date: date) -> DebtSnapshot:
    debt.current_balance = balance
    snapshot = DebtSnapshot(debt_id=debt.id, balance=balance, snapshot_date=snapshot_date)
    session.add(snapshot)
    return snapshot

