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


AVERAGE_DAYS_PER_MONTH = Decimal("30.4375")


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
    if observed_end <= observed_start:
        return PaceMetric(
            key, label, None, None, None, None, None, observed_start, observed_end, 1,
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
        _metric("debt", "Debt paid down", debt_series, requested_start, end, forecast_months, lower_is_better=True),
        _metric("net_worth", "Net worth", net_worth_series, requested_start, end, forecast_months),
    ]
