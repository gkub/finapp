from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from finance_tracker.db.database import create_schema, session_scope
from finance_tracker.db.seed import ensure_defaults
from finance_tracker.services.db_sync import SyncError, pull_database, push_database
from finance_tracker.ui.main_window import MainWindow


def main() -> int:
    """Initialize local storage and launch the desktop application."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Personal Finance Tracker")
    try:
        pull_warning = pull_database()
    except SyncError as exc:
        QMessageBox.critical(None, "Database sync failed", str(exc))
        return 1
    if pull_warning:
        QMessageBox.warning(None, "Database sync", pull_warning)
    create_schema()
    with session_scope() as session:
        ensure_defaults(session)
    window = MainWindow()
    window.show()

    def _sync_on_quit() -> None:
        try:
            push_warning = push_database()
        except SyncError as exc:
            QMessageBox.warning(None, "Database sync", str(exc))
            return
        if push_warning:
            QMessageBox.warning(None, "Database sync", push_warning)

    app.aboutToQuit.connect(_sync_on_quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
