from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from finance_tracker.db.database import default_database_path, dispose_engine


class SyncError(RuntimeError):
    pass


def sync_enabled() -> bool:
    return os.getenv("FINANCE_TRACKER_SYNC", "1") != "0"


def data_dir(database_path: Path | None = None) -> Path:
    return (database_path or default_database_path()).expanduser().resolve().parent


def is_git_work_tree(directory: Path) -> bool:
    return (directory / ".git").exists()


def pull_database(database_path: Path | None = None) -> str | None:
    """Preserve interrupted local work, then fetch remote DB before SQLite opens."""
    if not sync_enabled():
        return None
    path = (database_path or default_database_path()).expanduser()
    directory = path.parent
    if not is_git_work_tree(directory):
        return None
    recovery_warning = _commit_database(path, "recovered local snapshot before pull")
    if recovery_warning:
        return recovery_warning
    result = _git(["pull", "--rebase"], directory)
    if result.returncode == 0:
        return None
    detail = (result.stderr or result.stdout).strip() or "git pull failed"
    if _is_conflict(detail):
        raise SyncError(
            "Could not update finance.db from GitHub (conflict or diverged history). "
            "Close the app on the other computer, then fix ~/finance-data.\n\n"
            f"{detail}"
        )
    return f"Could not pull the database (using the local copy):\n{detail}"


def push_database(database_path: Path | None = None) -> str | None:
    """Checkpoint, commit, and push after the GUI closes."""
    if not sync_enabled():
        return None
    path = (database_path or default_database_path()).expanduser()
    directory = path.parent
    if not is_git_work_tree(directory) or not path.is_file():
        return None
    commit_warning = _commit_database(path)
    if commit_warning:
        return commit_warning
    pushed = _git(["push"], directory)
    if pushed.returncode != 0:
        return f"Could not push the database:\n{(pushed.stderr or pushed.stdout).strip()}"
    return None


def _commit_database(path: Path, message: str | None = None) -> str | None:
    """Checkpoint and commit only the database, preserving interrupted sessions."""
    if not path.is_file():
        return None
    directory = path.parent
    dispose_engine()
    connection = sqlite3.connect(str(path))
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    finally:
        connection.close()
    added = _git(["add", "--", path.name], directory)
    if added.returncode != 0:
        return f"Could not stage the database:\n{(added.stderr or added.stdout).strip()}"
    staged = _git(["diff", "--cached", "--quiet", "--", path.name], directory)
    if staged.returncode == 0:
        return None
    stamp = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    committed = _git(["commit", "-m", message or f"snapshot {stamp}"], directory)
    if committed.returncode != 0:
        return f"Could not commit the database:\n{(committed.stderr or committed.stdout).strip()}"
    return None


def _is_conflict(detail: str) -> bool:
    lowered = detail.lower()
    return any(token in lowered for token in ("conflict", "diverged", "unmerged", "needs merge"))


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            timeout=60, check=False,
        )
    except FileNotFoundError as exc:
        raise SyncError("git is not installed.") from exc
    except subprocess.TimeoutExpired as exc:
        raise SyncError(f"git {' '.join(args)} timed out.") from exc
