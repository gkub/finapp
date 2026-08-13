from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import Account
from finance_tracker.services.balance_service import (
    current_balance_sheet, estimated_overdraft_interest, overdraft_headroom,
    update_account_balance,
)
from finance_tracker.services.projection_service import (
    committed_cash, generate_events, lowest_projected_balance, project,
    safe_to_spend,
)
from finance_tracker.utils.money import format_money
from finance_tracker.ui.domain_pages import SettingsPage
from finance_tracker.ui.management_pages import (
    EventPage, InvestmentManagementPage, ManagedDebtPage, ManagedExpensePage,
    ManagedIncomePage,
)

STYLE = """
QWidget { background:#11151c; color:#e8edf5; font-size:14px; }
QFrame#sidebar { background:#171c25; border-right:1px solid #293140; }
QLabel#brand { font-size:20px; font-weight:700; padding:8px; }
QLabel#title { font-size:28px; font-weight:700; }
QLabel#muted { color:#93a0b3; }
QPushButton { background:#242c39; border:1px solid #354154; border-radius:7px; padding:8px 14px; }
QPushButton:hover { background:#2d3747; }
QPushButton#primary { background:#3d7eff; border-color:#3d7eff; font-weight:600; }
QPushButton#nav { text-align:left; border:none; background:transparent; padding:10px 14px; }
QPushButton#nav:checked { background:#263650; color:#78a7ff; border-left:3px solid #4d8aff; }
QFrame#card { background:#1a202a; border:1px solid #293241; border-radius:10px; }
QLabel#metric { font-size:23px; font-weight:700; }
QLineEdit,QComboBox,QDoubleSpinBox,QDateEdit { background:#171c25; border:1px solid #354154; border-radius:6px; padding:7px; }
QTableWidget { background:#171c25; alternate-background-color:#1b222d; border:1px solid #293241; gridline-color:#293241; }
QHeaderView::section { background:#202733; color:#b9c4d4; border:none; padding:8px; font-weight:600; }
"""


