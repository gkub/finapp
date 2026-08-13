from PySide6.QtWidgets import QApplication
from finance_tracker.db.database import create_schema
from finance_tracker.ui.main_window import MainWindow


def test_main_window_constructs(engine):
    create_schema(engine)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Personal Finance Tracker"
    assert window.stack.count() == 10
    window.close()
