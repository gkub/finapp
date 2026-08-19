# Product Direction — Simplification, Graphs, and Next Steps

This document captures the product discussion after the Progress redesign. It is
intended to preserve context when development moves between computers or Codex
sessions.

## Resume prompt

> Read `README.md`, `docs/HANDOFF.md`, `docs/PRODUCT_DIRECTION.md`, and the
> original full design specification before changing anything. Inspect the
> implementation and tests. Preserve all existing financial capabilities and the
> user's current database. The next proposed checkpoint is an
> information-architecture cleanup plus the first useful graphs; discuss the
> remaining Dashboard/card presentation choices with the user before implementing
> them.

## Current product concern

The application has grown feature by feature. Several pages now answer adjacent
questions and consequently feel more complicated or repetitive than necessary:

- Dashboard and Cash Flow both show projected events and balances.
- Outlook and Progress both show forward-looking scheduled values.
- The individual figures remain useful; the problem is presentation and ownership,
  not the underlying functionality.

The user strongly agrees with simplifying these areas, with one important caveat:

> Do not discard tracked card values or other useful credit metrics merely to make
> the Dashboard smaller. They can be grouped, summarized, or moved to a more
> appropriate location, but must remain readily accessible.

The precise Dashboard/card layout should be discussed with the user before coding.

## Proposed information architecture

Each top-level analytical page should have one clear job:

| Page | Question it answers |
| --- | --- |
| Dashboard | How am I doing right now? |
| Cash Flow | Exactly what money moves next? |
| Outlook | What will happen, and what if I change something? |
| Progress / Trends | What actually changed over time? |

### Dashboard

Make this an executive overview rather than a second Cash Flow page.

Proposed direction:

- Keep a small set of primary figures prominent: operating cash, safe to spend,
  available credit, total debt, and net worth.
- Preserve the other interesting tracked values—including current/projected card
  balances and credit availability—in a compact credit/debt group or another
  immediately accessible presentation.
- Add a projected operating-cash graph with the configured reserve line and the
  forecast low point.
- Show only a short list of the next important events, with the complete timeline
  remaining on Cash Flow.
- Keep investments and material assets visible in a compact balance-sheet group.

Open question: determine together whether the secondary card metrics belong in an
expandable Dashboard credit panel, a permanent second row, or a strong summary with
detail on Cash Flow/Outlook.

### Cash Flow

Make this the canonical detailed future-event timeline.

- Retain its selectable horizon.
- Retain funding source, running operating cash, investments, cards, available
  credit, and total debt.
- Add filters for income, bills, card charges, debt payments, and deposits.
- Consider daily or monthly grouping later.
- The Dashboard may preview several events, but should not duplicate this full
  table.

### Outlook

Make this the canonical scenario planner and detailed scheduled forecast.

- Retain the ability to pause recurring expenses without modifying saved records.
- Move the Scheduled Interval and Debt Detail functionality currently on Progress
  here.
- Preserve opening value, closing value, payments, new card charges, net debt
  reduction, and debt remaining.
- Avoid emphasizing static material assets in a scenario unless an actual future
  event changes them.
- Later, support temporary what-if income/expense adjustments and extra debt
  payments without changing stored records.

### Progress / Trends

Make this strictly historical and based on recorded snapshots.

- Remove the forward scheduled section after it has moved to Outlook.
- Retain independent historical dates, literal balance change, debt improvement,
  monthly pace, per-entity rows, and honest coverage warnings.
- Add recorded-history graphs for net worth, debt owed, operating cash, savings,
  and investments.
- Permit selecting individual accounts/debts or complete totals.
- Never display a partial aggregate as though it were a complete total.
- Never extrapolate a short balance swing into an absurd long-term forecast.
- Investment history must continue to disclose that value change combines
  contributions and market movement until transaction-level data can separate them.

## Graph principles

Graphs should clarify information rather than decorate pages.

First useful graphs:

1. Dashboard projected operating-cash line, including reserve and lowest-balance
   markers.
2. Progress recorded-history lines for net worth, debt, cash, and investments.

Rules:

- Projected and historical series must look visibly different.
- Sparse history should show isolated points or gaps, not a confident trend line.
- Partial aggregate coverage should suppress the total rather than graph a lie.
- Negative cash balances and overdraft limits must render correctly.
- Debt remains a positive amount owed; improvement is a reduction in that amount.
- Credit limit, amount owed, available credit, and utilization are different values
  and should not be visually conflated.

## Proposed implementation checkpoints

### Checkpoint 1: simplify page ownership


Implementation status (2026-08-19): page ownership and forecast/history separation
were manually approved and committed as `632dc25`. The current working tree is a
new, intentionally uncommitted visual checkpoint: responsive parent metric panels,
balanced tile wrapping, a scroll-safe Dashboard, better event-table sizing, and
cleaner primary/backup funding labels. Cash Flow reuses the same responsive summary
component. No database migration was required.

- Reshape Dashboard as a concise overview without losing credit/card metrics.
- Leave the detailed event table on Cash Flow.
- Move scheduled interval and debt reconciliation from Progress to Outlook.
- Rename Progress to Trends if that remains the clearest label.
- Preserve the existing services and database schema where possible.
- Stop for user validation after this checkpoint.

### Checkpoint 2: first graphs

- Add the Dashboard projected-cash graph.
- Add historical Trends graphs with selectors and coverage handling.
- Test dark, light, and pink themes for contrast.
- Stop for user validation again.

### Checkpoint 3: data freshness

- Show when finances were last updated.
- Flag stale accounts, debts, and investments without being judgmental.
- Clearly report what snapshots Update Finances recorded.
- Make historical graph quality/coverage understandable.

### Checkpoint 4: goals and planning

- Emergency-fund target.
- Debt payoff target or target date.
- Savings/investment targets.
- Compare progress at recorded historical pace with the configured scheduled plan,
  using visibly distinct language.

### Checkpoint 5: richer scenarios

- Temporary income or spending changes.
- Extra debt-payment controls.
- Baseline-versus-scenario comparisons that never mutate saved records unless the
  user explicitly saves a change.

### Later work

- Business-purpose grouping and a PayPal/Wise business overview.
- Polished macOS application packaging and desktop launch.
- Optional CSV import with remembered mappings and duplicate detection.
- Formal versioned database migrations before substantial schema evolution.

## Current technical checkpoint

Commit `632dc25` established the approved Dashboard, Cash Flow, Outlook, and Trends ownership model. The current uncommitted working tree adds the responsive visual layer described above.
At that checkpoint:

- Historical debt appears per debt, with a total only when every debt has coverage.
- A one-day balance change is recorded but is never converted into a monthly pace.
- Scheduled debt reconciles opening owed + new charges - capped payments = closing
  owed, while net reduction is shown separately.
- The full test suite reports 60 passing tests in the current uncommitted checkpoint.
- The redesign loaded successfully against a disposable copy of the user's real
  database.
- No schema migration or mutation of the live finance database was required.
- Graceful Ctrl+C shutdown and terminal-input isolation were already implemented in
  the prior checkpoint.

## Non-negotiable product rules

- Simplification means moving and grouping information, not silently deleting useful
  financial values.
- Do not break or rewrite the user's existing database.
- Current state, scheduled forecast, hypothetical scenario, and recorded history
  must remain distinct concepts.
- Net worth is not spendable cash.
- Credit availability is not an asset or cash balance.
- All authoritative money calculations remain Decimal-safe and outside Qt widgets.
- Validate meaningful feature checkpoints with the user before continuing.
