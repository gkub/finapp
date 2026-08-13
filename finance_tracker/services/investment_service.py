from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import InvestmentAccount, InvestmentHolding, SecurityPrice
from finance_tracker.services.currency_service import convert


class PriceUnavailable(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class HoldingValue:
    symbol: str
    native_value: Decimal
    native_currency: str
    reporting_value: Decimal
    reporting_currency: str


def latest_price(session: Session, symbol: str, on_date: date | None = None) -> SecurityPrice:
    query = select(SecurityPrice).where(SecurityPrice.symbol == symbol)
    if on_date is not None:
        query = query.where(SecurityPrice.price_date <= on_date)
    price = session.scalar(query.order_by(SecurityPrice.price_date.desc(), SecurityPrice.created_at.desc()).limit(1))
    if price is None:
        raise PriceUnavailable(f"No price has been entered for {symbol}.")
    return price


def value_holding(session: Session, holding: InvestmentHolding, reporting_currency: str = "CAD",
                  on_date: date | None = None) -> HoldingValue:
    price = latest_price(session, holding.symbol, on_date)
    native = holding.quantity * price.price
    reporting = convert(native, price.currency, reporting_currency, session, on_date)
    return HoldingValue(holding.symbol, native, price.currency, reporting, reporting_currency)


def value_account(session: Session, account: InvestmentAccount, reporting_currency: str = "CAD",
                  on_date: date | None = None) -> Decimal:
    total = convert(account.cash_balance, account.cash_currency, reporting_currency, session, on_date)
    holdings = session.scalars(select(InvestmentHolding).where(
        InvestmentHolding.investment_account_id == account.id, InvestmentHolding.active.is_(True))).all()
    return total + sum((value_holding(session, item, reporting_currency, on_date).reporting_value for item in holdings), Decimal("0"))

