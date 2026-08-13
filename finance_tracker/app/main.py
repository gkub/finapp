from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from finance_tracker.db.database import create_schema, session_scope
from finance_tracker.db.seed import ensure_defaults
from finance_tracker.ui.main_window import MainWindow


def main() -> int:
    """Initialize local storage and launch the desktop application."""
    create_schema()
    with session_scope() as session:
        ensure_defaults(session)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Personal Finance Tracker")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

