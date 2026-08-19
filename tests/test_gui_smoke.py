from decimal import Decimal

from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QHeaderView, QPushButton, QTableWidget
from finance_tracker.db.database import create_schema
from finance_tracker.ui.domain_pages import DebtDialog, configure_table, fit_table_columns
from finance_tracker.ui.main_window import (
    AccountDialog, Accounts, CashFlow, Dashboard, MainWindow, MetricGroup, UpdateFinances, _funding_display,
)
from finance_tracker.ui.management_pages import ManagedDebtPage
from finance_tracker.ui.outlook_page import Outlook
from finance_tracker.ui.progress_page import TrendsPage


def test_main_window_constructs(engine):
    create_schema(engine)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Personal Finance Tracker"
    assert window.stack.count() == 15
    assert "Outlook" in [button.text() for button in window.buttons]
    assert "Trends" in [button.text() for button in window.buttons]
    assert "Deposits" in [button.text() for button in window.buttons]
    assert "Assets" in [button.text() for button in window.buttons]
    window.close()


def test_table_columns_fit_header_text():
    app = QApplication.instance() or QApplication([])
    table = QTableWidget(0, 6)
    table.setHorizontalHeaderLabels(["Name", "Type", "Balance", "Overdraft limit", "Rate", "Headroom"])
    configure_table(table)
    table.resize(1000, 240)
    table.show()
    app.processEvents()
    fit_table_columns(table)
    header = table.horizontalHeader()
    assert header.stretchLastSection() is False
    assert header.sectionResizeMode(0) != QHeaderView.ResizeMode.Stretch
    assert table.columnWidth(3) > table.columnWidth(0)
    assert table.columnWidth(3) >= header.fontMetrics().horizontalAdvance("Overdraft limit")
    table.close()


def test_account_dialog_omits_credit_card_and_overdraft_for_savings():
    app = QApplication.instance() or QApplication([])
    dialog = AccountDialog()
    types = [dialog.kind.itemText(i) for i in range(dialog.kind.count())]
    assert types == ["checking", "savings", "cash", "digital_wallet", "other"]
    assert dialog.purpose.currentData() == "personal"
    dialog.purpose.setCurrentIndex(dialog.purpose.findData("business"))
    assert dialog.cash.isChecked() is False
    dialog.name.setText("TFSA cash")
    dialog.kind.setCurrentText("savings")
    dialog.limit.setValue(500)
    dialog.rate.setValue(19.99)
    values = dialog.values()
    assert values["overdraft_limit"] is None
    assert values["overdraft_interest_rate"] is None
    dialog.kind.setCurrentText("checking")
    values = dialog.values()
    assert values["overdraft_limit"] == Decimal("500")
    assert values["overdraft_interest_rate"] is not None
    dialog.close()


def test_accounts_page_uses_toolbar_not_cell_buttons(engine):
    create_schema(engine)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = next(item for item in window.pages if isinstance(item, Accounts))
    assert page.table.columnCount() == 7
    labels = [child.text() for child in page.findChildren(QPushButton)]
    assert "Edit" in labels
    assert "Delete" in labels
    for row in range(page.table.rowCount()):
        for col in range(page.table.columnCount()):
            assert page.table.cellWidget(row, col) is None
    window.close()


def test_debt_dialog_monthly_rate_converts_to_annual(engine):
    app = QApplication.instance() or QApplication([])
    dialog = DebtDialog()
    dialog.rate_period.setCurrentText("per month")
    dialog.rate.setValue(0.5)
    assert dialog.annual_rate() == Decimal("0.06")
    dialog.set_annual_rate(Decimal("0.0699"))
    assert dialog.rate_period.currentText() == "per year"
    assert abs(dialog.rate.value() - 6.99) < 0.0001
    dialog.rate_period.setCurrentText("per month")
    assert abs(dialog.rate.value() - 6.99 / 12) < 0.0001
    dialog.close()


def test_debts_page_has_pay_down_and_scheduled_payment(engine):
    create_schema(engine)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    page = next(item for item in window.pages if isinstance(item, ManagedDebtPage))
    labels = [child.text() for child in page.findChildren(QPushButton)]
    assert "Pay down" in labels
    headers = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
    assert {"Available", "Used", "Scheduled"} <= set(headers)
    dialog = DebtDialog()
    assert "Optional" in dialog.payment.toolTip()
    dialog.close()
    window.close()


def test_update_finances_lists_new_amount_not_mystery_interest():
    app = QApplication.instance() or QApplication([])
    page = UpdateFinances()
    headers = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
    assert headers == ["Type", "Name", "On file", "New amount", "Note"]
    field = page._amount_field(Decimal("-268.72"))
    assert field.minimumHeight() >= 36
    assert field.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
    page.close()


def test_analytical_pages_have_distinct_ownership(engine):
    create_schema(engine)
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    dashboard = next(item for item in window.pages if isinstance(item, Dashboard))
    assert dashboard.table.columnCount() == 4
    assert set(dashboard.cards) == {
        "cash", "safe", "low", "cards", "available", "utilization",
        "debt", "net", "investments", "material",
    }

    cash_flow = next(item for item in window.pages if isinstance(item, CashFlow))
    assert cash_flow.table.columnCount() == 12
    assert cash_flow.purpose_filter.itemText(0) == "All"
    assert set(cash_flow.type_filters) == {"income", "bills", "cards", "debt", "transfers"}

    outlook = next(item for item in window.pages if isinstance(item, Outlook))
    assert [outlook.tabs.tabText(i) for i in range(outlook.tabs.count())] == ["Scenario", "Scheduled debt"]
    assert outlook.forecast_table.columnCount() == 4
    assert outlook.debt_table.columnCount() == 6

    trends = next(item for item in window.pages if isinstance(item, TrendsPage))
    assert trends.history_table.columnCount() == 10
    assert not hasattr(trends, "forecast_table")
    window.close()


def test_metric_group_reflows_and_funding_labels_drop_zero_backup():
    app = QApplication.instance() or QApplication([])
    group = MetricGroup("Credit", (
        ("one", "One"), ("two", "Two"), ("three", "Three"), ("four", "Four"),
    ), 4)
    group.resize(660, 240)
    group.show()
    app.processEvents()
    assert group._columns == 2
    group.resize(1000, 240)
    app.processEvents()
    assert group._columns == 4
    assert _funding_display("gkub_paypal 22.04; chequing_td 0.00", "CAD") == "gkub paypal $22.04"
    assert _funding_display("gkub_paypal 0.59; chequing_td 6.75", "CAD") == (
        "gkub paypal $0.59 -> chequing td $6.75"
    )
    group.close()


def test_dashboard_uses_responsive_parent_groups_and_stretching_preview(engine):
    create_schema(engine)
    app = QApplication.instance() or QApplication([])
    dashboard = Dashboard()
    dashboard.resize(1500, 800)
    dashboard.show()
    app.processEvents()
    assert dashboard._wide_layout is True
    dashboard.resize(1000, 800)
    app.processEvents()
    assert dashboard._wide_layout is False
    assert dashboard.cash_group.objectName() == "metricGroup"
    assert dashboard.table.horizontalHeader().sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
    assert dashboard.table.horizontalHeader().sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch
    dashboard.close()
