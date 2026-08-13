from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

BOC_FXUSDCAD = "https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?recent=1"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"


class MarketDataError(RuntimeError):
    pass


def parse_boc_usd_cad(payload: dict) -> tuple[Decimal, date]:
    try:
        observation = payload["observations"][-1]
        value = Decimal(str(observation["FXUSDCAD"]["v"]))
        rate_date = date.fromisoformat(observation["d"])
    except (KeyError, IndexError, TypeError, InvalidOperation, ValueError) as exc:
        raise MarketDataError("Bank of Canada did not return a usable USD/CAD rate.") from exc
    if value <= 0:
        raise MarketDataError("Bank of Canada returned an invalid USD/CAD rate.")
    return value, rate_date


def parse_yahoo_quote(payload: dict) -> tuple[Decimal, str, date]:
    try:
        result = payload["chart"]["result"][0]
        meta = result["meta"]
        price = Decimal(str(meta["regularMarketPrice"]))
        currency = str(meta.get("currency") or "USD").upper()
        timestamp = meta.get("regularMarketTime") or (result.get("timestamp") or [None])[-1]
        price_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date() if timestamp else date.today()
    except (KeyError, IndexError, TypeError, InvalidOperation, ValueError) as exc:
        raise MarketDataError("Yahoo Finance did not return a usable quote.") from exc
    if price <= 0:
        raise MarketDataError("Yahoo Finance returned an invalid price.")
    return price, currency, price_date


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": "personal-finance-tracker/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())
    except urllib.error.URLError as exc:
        raise MarketDataError(f"Network request failed: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise MarketDataError("Market data response was not valid JSON.") from exc


def fetch_usd_cad() -> tuple[Decimal, date]:
    return parse_boc_usd_cad(_get_json(BOC_FXUSDCAD))


def fetch_quote(symbol: str) -> tuple[Decimal, str, date]:
    encoded = urllib.parse.quote(symbol.strip().upper())
    return parse_yahoo_quote(_get_json(YAHOO_CHART.format(symbol=encoded)))
