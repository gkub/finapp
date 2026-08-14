# Personal Finance Tracker

Local desktop app for cash flow, accounts, debts, bills, investments, and net
worth. Runs on Linux and macOS. This repo is source only — `finance.db` never
goes here. Money data lives in the private repo `gkub/finapp_db`.

## Run

```bash
cd ~/Code/finapp
./run.sh
```

That is the whole daily loop. First time it creates the Python env and clones
the private database if needed. Closing the window pulls/pushes the DB. Only
one computer should have the app open.

## New computer

Python 3.11+, git, and SSH to GitHub (`ssh -T git@github.com`).

```bash
git clone git@github.com:gkub/finapp.git ~/Code/finapp
cd ~/Code/finapp
./run.sh
```

Linux extras: `sudo apt install python3 python3-venv sqlite3` (and on a bare
system maybe `libegl1 libgl1 libxkbcommon-x11-0`). WSL2 needs WSLg / a GUI
session.

macOS: if `python3 --version` is older than 3.11, `brew install python`. Launch
from Terminal.app, not a headless SSH session.

## Tests

```bash
./run.sh  # once, so .venv exists
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests -q
```

## Privacy

No telemetry, bank login, or required cloud. Optional quotes/FX. Keep backups
private. Specs are in `docs/`.
