from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN


def decimal_amount(value: str | int | Decimal) -> Decimal:
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"Invalid monetary amount: {value!r}") from exc


def quantize_money(value: Decimal, decimals: int = 2) -> Decimal:
    quantum = Decimal(1).scaleb(-decimals)
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def format_money(value: Decimal, currency: str = "CAD") -> str:
    prefix = "US$" if currency == "USD" else "$" if currency == "CAD" else ""
    sign = "-" if value < 0 else ""
    absolute = quantize_money(abs(value))
    suffix = "" if prefix else f" {currency}"
    return f"{sign}{prefix}{absolute:,.2f}{suffix}"

