# Personal Finance Tracker — Home Computer Handoff

Use this document to resume work with Codex on another computer.

## Context to give Codex

> Continue implementing this personal finance tracker. Read `README.md`,
> `docs/HANDOFF.md`, and the full design specification in `docs/` first. Inspect
> the existing implementation and tests before changing anything. Preserve the
> local-only architecture, Decimal-safe calculations, native currencies,
> historical snapshots, and the distinction between operating cash, investments,
> debt, and net worth. Run the full test suite after changes.

## Current implementation

The project is a Python 3, PySide6, SQLAlchemy, and SQLite Linux desktop app.

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
- Account/debt snapshots and balance updates
- Investment accounts, holdings, manual prices, and valuation
- Operating-cash, investment, debt, and net-worth calculations
- Dashboard, Cash Flow, Accounts, Income, Recurring Expenses, Debts,
  One-Time Events, Investments, Update Finances, and Settings screens
- Add/edit/disable/delete workflows with confirmations and reference protection
- Local SQLite backup from Settings

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

Last verified state: `13 passed`, and all 10 navigation screens loaded in a
headless GUI check.

## Moving personal data

The database is not committed to Git. It normally lives at:

```text
~/.local/share/personal-finance-tracker/finance.db
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
- Settings are stored, but reporting currency, reserve, default horizon, and theme
  are not yet consistently consumed by every screen.
- Debt balance changes made through debt editing do not yet create a debt snapshot.
- Investment snapshots and a dedicated bulk investment-update workflow are incomplete.
- USD reporting requires a manually entered exchange rate, but there is no polished FX-rate UI yet.
- Existing warnings use deprecated `datetime.utcnow`; switch to timezone-aware UTC timestamps.
- Additional GUI interaction tests are needed beyond construction/smoke coverage.

## Recommended next steps

1. Add proper migrations and a schema-version bootstrap path.
2. Make all settings effective throughout services and screens.
3. Add a manual exchange-rate management screen.
4. Add debt and investment bulk-update workflows that always create snapshots.
5. Improve investment account totals and price history presentation.
6. Add forms for specific-date schedules and optional start/end dates.
7. Add repository/service tests for CRUD deletion, foreign-key protection, and snapshots.
8. Refactor the GUI into one module per domain page.
9. Add the projected cash-balance chart from the specification.

## Key files

- `README.md` — installation and usage
- `docs/Private Personal Finance Tracker — Full Design & Implementation Specification.md` — authoritative product specification
- `finance_tracker/db/models.py` — schema
- `finance_tracker/services/` — calculations and projections
- `finance_tracker/ui/main_window.py` — shell and core pages
- `finance_tracker/ui/domain_pages.py` — initial domain dialogs/pages
- `finance_tracker/ui/management_pages.py` — editing/deletion and one-time events
- `tests/` — automated tests

