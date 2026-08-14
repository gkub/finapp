#!/usr/bin/env bash
# Clone or fill ~/finance-data from gkub/finapp_db. Called by ./run.sh when needed.
set -euo pipefail

REMOTE="${FINAPP_DB_REMOTE:-git@github.com:gkub/finapp_db.git}"
DATA_DIR="${FINANCE_DATA_DIR:-$HOME/finance-data}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FINAPP_HOME="${FINAPP_HOME:-$(cd "$script_dir/.." && pwd)}"

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
  echo "Close the finance tracker before copying or cloning the database." >&2
  exit 1
fi

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    if [[ "$1" == sqlite3 ]]; then
      echo "Linux: sudo apt install sqlite3    macOS: already present, or brew install sqlite" >&2
    fi
    exit 1
  fi
}

need git
need sqlite3

echo "Remote:     $REMOTE"
echo "Data dir:   $DATA_DIR"
echo "Live DB:    $LIVE_DB"
echo "App home:   $FINAPP_HOME"

if [[ -d "$DATA_DIR/.git" ]]; then
  echo "Using existing clone at $DATA_DIR"
  git -C "$DATA_DIR" remote get-url origin >/dev/null
elif [[ -e "$DATA_DIR" && -n "$(ls -A "$DATA_DIR" 2>/dev/null)" ]]; then
  echo "$DATA_DIR exists and is not an empty git clone. Move it aside or set FINANCE_DATA_DIR." >&2
  exit 1
else
  git clone "$REMOTE" "$DATA_DIR"
fi

cd "$DATA_DIR"

if git rev-parse --verify HEAD >/dev/null 2>&1; then
  git pull --rebase
fi

cat > .gitignore <<'EOF'
*.db-wal
*.db-shm
*.db-journal
.DS_Store
EOF

if [[ -f finance.db ]]; then
  echo "Repo already has finance.db; leaving it in place."
elif [[ -f "$LIVE_DB" ]]; then
  echo "Checkpointing and copying live database into the repo."
  sqlite3 "$LIVE_DB" "PRAGMA wal_checkpoint(TRUNCATE);"
  cp "$LIVE_DB" finance.db
else
  echo "No database yet; the app will create one at $DATA_DIR/finance.db"
fi

git add .gitignore
if [[ -f finance.db ]]; then
  git add finance.db
fi

if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -m "Initial finance.db snapshot"
fi

if git rev-parse --verify HEAD >/dev/null 2>&1; then
  git branch -M main
  git push -u origin main
fi

echo
echo "Database ready at $DATA_DIR/finance.db"
echo "Only one computer should have the app open. Last push wins."
