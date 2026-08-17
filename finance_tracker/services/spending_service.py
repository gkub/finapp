from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from finance_tracker.db.models import Account, BalanceSnapshot, SpendingEntry
from finance_tracker.services.currency_service import RateUnavailable, convert
from finance_tracker.services.projection_service import generate_events


@dataclass(frozen=True, slots=True)
class SpendingSummary:
    requested_start: date
    requested_end: date
    observed_start: date | None
    observed_end: date | None
    balance_change: Decimal | None
    expected_cash_change: Decimal
    known_spending: Decimal
    estimated_general_spending: Decimal | None
    allocated_general_spending: Decimal
    unallocated_general_spending: Decimal | None
    total_spending: Decimal

    
    @property
    def has_balance_observation(self) -> bool:
        return self.balance_change is not None


def _cash_snapshot_totals(
    session: Session, start: date, end: date, reporting_currency: str,
) -> dict[date, Decimal]:
    rows = session.execute(
        select(BalanceSnapshot, Account)
        .join(Account, BalanceSnapshot.account_id == Account.id)
        .where(
            Account.include_in_cash.is_(True),
            Account.active.is_(True),
            BalanceSnapshot.snapshot_date <= end,
        )
        .order_by(BalanceSnapshot.snapshot_date, BalanceSnapshot.id)
    ).all()
    snapshots_by_account: dict[int, list[BalanceSnapshot]] = defaultdict(list)
    dates: set[date] = set()
    for snapshot, _account in rows:
        snapshots_by_account[snapshot.account_id].append(snapshot)
        dates.add(snapshot.snapshot_date)
    totals: dict[date, Decimal] = {}
    for on_date in sorted(dates):
        total = Decimal("0")
        found = False
        for snapshots in snapshots_by_account.values():
            applicable = [item for item in snapshots if item.snapshot_date <= on_date]
            if not applicable:
                continue
            snapshot = applicable[-1]
            try:
                total += convert(snapshot.balance, snapshot.currency, reporting_currency, session, on_date)
                found = True
            except RateUnavailable:
                continue
        if found:
            totals[on_date] = total
    return totals


def summarize_spending(
    session: Session, start: date, end: date, reporting_currency: str = "CAD",
) -> SpendingSummary:
    if end < start:
        raise ValueError("end must not be before start")
    snapshots = _cash_snapshot_totals(session, start, end, reporting_currency)
    observed_start = observed_end = None
    balance_change = None
    if len(snapshots) >= 2:
        before_or_on_start = [item for item in snapshots if item <= start]
        observed_start = max(before_or_on_start) if before_or_on_start else min(snapshots)
        observed_end = max(snapshots)
        if observed_end > observed_start:
            balance_change = snapshots[observed_end] - snapshots[observed_start]

    event_start = (observed_start + timedelta(days=1)) if observed_start else start
    event_end = observed_end or end
    events = generate_events(session, event_start, event_end, reporting_currency)
    expected_cash = sum((
        event.reporting_amount for event in events
        if event.event_type in {"income", "expense", "debt_payment", "deposit", "adjustment"}
    ), Decimal("0"))
    known_spending = -sum((
        event.reporting_amount for event in events
        if event.event_type in {"expense", "card_charge"} and event.reporting_amount < 0
    ), Decimal("0"))

    entries = session.scalars(select(SpendingEntry).where(
        SpendingEntry.entry_date.between(event_start, event_end),
    )).all()
    allocated = Decimal("0")
    for entry in entries:
        try:
            allocated += convert(entry.amount, entry.currency, reporting_currency, session, entry.entry_date)
        except RateUnavailable:
            continue

    estimated = None
    unallocated = None
    if balance_change is not None:
        estimated = max(expected_cash - balance_change, Decimal("0"))
        unallocated = max(estimated - allocated, Decimal("0"))
        total = known_spending + max(estimated, allocated)
    else:
        total = known_spending + allocated

    return SpendingSummary(
        start, end, observed_start, observed_end, balance_change, expected_cash,
        known_spending, estimated, allocated, unallocated, total,
    )


def monthly_period(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    return today.replace(day=1), today
