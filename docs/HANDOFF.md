# Personal Finance Tracker — Home Computer Handoff

Use this document to resume work with Codex on another computer.

## Context to give Codex

> Continue implementing this personal finance tracker. Read `README.md`,
> `docs/HANDOFF.md`, `docs/PRODUCT_DIRECTION.md`, and the full design specification in `docs/` first. Inspect
> the existing implementation and tests before changing anything. Preserve the
> local-only architecture, Decimal-safe calculations, native currencies,
> historical snapshots, and the distinction between operating cash, investments,
> debt, and net worth. Run the full test suite after changes.

## Current implementation

The project is a Python 3, PySide6, SQLAlchemy, and SQLite Linux/macOS desktop app.

Implemented:

- Local SQLite database and broad V0.1 domain schema
- CAD/USD currencies and dated manual exchange rates
- Decimal-safe money formatting and calculations
- Exact one-time, weekly, every-N-weeks, monthly, every-N-months, yearly, and specific-date schedules
- Month-end clamping, schedule boundaries, and weekend-policy architecture
- Accounts with signed balances, including negative chequing balances
- Optional overdraft limits, annual rates, headroom, and estimated interest
- Income, recurring expenses, debts, and one-time events
- Cash-flow events, running balances, committed cash, minimum cash, and safe-to-spend
- Spending reconciliation from balance snapshots, optional aggregate check-ins, and period comparisons
- Honest per-entity historical Progress analytics plus separately calculated scheduled intervals and debt reconciliation
- Credit limits, available credit, utilization, and zero-floor debt projections
- Digital-wallet accounts, independent Personal/Business purpose labels, and chronological primary/backup funding for PayPal-style payments
- Dark, light, and accessible pastel-pink themes
- Account/debt snapshots and balance updates
- Investment accounts, holdings, manual prices, and valuation
- Operating-cash, investment, debt, and net-worth calculations
- Dashboard, Cash Flow, Spending, Outlook, Progress, Accounts, Income, Recurring Expenses, Debts,
  One-Time Events, Investments, Update Finances, and Settings screens
- Add/edit/disable/delete workflows with confirmations and reference protection
- Local SQLite backup from Settings
- Graceful Ctrl+C shutdown plus interrupted-session database recovery before pull

## Fresh setup

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
git clone YOUR_REPOSITORY_URL finapp
cd finapp
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[desktop,dev]'
```

Launch:

```bash
.venv/bin/finance-tracker
```

If working inside Cursor and PySide6 appears missing:

```bash
env -u __PYVENV_LAUNCHER__ .venv/bin/finance-tracker
```

Tests:

```bash
env -u __PYVENV_LAUNCHER__ QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

Last verified state: `56 passed`, including GUI, analytics, migration, spending, credit, funding, and theme-contrast coverage.

## Moving personal data

With private sync, the database lives in its own private Git repository at:

```text
~/finance-data/finance.db
```

To move it safely:

1. Close the app on both computers.
2. Use **Settings → Back up database** on the current computer.
3. Install and launch once on the home computer, then close the app.
4. Copy the backup to the path above as `finance.db`.
5. Keep the backup private; it contains personal financial information.

## Important design rules

- Core operation remains offline and local-only.
- Never use binary `float` for authoritative financial calculations.
- Recurring cash flow is based on actual dates, never approximate monthly averages.
- Ordinary account balances are signed; standalone debt is a positive amount owed.
- Investments do not count as operating cash.
- Native monetary values and currencies are preserved; conversion is centralized.
- Current values and dated historical snapshots remain separate.
- Prefer disabling records when history matters; require confirmation for deletion.
- Business calculations remain outside Qt widgets.

## Known issues and rough edges

- The project currently creates tables with `metadata.create_all`; a real Alembic
  migration workflow still needs to be established before schema evolution becomes risky.
- The GUI code grew quickly and should be broken into smaller page/dialog modules.
- Income, expense, and debt deletion may leave unused schedule rows. This is harmless
  but should eventually be cleaned up transactionally.
- Some settings and reporting-currency edge cases still need consistency checks across every screen.
- Debt balance changes made through debt editing do not yet create a debt snapshot.
- Investment snapshots and a dedicated bulk investment-update workflow are incomplete.
- USD reporting requires a manually entered exchange rate, but there is no polished FX-rate UI yet.
- Existing warnings use deprecated `datetime.utcnow`; switch to timezone-aware UTC timestamps.
- Additional GUI interaction tests are needed beyond construction/smoke coverage.

## Recommended next steps

See `docs/PRODUCT_DIRECTION.md` for the current agreed roadmap. The immediate
proposal is to simplify ownership between Dashboard, Cash Flow, Outlook, and
Progress/Trends without losing any tracked card or credit values, then add the first
useful projected-cash and historical graphs.

## Key files

- `README.md` — installation and usage
- `docs/Private Personal Finance Tracker — Full Design & Implementation Specification.md` — authoritative product specification
- `docs/PRODUCT_DIRECTION.md` — current simplification decisions, open questions, and implementation checkpoints
- `finance_tracker/db/models.py` — schema
- `finance_tracker/services/` — calculations and projections
- `finance_tracker/ui/main_window.py` — shell and core pages
- `finance_tracker/ui/domain_pages.py` — initial domain dialogs/pages
- `finance_tracker/ui/management_pages.py` — editing/deletion and one-time events
- `tests/` — automated tests

