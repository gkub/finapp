from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from finance_tracker.db.models import ExchangeRate


class RateUnavailable(LookupError):
    pass


def convert(amount: Decimal, source: str, target: str, session: Session, rate_date: date | None = None) -> Decimal:
    if source == target:
        return amount
    query = select(ExchangeRate).where(
        or_(
            (ExchangeRate.base_currency == source) & (ExchangeRate.quote_currency == target),
            (ExchangeRate.base_currency == target) & (ExchangeRate.quote_currency == source),
        )
    )
    if rate_date is not None:
        query = query.where(ExchangeRate.rate_date <= rate_date)
    rate = session.scalar(query.order_by(ExchangeRate.rate_date.desc(), ExchangeRate.created_at.desc()).limit(1))
    if rate is None:
        raise RateUnavailable(f"No exchange rate available for {source}/{target}")
    if rate.base_currency == source:
        return amount * rate.rate
    return amount / rate.rate

