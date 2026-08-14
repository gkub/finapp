#!/usr/bin/env bash
# From the repo: ./run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

pick_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3 \
      /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
        >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "Need Python 3.11+." >&2
  if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
    echo "Installing it with Homebrew…" >&2
    brew install python
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
      if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
          >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done
  fi
  echo "Linux: sudo apt install python3 python3-venv" >&2
  echo "macOS: brew install python" >&2
  exit 1
}

PYTHON="$(pick_python)"

need_github_ssh() {
  local output
  output="$(ssh -o BatchMode=yes -o ConnectTimeout=8 -T git@github.com 2>&1 || true)"
  if ! grep -qi 'successfully authenticated' <<<"$output"; then
    echo "This computer cannot talk to GitHub over SSH yet. A key on Linux does not exist on the Mac until you add one here." >&2
    echo "In Terminal:" >&2
    echo "  ssh-keygen -t ed25519 -C \"macbook\" -f ~/.ssh/id_ed25519 -N \"\"" >&2
    echo "  cat ~/.ssh/id_ed25519.pub" >&2
    echo "Add that public key at https://github.com/settings/keys then:" >&2
    echo "  ssh -T git@github.com" >&2
    echo "When that says Hi gkub, run ./run.sh again." >&2
    exit 1
  fi
}

if [[ ! -x .venv/bin/python ]]; then
  "$PYTHON" -m venv .venv
fi

if [[ ! -x .venv/bin/finance-tracker || pyproject.toml -nt .venv/bin/finance-tracker ]]; then
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e '.[desktop,dev]'
fi

if [[ ! -d "${FINANCE_DATA_DIR:-$HOME/finance-data}/.git" ]]; then
  need_github_ssh
  bash "$ROOT/scripts/setup-db-repo.sh"
fi

export FINANCE_TRACKER_DB_PATH="${FINANCE_TRACKER_DB_PATH:-${FINANCE_DATA_DIR:-$HOME/finance-data}/finance.db}"
exec env -u __PYVENV_LAUNCHER__ "$ROOT/.venv/bin/finance-tracker"
