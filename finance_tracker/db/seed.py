from sqlalchemy.orm import Session

from finance_tracker.db.models import Currency, Setting


def ensure_defaults(session: Session) -> None:
    for code, name, symbol in (("CAD", "Canadian Dollar", "$"), ("USD", "US Dollar", "US$")):
        if session.get(Currency, code) is None:
            session.add(Currency(code=code, name=name, symbol=symbol, decimals=2))
    defaults = {
        "reporting_currency": "CAD",
        "default_projection_days": "30",
        "cash_reserve_amount": "0.00",
        "theme": "system",
    }
    for key, value in defaults.items():
        if session.get(Setting, key) is None:
            session.add(Setting(key=key, value=value))

