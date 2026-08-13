from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from finance_tracker.db.models import Currency, ExchangeRate
from finance_tracker.services.currency_service import convert, upsert_rate


def test_same_currency_is_identity(session: Session):
    value = Decimal("100.1234")
    assert convert(value, "CAD", "CAD", session) == value


def test_conversion_and_inverse_preserve_native_value(session: Session):
    session.add_all([Currency(code="CAD", name="Canadian Dollar", symbol="$"), Currency(code="USD", name="US Dollar", symbol="US$")])
    session.flush()
    session.add(ExchangeRate(base_currency="USD", quote_currency="CAD", rate=Decimal("1.40"), rate_date=date(2026, 8, 1)))
    session.flush()
    native = Decimal("100")
    assert convert(native, "USD", "CAD", session) == Decimal("140.00")
    assert convert(Decimal("140"), "CAD", "USD", session) == Decimal("100")
    assert native == Decimal("100")


def test_upsert_rate_updates_same_pair_and_date(session: Session):
    session.add_all([Currency(code="CAD", name="Canadian Dollar", symbol="$"), Currency(code="USD", name="US Dollar", symbol="US$")])
    session.flush()
    first = upsert_rate(session, "USD", "CAD", Decimal("1.35"), date(2026, 8, 12), "api")
    session.flush()
    second = upsert_rate(session, "USD", "CAD", Decimal("1.3725"), date(2026, 8, 12), "api")
    session.flush()
    assert first.id == second.id
    assert convert(Decimal("100"), "USD", "CAD", session) == Decimal("137.25")

