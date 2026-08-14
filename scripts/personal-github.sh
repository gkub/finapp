# Shared by run.sh and setup-db-repo.sh.
# On machines with two GitHub SSH hosts, personal finance must use gkub.

personal_github_host() {
  if [[ -f "${HOME}/.ssh/config" ]] \
    && grep -E -q '^[[:space:]]*Host[[:space:]]+github\.com-personal([[:space:]]|$)' \
      "${HOME}/.ssh/config"; then
    printf '%s\n' github.com-personal
  else
    printf '%s\n' github.com
  fi
}

personal_github_remote() {
  local repo="${1:?repo path under gkub}"
  printf 'git@%s:gkub/%s.git\n' "$(personal_github_host)" "$repo"
}

require_personal_github_ssh() {
  local host output
  host="$(personal_github_host)"
  output="$(ssh -o BatchMode=yes -o ConnectTimeout=8 -T "git@${host}" 2>&1 || true)"
  if ! grep -qi 'successfully authenticated' <<<"$output"; then
    echo "This computer cannot talk to GitHub over SSH yet as gkub." >&2
    echo "On a one-account machine:" >&2
    echo "  ssh-keygen -t ed25519 -C \"macbook\" -f ~/.ssh/id_ed25519 -N \"\"" >&2
    echo "  cat ~/.ssh/id_ed25519.pub" >&2
    echo "Add that public key at https://github.com/settings/keys then:" >&2
    echo "  ssh -T git@github.com" >&2
    echo "On a two-account machine, use Host github.com-personal in ~/.ssh/config" >&2
    echo "and: ssh -T git@github.com-personal" >&2
    echo "When that says Hi gkub, run ./run.sh again." >&2
    exit 1
  fi
  if ! grep -q 'Hi gkub!' <<<"$output"; then
    echo "GitHub SSH authenticated as the wrong account (need gkub):" >&2
    echo "  $output" >&2
    echo "This project must not use a work GitHub account." >&2
    echo "Use git@github.com-personal (IdentityFile ~/.ssh/id_rsa_personal)." >&2
    exit 1
  fi
}

use_personal_git_identity() {
  local repo="${1:?git repo}"
  local name email
  name="$(git -C "$FINAPP_HOME" config --local --get user.name || true)"
  email="$(git -C "$FINAPP_HOME" config --local --get user.email || true)"
  if [[ -z "$name" || -z "$email" ]]; then
    echo "Set a personal git identity in $FINAPP_HOME first:" >&2
    echo "  git -C \"$FINAPP_HOME\" config --local user.name gkub" >&2
    echo "  git -C \"$FINAPP_HOME\" config --local user.email YOUR_PERSONAL_EMAIL" >&2
    exit 1
  fi
  git -C "$repo" config --local user.name "$name"
  git -C "$repo" config --local user.email "$email"
}
