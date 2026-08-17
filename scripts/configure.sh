#!/usr/bin/env bash
# Interactive first-run configuration. Safe to rerun with --force.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/.finapp.env"

if [[ -f "$CONFIG" && "${1:-}" != "--force" ]]; then
  echo "Finapp is already configured in $CONFIG"
  echo "Run scripts/configure.sh --force to change it."
  exit 0
fi
if [[ ! -t 0 ]]; then
  echo "First-run setup needs an interactive terminal." >&2
  echo "Run: ./scripts/configure.sh" >&2
  exit 1
fi

echo
echo "Finapp first-run setup"
echo "======================"
echo "1) Private GitHub sync (recommended for multiple computers)"
echo "2) Local only"
read -r -p "Choose [1]: " mode
mode="${mode:-1}"

write_config() {
  umask 077
  {
    printf 'FINAPP_SYNC_MODE=%q\n' "$1"
    [[ -z "${2:-}" ]] || printf 'FINAPP_DB_REMOTE=%q\n' "$2"
    [[ -z "${3:-}" ]] || printf 'FINAPP_GIT_NAME=%q\n' "$3"
    [[ -z "${4:-}" ]] || printf 'FINAPP_GIT_EMAIL=%q\n' "$4"
  } > "$CONFIG"
  chmod 600 "$CONFIG"
}

if [[ "$mode" == "2" ]]; then
  write_config local
  echo
  echo "Configured for local-only storage. Run ./run.sh"
  exit 0
fi
if [[ "$mode" != "1" ]]; then
  echo "Invalid choice." >&2
  exit 1
fi

remote=""
git_name=""
git_email=""
if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  login="$(gh api user --jq .login)"
  account_id="$(gh api user --jq .id)"
  git_name="$(gh api user --jq '.name // .login')"
  git_email="${account_id}+${login}@users.noreply.github.com"
  read -r -p "Private database repository [${login}/finapp_db]: " repo
  repo="${repo:-${login}/finapp_db}"
  if ! gh repo view "$repo" >/dev/null 2>&1; then
    echo "Creating private GitHub repository $repo…"
    gh repo create "$repo" --private --disable-issues --disable-wiki
  fi
  remote="git@github.com:${repo}.git"
else
  echo
  echo "Create an EMPTY private repository at https://github.com/new"
  echo "Suggested name: finapp_db"
  echo "Visibility: Private"
  echo "Do not add a README, license, or .gitignore."
  echo
  read -r -p "Paste its SSH URL (git@github.com:YOU/finapp_db.git): " remote
  read -r -p "Git commit name: " git_name
  read -r -p "Git commit email (GitHub noreply recommended): " git_email
fi

if [[ ! "$remote" =~ ^git@[^:]+:.+/.+\.git$ ]]; then
  echo "Expected an SSH URL such as git@github.com:you/finapp_db.git" >&2
  exit 1
fi
echo "Checking access to $remote…"
if ! git ls-remote "$remote" >/dev/null; then
  echo "Cannot access that repository over SSH." >&2
  echo "Confirm the URL and run: ssh -T git@github.com" >&2
  exit 1
fi

write_config github "$remote" "$git_name" "$git_email"
echo
echo "Private sync configured. Run ./run.sh"
echo "Configuration: $CONFIG (mode 600, never committed)"
