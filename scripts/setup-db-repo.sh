#!/usr/bin/env bash
# Clone or initialize the private DB repository selected during onboarding.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FINAPP_HOME="${FINAPP_HOME:-$(cd "$script_dir/.." && pwd)}"
if [[ -f "$FINAPP_HOME/.finapp.env" ]]; then
  # shellcheck disable=SC1091
  source "$FINAPP_HOME/.finapp.env"
fi
REMOTE="${FINAPP_DB_REMOTE:-}"
DATA_DIR="${FINANCE_DATA_DIR:-$HOME/finance-data}"

if [[ -z "$REMOTE" ]]; then
  echo "No private database remote is configured." >&2
  echo "Run: $FINAPP_HOME/scripts/configure.sh --force" >&2
  exit 1
fi

os_default_db() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    printf '%s\n' "$HOME/Library/Application Support/personal-finance-tracker/finance.db"
  else
    printf '%s\n' "${XDG_DATA_HOME:-$HOME/.local/share}/personal-finance-tracker/finance.db"
  fi
}

LIVE_DB="$(os_default_db)"
if [[ -n "${FINANCE_TRACKER_DB_PATH:-}" && -f "${FINANCE_TRACKER_DB_PATH}" ]]; then
  case "${FINANCE_TRACKER_DB_PATH}" in
    "$DATA_DIR"/finance.db) ;;
    *) LIVE_DB="${FINANCE_TRACKER_DB_PATH}" ;;
  esac
fi

if pgrep -f 'finance_tracker\.app|[.]venv/bin/finance-tracker' >/dev/null 2>&1; then
  echo "Close the finance tracker before setting up the database." >&2
  exit 1
fi
for command in git sqlite3; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing command: $command" >&2
    echo "Linux: sudo apt install git sqlite3" >&2
    exit 1
  fi
done

echo "Remote:   $REMOTE"
echo "Data dir: $DATA_DIR"
if [[ -d "$DATA_DIR/.git" ]]; then
  echo "Using existing clone at $DATA_DIR"
  current="$(git -C "$DATA_DIR" remote get-url origin)"
  if [[ "$current" != "$REMOTE" ]]; then
    echo "$DATA_DIR points to a different database remote: $current" >&2
    echo "Move it aside or set FINANCE_DATA_DIR to a new directory." >&2
    exit 1
  fi
elif [[ -e "$DATA_DIR" && -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]]; then
  echo "$DATA_DIR exists and is not empty. Move it aside or set FINANCE_DATA_DIR." >&2
  exit 1
else
  git clone "$REMOTE" "$DATA_DIR"
fi

cd "$DATA_DIR"
if [[ -n "${FINAPP_GIT_NAME:-}" ]]; then
  git config --local user.name "$FINAPP_GIT_NAME"
fi
if [[ -n "${FINAPP_GIT_EMAIL:-}" ]]; then
  git config --local user.email "$FINAPP_GIT_EMAIL"
fi
if [[ -z "$(git config --get user.name || true)" || -z "$(git config --get user.email || true)" ]]; then
  echo "Git needs a name and email for database snapshots." >&2
  echo "Rerun $FINAPP_HOME/scripts/configure.sh --force and provide them." >&2
  exit 1
fi

if git rev-parse --verify HEAD >/dev/null 2>&1; then
  git pull --rebase
fi

printf '%s\n' '*.db-wal' '*.db-shm' '*.db-journal' '.DS_Store' > .gitignore
if [[ -f finance.db ]]; then
  echo "The private repo already contains finance.db."
elif [[ -f "$LIVE_DB" ]]; then
  echo "Copying the existing local database into the private repo."
  sqlite3 "$LIVE_DB" "PRAGMA wal_checkpoint(TRUNCATE);"
  cp "$LIVE_DB" finance.db
else
  echo "No existing database; the app will create one."
fi

git add .gitignore
[[ ! -f finance.db ]] || git add finance.db
if ! git diff --cached --quiet; then
  git commit -m "Initial finance database"
fi
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  git branch -M main
  git push -u origin main
fi

echo
echo "Database ready at $DATA_DIR/finance.db"
echo "Only one computer should have the app open. Last push wins."
