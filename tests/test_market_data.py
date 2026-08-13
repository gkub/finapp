from datetime import date, datetime, timezone
from decimal import Decimal

from finance_tracker.services.market_data import parse_boc_usd_cad, parse_yahoo_quote


def test_parse_bank_of_canada_usd_cad():
    payload = {
        "observations": [
            {"d": "2026-08-11", "FXUSDCAD": {"v": "1.3701"}},
            {"d": "2026-08-12", "FXUSDCAD": {"v": "1.3725"}},
        ]
    }
    rate, rate_date = parse_boc_usd_cad(payload)
    assert rate == Decimal("1.3725")
    assert rate_date == date(2026, 8, 12)


def test_parse_yahoo_quote():
    stamp = int(datetime(2026, 8, 12, 20, 0, tzinfo=timezone.utc).timestamp())
    payload = {
        "chart": {
            "result": [{
                "meta": {"regularMarketPrice": 300.69, "currency": "USD", "regularMarketTime": stamp},
                "timestamp": [stamp],
            }]
        }
    }
    price, currency, price_date = parse_yahoo_quote(payload)
    assert price == Decimal("300.69")
    assert currency == "USD"
    assert price_date == date(2026, 8, 12)
