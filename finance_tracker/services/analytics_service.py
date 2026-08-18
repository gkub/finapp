from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import (
    Account, BalanceSnapshot, Debt, DebtSnapshot, InvestmentAccount,
    InvestmentSnapshot, MaterialAsset, MaterialAssetSnapshot,
)
from finance_tracker.services.currency_service import RateUnavailable, convert
from finance_tracker.services.balance_service import current_balance_sheet
from finance_tracker.services.projection_service import generate_events, position_at, project


AVERAGE_DAYS_PER_MONTH = Decimal("30.4375")
MIN_PACE_DAYS = 28


@dataclass(frozen=True, slots=True)
class PaceMetric:
    key: str
    label: str
    start_value: Decimal | None
    end_value: Decimal | None
    change: Decimal | None
    monthly_pace: Decimal | None
    projected_value: Decimal | None
    observed_start: date | None
    observed_end: date | None
    observation_count: int
    covered_entities: int
    total_entities: int
    lower_is_better: bool = False

    @property
    def available(self) -> bool:
        return self.monthly_pace is not None


@dataclass(frozen=True, slots=True)
class ScheduledMetric:
    key: str
    current_value: Decimal | None
    future_value: Decimal | None
    change: Decimal | None


@dataclass(frozen=True, slots=True)
class HistoricalMetric:
    kind: str
    key: str
    label: str
    start_value: Decimal | None
    end_value: Decimal | None
    balance_change: Decimal | None
    improvement: Decimal | None
    monthly_pace: Decimal | None
    observed_start: date | None
    observed_end: date | None
    observation_count: int
    coverage: str
    quality: str
    lower_is_better: bool = False


@dataclass(frozen=True, slots=True)
class IntervalMetric:
    key: str
    label: str
    start_value: Decimal
    end_value: Decimal
    change: Decimal
    improvement: Decimal
    lower_is_better: bool = False


@dataclass(frozen=True, slots=True)
class DebtInterval:
    debt_id: int
    label: str
    start_balance: Decimal
    payments: Decimal
    charges: Decimal
    net_reduction: Decimal
    end_balance: Decimal


@dataclass(frozen=True, slots=True)
class ForecastInterval:
    start: date
    end: date
    summary: tuple[IntervalMetric, ...]
    debts: tuple[DebtInterval, ...]


@dataclass(frozen=True, slots=True)
class _Series:
    values: dict[date, Decimal]
    covered_entities: int
    total_entities: int


def _converted(value: Decimal, currency: str, reporting_currency: str, session: Session, on_date: date) -> Decimal:
    return convert(value, currency, reporting_currency, session, on_date)


def _series(
    session: Session,
    entities: Iterable[object],
    snapshots: Iterable[object],
    entity_id: Callable[[object], int],
    snapshot_entity_id: Callable[[object], int],
    snapshot_date: Callable[[object], date],
    snapshot_value: Callable[[object], Decimal],
    snapshot_currency: Callable[[object], str],
    reporting_currency: str,
    through: date,
) -> _Series:
    ids = {entity_id(item) for item in entities}
    grouped: dict[int, list[object]] = {ident: [] for ident in ids}
    candidate_dates: set[date] = set()
    for item in snapshots:
        ident = snapshot_entity_id(item)
        on_date = snapshot_date(item)
        if ident in grouped and on_date <= through:
            grouped[ident].append(item)
            candidate_dates.add(on_date)
    grouped = {ident: items for ident, items in grouped.items() if items}
    if not grouped:
        return _Series({}, 0, len(ids))
    for items in grouped.values():
        items.sort(key=lambda item: (snapshot_date(item), getattr(item, "id", 0)))

    values: dict[date, Decimal] = {}
    for on_date in sorted(candidate_dates):
        total = Decimal("0")
        complete = True
        for items in grouped.values():
            applicable = [item for item in items if snapshot_date(item) <= on_date]
            if not applicable:
                complete = False
                break
            item = applicable[-1]
            try:
                total += _converted(
                    snapshot_value(item), snapshot_currency(item), reporting_currency, session, on_date,
                )
            except RateUnavailable:
                complete = False
                break
        if complete:
            values[on_date] = total
    return _Series(values, len(grouped), len(ids))


