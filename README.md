# Personal Finance Tracker

A private, local-only Linux desktop application for tracking cash flow, accounts,
debts, recurring bills, investments, and net worth. Financial data is stored in
a local SQLite database and no internet connection is required.

The full product specification and computer-to-computer development handoff are in `docs/`.

## Features currently available

- Dashboard with operating cash, investments, debt, net worth, projected minimum balance, and safe-to-spend
- Negative balances, overdraft limits, and overdraft interest rates
- Exact weekly, biweekly, monthly, and yearly income/expense schedules
- Debts, one-time events, TFSA/FHSA/RRSP accounts, holdings, and manual CAD/USD prices
- Cash-flow projections, dated snapshots, local backups, editing, disabling, and confirmed deletion

## Install on another computer

These instructions target Debian, Ubuntu, Linux Mint, Pop!_OS, and related distributions.

### 1. Install system requirements

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
```

PySide6 installed through `pip` bundles Qt. A particularly minimal installation may also need:

```bash
sudo apt install -y libegl1 libgl1 libxkbcommon-x11-0
```

### 2. Download the project

After pushing this directory to a Git repository:

```bash
git clone YOUR_REPOSITORY_URL finapp
cd finapp
```

Alternatively, copy the directory to the other computer. Do not copy `.venv`; recreate it below.

### 3. Create the environment and install

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[desktop,dev]'
```

### 4. Launch

```bash
.venv/bin/finance-tracker
```

If Cursor reports that `PySide6` cannot be found, use:

```bash
env -u __PYVENV_LAUNCHER__ .venv/bin/finance-tracker
```

The database is created automatically on first launch.

## Run the tests

```bash
env -u __PYVENV_LAUNCHER__ QT_QPA_PLATFORM=offscreen .venv/bin/pytest
```

## Data location and migration

Data is stored at:

```text
~/.local/share/personal-finance-tracker/finance.db
```

To move existing data to another computer:

1. Close the application on both computers.
2. Use **Settings → Back up database** on the old computer.
3. Install and launch once on the new computer, then close it.
4. Copy the backup to `~/.local/share/personal-finance-tracker/finance.db`.
5. Launch again.

Keep backups private: they contain your financial information. Database files are ignored by Git.

For an isolated database:

```bash
FINANCE_TRACKER_DB_PATH=/absolute/path/test-finance.db .venv/bin/finance-tracker
```

## Updating

```bash
git pull
.venv/bin/python -m pip install -e '.[desktop,dev]'
env -u __PYVENV_LAUNCHER__ .venv/bin/finance-tracker
```

## Troubleshooting

### `No module named PySide6`

```bash
env -u __PYVENV_LAUNCHER__ .venv/bin/python -c 'import PySide6; print(PySide6.__version__)'
env -u __PYVENV_LAUNCHER__ .venv/bin/python -m pip install -e '.[desktop,dev]'
```

### Qt platform plugin or display error

Launch from a graphical Linux desktop session and install the optional runtime libraries in step 1.

### Temporary empty database

Do not delete your real database unless it is backed up. For a clean temporary database:

```bash
FINANCE_TRACKER_DB_PATH=/tmp/finance-tracker-test.db .venv/bin/finance-tracker
```

## Privacy

There is no telemetry, cloud synchronization, bank login, or required network integration. Core data remains in local SQLite.
