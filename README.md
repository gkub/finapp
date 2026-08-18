# Personal Finance Tracker

Local desktop app for cash flow, accounts, debts, bills, investments, and net
worth. Runs on Linux and macOS. The application source and each user’s financial
database are intentionally separate.

## Everyday use

```bash
cd ~/Code/finapp
./run.sh
```

The first run installs Python dependencies and asks how to store data. Later runs
open the app directly. When private GitHub sync is enabled, opening pulls the
latest database and closing commits and pushes it.

## Current highlights

- Spending estimates from periodic balance updates, with optional broad check-ins
- Credit limits, available credit, utilization, and projections that stop at $0 owed
- PayPal-style primary and backup account funding
- Dark, light, and accessible pastel-pink themes in Settings
- Signed account balances, overdraft limits, and overdraft interest rates

For useful spending estimates, use **Update Finances** periodically. The app
reconciles the change between two balance snapshots against known income, bills,
and card activity; individual purchase entry remains optional.

> Only open a synced database on one computer at a time. SQLite database commits
> do not merge; if two computers edit concurrently, the last push can conflict.

## Share with another person

### Before she starts

Give her access to this application repository (add her as a GitHub collaborator
if it is private). Do **not** give her access to your `finapp_db` repository.
Every user should own a separate private database repository.

### Her one-time setup

Linux requirements:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv sqlite3
```

macOS requirements: install Apple command-line tools with
`xcode-select --install`. If Python is older than 3.11, install a current Python
with Homebrew.

Clone and run:

```bash
git clone git@github.com:gkub/finapp.git ~/Code/finapp
cd ~/Code/finapp
./run.sh
```

On first run she chooses:

1. **Private GitHub sync (recommended):** if authenticated GitHub CLI (`gh`) is
   available, setup offers to create her private `finapp_db` automatically.
2. **Manual private repo:** without `gh`, setup explains how to create one empty
   private GitHub repo and asks for its SSH URL, commit name, and email.
3. **Local only:** no GitHub database repo or sync; data stays on that computer.

Her choice is saved to `.finapp.env`, which is mode `600` and ignored by Git.
It contains configuration—not financial data or GitHub tokens.

### Optional: install GitHub CLI for the most automated setup

Follow the official package instructions for the platform, then authenticate:

```bash
gh auth login
```

After that, `./run.sh` can create the private database repository for her. GitHub
CLI is optional; manually creating an empty private repo works just as well.

### Change the storage choice later

Close the app, then run:

```bash
./scripts/configure.sh --force
```

If changing from local-only to sync, the setup copies the existing standard
local database into the new private repository when possible.

## Database locations

Private GitHub sync:

```text
~/finance-data/finance.db
```

Local-only Linux:

```text
~/.local/share/personal-finance-tracker/finance.db
```

Local-only macOS:

```text
~/Library/Application Support/personal-finance-tracker/finance.db
```

The app repository ignores `.finapp.env`, SQLite files, sidecars, and backups.
The private data repository ignores SQLite WAL/journal sidecars.

## SSH troubleshooting

Verify GitHub access on the new computer:

```bash
ssh -T git@github.com
```

If multiple GitHub accounts use SSH aliases, paste the appropriate aliased URL
during manual setup, for example:

```text
git@github.com-personal:USERNAME/finapp_db.git
```

## Updating

```bash
cd ~/Code/finapp
git pull
./run.sh
```

`run.sh` reinstalls the editable package when `pyproject.toml` changes.

## Tests

```bash
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  env -u __PYVENV_LAUNCHER__ .venv/bin/python -m pytest tests -q
```

## Privacy

No telemetry or bank login is used. Market and FX lookup are optional. A database
repository contains highly sensitive financial information: keep it private,
never reuse another person’s data repository, and do not add collaborators unless
they should see all of that financial data.

The specification, development handoff, and [fresh Mac setup guide](docs/MAC_SETUP.md)
are in `docs/`.