def _metric(
    key: str,
    label: str,
    series: _Series,
    requested_start: date,
    end: date,
    forecast_months: int,
    lower_is_better: bool = False,
) -> PaceMetric:
    dates = [item for item in series.values if item <= end]
    if len(dates) < 2:
        return PaceMetric(
            key, label, None, None, None, None, None, None, None, len(dates),
            series.covered_entities, series.total_entities, lower_is_better,
        )
    before = [item for item in dates if item <= requested_start]
    observed_start = max(before) if before else min(dates)
    observed_end = max(dates)
    elapsed = (observed_end - observed_start).days
    if elapsed < MIN_PACE_DAYS:
        return PaceMetric(
            key, label, series.values[observed_start], series.values[observed_end],
            None, None, None, observed_start, observed_end,
            sum(observed_start <= item <= observed_end for item in dates),
            series.covered_entities, series.total_entities, lower_is_better,
        )
    start_value, end_value = series.values[observed_start], series.values[observed_end]
    raw_change = end_value - start_value
    change = -raw_change if lower_is_better else raw_change
    elapsed_days = Decimal((observed_end - observed_start).days)
    monthly_pace = change * AVERAGE_DAYS_PER_MONTH / elapsed_days
    projected = end_value - monthly_pace * forecast_months if lower_is_better else end_value + monthly_pace * forecast_months
    if lower_is_better:
        projected = max(projected, Decimal("0"))
    observations = sum(observed_start <= item <= observed_end for item in dates)
    return PaceMetric(
        key, label, start_value, end_value, change, monthly_pace, projected,
        observed_start, observed_end, observations, series.covered_entities,
        series.total_entities, lower_is_better,
    )


def progress_metrics(
    session: Session,
    requested_start: date,
    end: date,
    forecast_months: int,
    reporting_currency: str = "CAD",
) -> list[PaceMetric]:
    accounts = session.scalars(select(Account).where(Account.active.is_(True))).all()
    account_snapshots = session.scalars(
        select(BalanceSnapshot).where(BalanceSnapshot.snapshot_date <= end)
    ).all()
    savings_accounts = [item for item in accounts if item.account_type == "savings"]
    cash_accounts = [item for item in accounts if item.include_in_cash]

    def account_series(items: list[Account]) -> _Series:
        return _series(
            session, items, account_snapshots, lambda item: item.id, lambda item: item.account_id,
            lambda item: item.snapshot_date, lambda item: item.balance, lambda item: item.currency,
            reporting_currency, end,
        )

    debts = session.scalars(select(Debt).where(Debt.active.is_(True))).all()
    debt_snapshots = session.scalars(select(DebtSnapshot).where(DebtSnapshot.snapshot_date <= end)).all()
    debt_series = _series(
        session, debts, debt_snapshots, lambda item: item.id, lambda item: item.debt_id,
        lambda item: item.snapshot_date, lambda item: item.balance,
        lambda item: next(debt.currency for debt in debts if debt.id == item.debt_id),
        reporting_currency, end,
    )

    investments = session.scalars(select(InvestmentAccount).where(InvestmentAccount.active.is_(True))).all()
    investment_snapshots = session.scalars(
        select(InvestmentSnapshot).where(InvestmentSnapshot.snapshot_date <= end)
    ).all()
    investment_series = _series(
        session, investments, investment_snapshots, lambda item: item.id,
        lambda item: item.investment_account_id, lambda item: item.snapshot_date,
        lambda item: item.market_value, lambda item: item.reporting_currency,
        reporting_currency, end,
    )

    assets = session.scalars(select(MaterialAsset).where(MaterialAsset.active.is_(True))).all()
    asset_snapshots = session.scalars(
        select(MaterialAssetSnapshot).where(MaterialAssetSnapshot.snapshot_date <= end)
    ).all()
    asset_series = _series(
        session, assets, asset_snapshots, lambda item: item.id, lambda item: item.material_asset_id,
        lambda item: item.snapshot_date, lambda item: item.value,
        lambda item: next(asset.currency for asset in assets if asset.id == item.material_asset_id),
        reporting_currency, end,
    )

    ordinary_series = account_series([item for item in accounts if item.include_in_net_worth])
    components = (
        (ordinary_series, Decimal("1")),
        (investment_series, Decimal("1")),
        (asset_series, Decimal("1")),
        (debt_series, Decimal("-1")),
    )
    populated = [(series, sign) for series, sign in components if series.total_entities]
    net_values: dict[date, Decimal] = {}
    complete_coverage = all(
        series.values and series.covered_entities == series.total_entities
        for series, _sign in populated
    )
    if populated and complete_coverage:
        candidate_dates = sorted(set().union(*(series.values for series, _sign in populated)))
        for on_date in candidate_dates:
            total = Decimal("0")
            complete = True
            for series, sign in populated:
                available = [item for item in series.values if item <= on_date]
                if not available:
                    complete = False
                    break
                total += series.values[max(available)] * sign
            if complete:
                net_values[on_date] = total
    net_worth_series = _Series(
        net_values,
        sum(series.covered_entities for series, _sign in populated),
        sum(series.total_entities for series, _sign in populated),
    )

    return [
        _metric("savings", "Savings accounts", account_series(savings_accounts), requested_start, end, forecast_months),
        _metric("cash", "Operating cash", account_series(cash_accounts), requested_start, end, forecast_months),
        _metric("investments", "Investment value", investment_series, requested_start, end, forecast_months),
        _metric("debt", "Total debt", debt_series, requested_start, end, forecast_months, lower_is_better=True),
        _metric("net_worth", "Net worth", net_worth_series, requested_start, end, forecast_months),
    ]


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year, month = value.year + month_index // 12, month_index % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    month_lengths = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return date(year, month, min(value.day, month_lengths[month - 1]))


