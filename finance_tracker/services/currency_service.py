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


def latest_rate(session: Session, base: str = "USD", quote: str = "CAD") -> ExchangeRate | None:
    return session.scalar(select(ExchangeRate).where(
        or_(
            (ExchangeRate.base_currency == base) & (ExchangeRate.quote_currency == quote),
            (ExchangeRate.base_currency == quote) & (ExchangeRate.quote_currency == base),
        )
    ).order_by(ExchangeRate.rate_date.desc(), ExchangeRate.created_at.desc()).limit(1))


def upsert_rate(session: Session, base: str, quote: str, rate: Decimal, rate_date: date,
                source: str = "manual") -> ExchangeRate:
    existing = session.scalar(select(ExchangeRate).where(
        ExchangeRate.base_currency == base, ExchangeRate.quote_currency == quote,
        ExchangeRate.rate_date == rate_date, ExchangeRate.source == source,
    ))
    if existing is None:
        existing = ExchangeRate(base_currency=base, quote_currency=quote, rate=rate,
                                rate_date=rate_date, source=source)
        session.add(existing)
        return existing
    existing.rate = rate
    return existing