class Card(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        box = QVBoxLayout(self)
        label = QLabel(title)
        label.setObjectName("muted")
        self.value = QLabel("—")
        self.value.setObjectName("metric")
        box.addWidget(label)
        box.addWidget(self.value)


def page_layout(widget, title, subtitle=""):
    box = QVBoxLayout(widget)
    box.setContentsMargins(28, 24, 28, 24)
    box.setSpacing(16)
    label = QLabel(title)
    label.setObjectName("title")
    box.addWidget(label)
    if subtitle:
        note = QLabel(subtitle)
        note.setObjectName("muted")
        box.addWidget(note)
    return box


class Dashboard(QWidget):
    def __init__(self):
        super().__init__()
        box = page_layout(self, "Dashboard", "Your cash position and balance sheet at a glance.")
        grid = QGridLayout()
        self.cards = {}
        for i, (key, label) in enumerate((
            ("cash", "Operating cash"), ("investments", "Investments"),
            ("debt", "Total debt"), ("net", "Net worth"),
            ("low", "30-day minimum"), ("safe", "Safe to spend"),
        )):
            self.cards[key] = Card(label)
            grid.addWidget(self.cards[key], i // 3, i % 3)
        box.addLayout(grid)
        box.addWidget(QLabel("Upcoming 30 days"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Description", "Amount", "Projected balance"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        box.addWidget(self.table, 1)

    def refresh(self):
        try:
            with session_scope() as session:
                sheet = current_balance_sheet(session)
                events = generate_events(session, date.today(), date.today() + timedelta(days=30))
                rows = project(sheet.operating_cash, events)
                values = {
                    "cash": sheet.operating_cash, "investments": sheet.investments,
                    "debt": sheet.debts, "net": sheet.net_worth,
                    "low": lowest_projected_balance(sheet.operating_cash, events),
                    "safe": safe_to_spend(sheet.operating_cash, events, Decimal("0")),
                }
                for key, value in values.items():
                    self.cards[key].value.setText(format_money(value))
                self.table.setRowCount(len(rows))
                for row, event in enumerate(rows):
                    for col, value in enumerate((
                        event.date.isoformat(), event.description,
                        format_money(event.reporting_amount), format_money(event.running_balance),
                    )):
                        self.table.setItem(row, col, QTableWidgetItem(value))
        except Exception as exc:
            for card in self.cards.values():
                card.value.setText("Unavailable")
            self.table.setToolTip(str(exc))


class AccountDialog(QDialog):
    def __init__(self, account=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit account" if account else "Add account")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.name = QLineEdit(account.name if account else "")
        self.kind = QComboBox()
        self.kind.addItems(["checking", "savings", "cash", "credit_card", "other"])
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.balance = self.money_spin(-999999999, 999999999)
        self.limit = self.money_spin(0, 999999999)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 999)
        self.rate.setDecimals(3)
        self.rate.setSuffix(" %")
        self.cash = QCheckBox()
        self.net = QCheckBox()
        self.cash.setChecked(True if account is None else account.include_in_cash)
        self.net.setChecked(True if account is None else account.include_in_net_worth)
        if account:
            self.kind.setCurrentText(account.account_type)
            self.currency.setCurrentText(account.currency)
            self.balance.setValue(float(account.current_balance))
            self.limit.setValue(float(account.overdraft_limit or 0))
            self.rate.setValue(float((account.overdraft_interest_rate or 0) * 100))
        for label, field in (
            ("Name", self.name), ("Type", self.kind), ("Currency", self.currency),
            ("Current balance", self.balance), ("Overdraft limit", self.limit),
            ("Overdraft annual rate", self.rate), ("Include in operating cash", self.cash),
            ("Include in net worth", self.net),
        ):
            form.addRow(label, field)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @staticmethod
    def money_spin(low, high):
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setDecimals(2)
        field.setPrefix("$ ")
        field.setGroupSeparatorShown(True)
        return field

    def validate(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name required", "Enter an account name.")
            return
        if self.limit.value() and self.balance.value() < -self.limit.value():
            QMessageBox.warning(self, "Overdraft exceeded", "The balance exceeds the entered overdraft limit.")
            return
        self.accept()

    def values(self):
        rate = Decimal(str(self.rate.value())) / Decimal("100") if self.rate.value() else None
        return dict(
            name=self.name.text().strip(), account_type=self.kind.currentText(),
            currency=self.currency.currentText(), current_balance=Decimal(str(self.balance.value())),
            overdraft_limit=Decimal(str(self.limit.value())) if self.limit.value() else None,
            overdraft_interest_rate=rate, include_in_cash=self.cash.isChecked(),
            include_in_net_worth=self.net.isChecked(),
        )


class Accounts(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = page_layout(self, "Accounts", "Negative balances, overdraft limits, and overdraft rates are supported.")
        controls = QHBoxLayout()
        controls.addStretch()
        add = QPushButton("Add account")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        controls.addWidget(add)
        box.addLayout(controls)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Balance", "Overdraft limit", "Rate", "Headroom", "", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        box.addWidget(self.table)

    def refresh(self):
        with session_scope() as session:
            accounts = session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)).all()
            self.table.setRowCount(len(accounts))
            for row, account in enumerate(accounts):
                rate = f"{account.overdraft_interest_rate * 100:.2f}%" if account.overdraft_interest_rate is not None else "—"
                values = (
                    account.name, account.account_type.replace("_", " ").title(),
                    format_money(account.current_balance, account.currency),
                    format_money(account.overdraft_limit, account.currency) if account.overdraft_limit is not None else "—",
                    rate, format_money(overdraft_headroom(account), account.currency),
                )
                for col, value in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(value))
                button = QPushButton("Edit")
                button.clicked.connect(lambda _=False, ident=account.id: self.edit(ident))
                self.table.setCellWidget(row, 6, button)
                remove = QPushButton("Delete")
                remove.clicked.connect(lambda _=False, ident=account.id: self.delete_account(ident))
                self.table.setCellWidget(row, 7, remove)

    def delete_account(self, ident):
        answer = QMessageBox.question(
            self, "Confirm deletion",
            "Permanently delete this account and its balance snapshots?\n\n"
            "Referenced accounts cannot be deleted until dependent records are changed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with session_scope() as session:
                session.delete(session.get(Account, ident))
        except IntegrityError:
            QMessageBox.warning(self, "Cannot delete", "This account is used by income, expenses, debts, or events. Reassign those records first.")
            return
        self.refresh()
        self.changed.emit()

    def add(self):
        dialog = AccountDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            with session_scope() as session:
                session.add(Account(**dialog.values()))
            self.refresh()
            self.changed.emit()

    def edit(self, ident):
        with session_scope() as session:
            account = session.get(Account, ident)
            dialog = AccountDialog(account, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            for key, value in dialog.values().items():
                setattr(account, key, value)
        self.refresh()
        self.changed.emit()


class CashFlow(QWidget):
    def __init__(self):
        super().__init__()
        box = page_layout(self, "Cash Flow")
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Horizon"))
        self.days = QComboBox()
        self.days.addItems(["7", "30", "60", "90", "180", "365"])
        self.days.setCurrentText("30")
        self.days.currentTextChanged.connect(self.refresh)
        controls.addWidget(self.days)
        controls.addWidget(QLabel("days"))
        controls.addStretch()
        box.addLayout(controls)
        cards = QHBoxLayout()
        self.committed, self.minimum, self.safe = Card("Committed cash"), Card("Minimum balance"), Card("Safe to spend")
        for card in (self.committed, self.minimum, self.safe):
            cards.addWidget(card)
        box.addLayout(cards)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Description", "Type", "Amount", "Currency", "Projected balance"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        box.addWidget(self.table)

    def refresh(self):
        try:
            with session_scope() as session:
                sheet = current_balance_sheet(session)
                events = generate_events(session, date.today(), date.today() + timedelta(days=int(self.days.currentText())))
                rows = project(sheet.operating_cash, events)
                self.committed.value.setText(format_money(committed_cash(events)))
                self.minimum.value.setText(format_money(lowest_projected_balance(sheet.operating_cash, events)))
                self.safe.value.setText(format_money(safe_to_spend(sheet.operating_cash, events, Decimal("0"))))
                self.table.setRowCount(len(rows))
                for row, event in enumerate(rows):
                    values = (
                        event.date.isoformat(), event.description, event.event_type.replace("_", " ").title(),
                        format_money(event.amount, event.currency), event.currency, format_money(event.running_balance),
                    )
                    for col, value in enumerate(values):
                        self.table.setItem(row, col, QTableWidgetItem(value))
        except Exception as exc:
            QMessageBox.warning(self, "Projection unavailable", str(exc))


class UpdateFinances(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = page_layout(self, "Update Finances", "Update balances quickly and preserve dated snapshots.")
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Snapshot date"))
        self.snapshot_date = QDateEdit(QDate.currentDate())
        self.snapshot_date.setCalendarPopup(True)
        controls.addWidget(self.snapshot_date)
        controls.addStretch()
        box.addLayout(controls)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Account", "Previous", "Current", "Estimated overdraft interest (30d)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        box.addWidget(self.table)
        save = QPushButton("Save updates")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        box.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        self.ids = []

    def refresh(self):
        with session_scope() as session:
            accounts = session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)).all()
            self.ids = [item.id for item in accounts]
            self.table.setRowCount(len(accounts))
            for row, account in enumerate(accounts):
                self.table.setItem(row, 0, QTableWidgetItem(account.name))
                self.table.setItem(row, 1, QTableWidgetItem(format_money(account.current_balance, account.currency)))
                field = AccountDialog.money_spin(-999999999, 999999999)
                field.setValue(float(account.current_balance))
                self.table.setCellWidget(row, 2, field)
                interest = estimated_overdraft_interest(account, 30)
                self.table.setItem(row, 3, QTableWidgetItem(format_money(interest, account.currency) if interest else "—"))

    def save(self):
        with session_scope() as session:
            for row, ident in enumerate(self.ids):
                account = session.get(Account, ident)
                value = Decimal(str(self.table.cellWidget(row, 2).value()))
                update_account_balance(session, account, value, self.snapshot_date.date().toPython())
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Saved", "Balances and snapshots were saved.")


class Placeholder(QWidget):
    def __init__(self, title):
        super().__init__()
        box = page_layout(self, title)
        note = QLabel("This screen is coming in the next implementation milestone.")
        note.setObjectName("muted")
        box.addWidget(note)
        box.addStretch()

    def refresh(self):
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Personal Finance Tracker")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(STYLE)
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(210)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 18, 12, 18)
        brand = QLabel("FINANCE\nTRACKER")
        brand.setObjectName("brand")
        nav.addWidget(brand)
        nav.addSpacing(18)
        self.stack = QStackedWidget()
        definitions = [
            ("Dashboard", Dashboard()), ("Cash Flow", CashFlow()), ("Accounts", Accounts()),
            ("Income", ManagedIncomePage()), ("Recurring Expenses", ManagedExpensePage()),
            ("Debts", ManagedDebtPage()), ("One-Time Events", EventPage()),
            ("Investments", InvestmentManagementPage()),
            ("Update Finances", UpdateFinances()), ("Settings", SettingsPage()),
        ]
        self.pages, self.buttons = [], []
        for index, (label, page) in enumerate(definitions):
            button = QPushButton(label)
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda _=False, i=index: self.navigate(i))
            nav.addWidget(button)
            self.buttons.append(button)
            self.pages.append(page)
            self.stack.addWidget(page)
        nav.addStretch()
        outer.addWidget(sidebar)
        outer.addWidget(self.stack, 1)
        for page in self.pages:
            if hasattr(page, "changed"):
                page.changed.connect(self.refresh_all)
        self.navigate(0)

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)
        self.pages[index].refresh()

    def refresh_all(self):
        for page in self.pages:
            page.refresh()