def _historical_metric(kind, key, label, series, requested_start, end, lower_is_better=False, require_complete=False):
    coverage = f"{series.covered_entities}/{series.total_entities} tracked"
    empty = dict(kind=kind, key=key, label=label, start_value=None, end_value=None,
                 balance_change=None, improvement=None, monthly_pace=None,
                 observed_start=None, observed_end=None, observation_count=0,
                 lower_is_better=lower_is_better)
    if not series.total_entities:
        return HistoricalMetric(**empty, coverage="No matching records", quality="Unavailable")
    if require_complete and series.covered_entities != series.total_entities:
        return HistoricalMetric(**empty, coverage=f"Incomplete: {coverage}", quality="Unavailable")
    dates = sorted(item for item in series.values if item <= end)
    if not dates:
        return HistoricalMetric(**empty, coverage=coverage, quality="No history")
    prior = [item for item in dates if item <= requested_start]
    observed_start = max(prior) if prior else min(dates)
    observed_end = max(dates)
    observations = sum(observed_start <= item <= observed_end for item in dates)
    start_value, end_value = series.values[observed_start], series.values[observed_end]
    elapsed = (observed_end - observed_start).days
    if observations < 2 or elapsed <= 0:
        return HistoricalMetric(kind, key, label, start_value, end_value, None, None, None,
                                observed_start, observed_end, observations, coverage,
                                "One observation", lower_is_better)
    balance_change = end_value - start_value
    improvement = -balance_change if lower_is_better else balance_change
    monthly_pace = None
    quality = f"Need {MIN_PACE_DAYS}+ days for pace"
    if elapsed >= MIN_PACE_DAYS:
        monthly_pace = improvement * AVERAGE_DAYS_PER_MONTH / Decimal(elapsed)
        quality = "High" if elapsed >= 180 and observations >= 4 else (
            "Medium" if elapsed >= 90 and observations >= 3 else "Low"
        )
    return HistoricalMetric(kind, key, label, start_value, end_value, balance_change, improvement,
                            monthly_pace, observed_start, observed_end, observations, coverage,
                            quality, lower_is_better)


