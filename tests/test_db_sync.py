import sqlite3
import subprocess
from pathlib import Path

from finance_tracker.services import db_sync


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo_with_db(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    data = tmp_path / "data"
    subprocess.run(["git", "clone", str(remote), str(data)], check=True, capture_output=True)
    _git(data, "config", "user.email", "test@example.com")
    _git(data, "config", "user.name", "Test")
    connection = sqlite3.connect(data / "finance.db")
    connection.execute("CREATE TABLE ping (n INTEGER)")
    connection.commit()
    connection.close()
    _git(data, "add", "finance.db")
    _git(data, "commit", "-m", "init")
    _git(data, "branch", "-M", "main")
    _git(data, "push", "-u", "origin", "main")
    subprocess.run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote, check=True, capture_output=True)
    return data


def test_pull_and_push_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("FINANCE_TRACKER_SYNC", raising=False)
    data = _repo_with_db(tmp_path)
    db = data / "finance.db"
    assert db_sync.pull_database(db) is None
    connection = sqlite3.connect(db)
    connection.execute("INSERT INTO ping VALUES (1)")
    connection.commit()
    connection.close()
    assert db_sync.push_database(db) is None
    clone = tmp_path / "other"
    subprocess.run(["git", "clone", str(tmp_path / "remote.git"), str(clone)], check=True, capture_output=True)
    copied = sqlite3.connect(clone / "finance.db")
    assert copied.execute("SELECT n FROM ping").fetchall() == [(1,)]
    copied.close()


def test_pull_skipped_when_sync_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("FINANCE_TRACKER_SYNC", "0")
    data = _repo_with_db(tmp_path)
    assert db_sync.pull_database(data / "finance.db") is None
