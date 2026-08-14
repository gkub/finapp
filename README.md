# Personal Finance Tracker

Local desktop app for cash flow, accounts, debts, bills, investments, and net
worth. Runs on Linux and macOS. This repo is source only — `finance.db` never
goes here. Money data lives in the private repo `gkub/finapp_db`.

## Run (every time, either computer)

```bash
cd ~/Code/finapp
./run.sh
```

Closing the window syncs the database. Only one computer should have the app
open.

## New computer (Mac included)

Same three commands as Linux. `./run.sh` creates the Python env and clones the
private DB. You do not run a second setup script.

**Once on the Mac**, GitHub SSH has to work *on that laptop* (Linux keys do not
travel with the machine):

```bash
ssh -T git@github.com
```

That must print `Hi gkub`. If it does not:

```bash
ssh-keygen -t ed25519 -C "macbook" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Add the printed line at https://github.com/settings/keys then retry `ssh -T`.

Then:

```bash
git clone git@github.com:gkub/finapp.git ~/Code/finapp
cd ~/Code/finapp
./run.sh
```

Use Terminal.app, not SSH into the Mac. If `git` is missing:
`xcode-select --install`. If Python is old and Homebrew exists, `./run.sh`
installs a current Python itself.

Linux extras if a package is missing:
`sudo apt install python3 python3-venv sqlite3 git`. WSL2 needs a GUI session.

## Tests

```bash
./run.sh
QT_QPA_PLATFORM=offscreen PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests -q
```

## Privacy

No telemetry, bank login, or required cloud. Optional quotes/FX. Keep backups
private. Specs are in `docs/`.