def historical_metrics(session, requested_start, end, reporting_currency="CAD"):
    """Return per-entity history and only complete aggregate totals."""
    if requested_start > end:
        raise ValueError("History start must not be after its end")
    accounts = session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)).all()
    account_snapshots = session.scalars(select(BalanceSnapshot).where(BalanceSnapshot.snapshot_date <= end)).all()
    debts = session.scalars(select(Debt).where(Debt.active.is_(True)).order_by(Debt.name)).all()
    debt_snapshots = session.scalars(select(DebtSnapshot).where(DebtSnapshot.snapshot_date <= end)).all()
    investments = session.scalars(select(InvestmentAccount).where(InvestmentAccount.active.is_(True)).order_by(InvestmentAccount.name)).all()
    investment_snapshots = session.scalars(select(InvestmentSnapshot).where(InvestmentSnapshot.snapshot_date <= end)).all()
    assets = session.scalars(select(MaterialAsset).where(MaterialAsset.active.is_(True))).all()
    asset_snapshots = session.scalars(select(MaterialAssetSnapshot).where(MaterialAssetSnapshot.snapshot_date <= end)).all()

    def account_series(items):
        return _series(session, items, account_snapshots, lambda x: x.id, lambda x: x.account_id,
                       lambda x: x.snapshot_date, lambda x: x.balance, lambda x: x.currency,
                       reporting_currency, end)

    def debt_series(items):
        currencies = {item.id: item.currency for item in items}
        return _series(session, items, debt_snapshots, lambda x: x.id, lambda x: x.debt_id,
                       lambda x: x.snapshot_date, lambda x: x.balance, lambda x: currencies[x.debt_id],
                       reporting_currency, end)

    def investment_series(items):
        return _series(session, items, investment_snapshots, lambda x: x.id,
                       lambda x: x.investment_account_id, lambda x: x.snapshot_date,
                       lambda x: x.market_value, lambda x: x.reporting_currency,
                       reporting_currency, end)

    rows = []
    cash_accounts = [item for item in accounts if item.include_in_cash]
    rows.append(_historical_metric("Cash", "cash", "Operating cash total", account_series(cash_accounts),
                                   requested_start, end, require_complete=True))
    for account in accounts:
        if account.account_type == "savings":
            rows.append(_historical_metric("Savings", f"account:{account.id}", account.name,
                                           account_series([account]), requested_start, end))
    for investment in investments:
        rows.append(_historical_metric("Investment", f"investment:{investment.id}", investment.name,
                                       investment_series([investment]), requested_start, end))
    rows.append(_historical_metric("Debt", "debt_total", "Total debt owed", debt_series(debts),
                                   requested_start, end, lower_is_better=True, require_complete=True))
    for debt in debts:
        rows.append(_historical_metric("Debt", f"debt:{debt.id}", debt.name, debt_series([debt]),
                                       requested_start, end, lower_is_better=True))

    ordinary = account_series([item for item in accounts if item.include_in_net_worth])
    all_debts = debt_series(debts)
    net_investments = [item for item in investments if item.include_in_net_worth]
    all_investments = investment_series(net_investments)
    net_assets = [item for item in assets if item.include_in_net_worth]
    asset_currencies = {item.id: item.currency for item in net_assets}
    all_assets = _series(session, net_assets, asset_snapshots, lambda x: x.id, lambda x: x.material_asset_id,
                         lambda x: x.snapshot_date, lambda x: x.value,
                         lambda x: asset_currencies[x.material_asset_id], reporting_currency, end)
    components = ((ordinary, Decimal("1")), (all_investments, Decimal("1")),
                  (all_assets, Decimal("1")), (all_debts, Decimal("-1")))
    populated = [(series, sign) for series, sign in components if series.total_entities]
    total_entities = sum(series.total_entities for series, _ in populated)
    covered_entities = sum(series.covered_entities for series, _ in populated)
    net_values = {}
    if populated and covered_entities == total_entities:
        candidates = sorted(set().union(*(series.values for series, _ in populated)))
        for on_date in candidates:
            available = [(series, [d for d in series.values if d <= on_date], sign)
                         for series, sign in populated]
            if all(dates for _, dates, _ in available):
                net_values[on_date] = sum((series.values[max(dates)] * sign
                                           for series, dates, sign in available), Decimal("0"))
    rows.append(_historical_metric("Overall", "net_worth", "Net worth",
                                   _Series(net_values, covered_entities, total_entities),
                                   requested_start, end, require_complete=True))
    return rows


def forecast_interval(session, start, end, reporting_currency="CAD", today=None):
    """Project configured activity over a selectable future interval."""
    today = today or date.today()
    if start < today:
        raise ValueError("Forecast start cannot be before today")
    if end < start:
        raise ValueError("Forecast end must not be before its start")
    sheet = current_balance_sheet(session, reporting_currency, today)
    projected = project(sheet.operating_cash, generate_events(session, today, end, reporting_currency),
                        sheet.credit_cards, sheet.debts, sheet.investments, sheet.credit_limit)
    opening = position_at(start, projected, sheet.operating_cash, sheet.credit_cards, sheet.debts,
                          sheet.investments, sheet.net_worth, inclusive=False)
    closing = position_at(end, projected, sheet.operating_cash, sheet.credit_cards, sheet.debts,
                          sheet.investments, sheet.net_worth)
    values = (("cash", "Operating cash", opening.cash, closing.cash, False),
              ("investments", "Investments", opening.investments, closing.investments, False),
              ("debt", "Total debt owed", opening.debt, closing.debt, True),
              ("net_worth", "Net worth", opening.net_worth, closing.net_worth, False))
    summary = tuple(IntervalMetric(key, label, before, after, after - before,
                                   before - after if lower else after - before, lower)
                    for key, label, before, after, lower in values)

    debts = session.scalars(select(Debt).where(Debt.active.is_(True)).order_by(Debt.name)).all()
    balances = {debt.id: max(convert(debt.current_balance, debt.currency, reporting_currency,
                                     session, today), Decimal("0")) for debt in debts}
    payments = {debt.id: Decimal("0") for debt in debts}
    charges = {debt.id: Decimal("0") for debt in debts}
    for event in projected:
        if event.debt_id not in balances or event.date >= start:
            continue
        amount = max(-event.reporting_amount, Decimal("0"))
        if event.event_type == "card_charge":
            balances[event.debt_id] += amount
        elif event.event_type == "debt_payment":
            balances[event.debt_id] = max(balances[event.debt_id] - amount, Decimal("0"))
    opening_debts = dict(balances)
    for event in projected:
        if event.debt_id not in balances or not start <= event.date <= end:
            continue
        amount = max(-event.reporting_amount, Decimal("0"))
        if event.event_type == "card_charge":
            charges[event.debt_id] += amount
            balances[event.debt_id] += amount
        elif event.event_type == "debt_payment":
            payments[event.debt_id] += amount
            balances[event.debt_id] = max(balances[event.debt_id] - amount, Decimal("0"))
    debt_rows = tuple(DebtInterval(debt.id, debt.name, opening_debts[debt.id], payments[debt.id],
                                   charges[debt.id], opening_debts[debt.id] - balances[debt.id],
                                   balances[debt.id]) for debt in debts)
    return ForecastInterval(start, end, summary, debt_rows)


def scheduled_metrics(
    session: Session,
    start: date,
    forecast_months: int,
    reporting_currency: str = "CAD",
) -> dict[str, ScheduledMetric]:
    """Forecast configured schedules; never extrapolate sparse balance snapshots."""
    end = _add_months(start, forecast_months)
    sheet = current_balance_sheet(session, reporting_currency, start)
    events = generate_events(session, start, end, reporting_currency)
    rows = project(
        sheet.operating_cash, events, sheet.credit_cards, sheet.debts,
        sheet.investments, sheet.credit_limit,
    )
    future = position_at(
        end, rows, sheet.operating_cash, sheet.credit_cards, sheet.debts,
        sheet.investments, sheet.net_worth,
    )
    values = {
        "cash": (sheet.operating_cash, future.cash),
        "investments": (sheet.investments, future.investments),
        "debt": (sheet.debts, future.debt),
        "net_worth": (sheet.net_worth, future.net_worth),
    }
    result = {
        key: ScheduledMetric(key, current, projected, projected - current)
        for key, (current, projected) in values.items()
    }
    result["savings"] = ScheduledMetric("savings", None, None, None)
    return result
