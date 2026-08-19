from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import Account, Debt, InvestmentAccount, InvestmentSnapshot, MaterialAsset, Setting
from finance_tracker.services.balance_service import (
    credit_utilization, current_balance_sheet, estimated_overdraft_interest, overdraft_headroom,
    supports_overdraft, update_account_balance, update_debt_balance,
    update_material_asset_value,
)
from finance_tracker.services.investment_service import value_account
from finance_tracker.services.projection_service import (
    committed_cash, generate_events, lowest_projected_balance, position_at, project,
    safe_to_spend,
)
from finance_tracker.utils.money import format_money
from finance_tracker.ui.domain_pages import SettingsPage, configure_table, fit_table_columns, projection_prefs, purpose_choices
from finance_tracker.ui.outlook_page import Outlook
from finance_tracker.ui.progress_page import TrendsPage
from finance_tracker.ui.spending_page import SpendingPage
from finance_tracker.ui.themes import stylesheet
from finance_tracker.ui.management_pages import (
    EventPage, InvestmentManagementPage, ManagedAssetPage, ManagedDebtPage, ManagedDepositPage,
    ManagedExpensePage, ManagedIncomePage, selected_id,
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
QTableWidget::item { padding:6px 10px; }
QTableWidget QDoubleSpinBox {
    padding: 2px 10px;
    min-height: 34px;
    font-size: 15px;
}
QHeaderView::section { background:#202733; color:#b9c4d4; border:none; padding:8px 12px; font-weight:600; }
"""


class Card(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(2)
        label = QLabel(title)
        label.setObjectName("muted")
        self.caption = label
        self.value = QLabel("—")
        self.value.setObjectName("metric")
        self.detail = QLabel()
        self.detail.setObjectName("muted")
        self.detail.setWordWrap(True)
        self.detail.hide()
        box.addWidget(label)
        box.addWidget(self.value)
        box.addWidget(self.detail)

    def set_detail(self, text):
        self.detail.setText(text)
        self.detail.setVisible(bool(text))


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
        note.setWordWrap(True)
        box.addWidget(note)
    return box


class Dashboard(QWidget):
    PREVIEW_LIMIT = 5

    def __init__(self):
        super().__init__()
        box = page_layout(
            self, "Dashboard",
            "A concise view of what is spendable now, what is owed, and where the current schedule leads.",
        )
        self.cards = {}
        for heading, items in (
            ("Spendable now", (
                ("cash", "Operating cash"), ("safe", "Safe to spend"), ("low", "Forecast cash low"),
            )),
            ("Credit and debt", (
                ("cards", "Cards owed"), ("available", "Credit available"),
                ("utilization", "Card utilization"), ("debt", "Total debt"),
            )),
            ("Overall position", (
                ("net", "Net worth"), ("investments", "Investments"), ("material", "Material assets"),
            )),
        ):
            label = QLabel(f"<b>{heading}</b>")
            box.addWidget(label)
            grid = QGridLayout()
            for column, (key, title) in enumerate(items):
                self.cards[key] = Card(title)
                grid.addWidget(self.cards[key], 0, column)
            box.addLayout(grid)

        self.upcoming = QLabel("Next scheduled events")
        box.addWidget(self.upcoming)
        self.upcoming_note = QLabel()
        self.upcoming_note.setObjectName("muted")
        box.addWidget(self.upcoming_note)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Description", "Amount", "Funding"])
        configure_table(self.table)
        self.table.setMinimumHeight(150)
        self.table.setMaximumHeight(245)
        box.addWidget(self.table)
        box.addStretch()

    @staticmethod
    def _percentage(value):
        return f"{value:.1f}%" if value is not None else "-"

    def refresh(self):
        try:
            with session_scope() as session:
                days, reserve, currency = projection_prefs(session)
                today = date.today()
                horizon_end = today + timedelta(days=days)
                sheet = current_balance_sheet(session, currency)
                events = generate_events(session, today, horizon_end, currency)
                rows = project(
                    sheet.operating_cash, events, sheet.credit_cards, sheet.debts,
                    sheet.investments, sheet.credit_limit,
                )
                future = position_at(
                    horizon_end, rows, sheet.operating_cash, sheet.credit_cards,
                    sheet.debts, sheet.investments, sheet.net_worth,
                )
                projected_available = rows[-1].running_available_credit if rows else sheet.available_credit
                current_utilization = credit_utilization(sheet.credit_cards, sheet.credit_limit)
                projected_utilization = credit_utilization(future.cards, sheet.credit_limit)
                values = {
                    "cash": (sheet.operating_cash, f"{days}-day forecast: {format_money(future.cash, currency)}"),
                    "safe": (safe_to_spend(sheet.operating_cash, events, reserve),
                             f"After {format_money(reserve, currency)} reserve"),
                    "low": (lowest_projected_balance(sheet.operating_cash, events), f"Over the next {days} days"),
                    "cards": (sheet.credit_cards, f"{days}-day forecast: {format_money(future.cards, currency)}"),
                    "available": (sheet.available_credit,
                                  f"{days}-day forecast: {format_money(projected_available, currency)}"),
                    "utilization": (current_utilization,
                                    f"{days}-day forecast: {self._percentage(projected_utilization)}"),
                    "debt": (sheet.debts, f"{days}-day forecast: {format_money(future.debt, currency)}"),
                    "net": (sheet.net_worth, f"{days}-day forecast: {format_money(future.net_worth, currency)}"),
                    "investments": (sheet.investments, "Included in net worth, not spendable cash"),
                    "material": (sheet.material_assets, "Included only when marked for net worth"),
                }
                for key, (value, detail) in values.items():
                    self.cards[key].value.setText(
                        self._percentage(value) if key == "utilization" else format_money(value, currency)
                    )
                    self.cards[key].set_detail(detail)

                preview = rows[:self.PREVIEW_LIMIT]
                self.upcoming.setText(f"Next scheduled events - {days}-day horizon")
                remaining = max(len(rows) - len(preview), 0)
                self.upcoming_note.setText(
                    f"Showing the next {len(preview)} of {len(rows)} scheduled events. "
                    + (f"{remaining} more are available in Cash Flow." if remaining else "Full detail is available in Cash Flow.")
                )
                self.table.setRowCount(len(preview))
                for row, event in enumerate(preview):
                    for col, value in enumerate((
                        event.date.isoformat(), event.description,
                        format_money(event.reporting_amount, currency), event.funding_summary or "-",
                    )):
                        self.table.setItem(row, col, QTableWidgetItem(value))
                fit_table_columns(self.table)
                self.table.setToolTip("")
        except Exception as exc:
            for card in self.cards.values():
                card.value.setText("Unavailable")
                card.set_detail("")
            self.table.setRowCount(0)
            self.table.setToolTip(str(exc))


ASSET_ACCOUNT_TYPES = ["checking", "savings", "cash", "digital_wallet", "other"]


class AccountDialog(QDialog):
    def __init__(self, account=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit account" if account else "Add account")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.form = form
        self.name = QLineEdit(account.name if account else "")
        self.kind = QComboBox()
        types = list(ASSET_ACCOUNT_TYPES)
        if account and account.account_type not in types:
            types.append(account.account_type)
        self.kind.addItems(types)
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.purpose = purpose_choices()
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
        self.cash.setToolTip("Controls personal operating cash and safe-to-spend. Usually off for a business wallet.")
        self.net.setToolTip("Include this account in overall net worth even when it is not spendable personal cash.")
        self.credit_note = QLabel("Credit cards belong on the Debts tab. They are liabilities, not cash accounts.")
        self.credit_note.setObjectName("muted")
        self.credit_note.setWordWrap(True)
        if account:
            self.kind.setCurrentText(account.account_type)
            self.currency.setCurrentText(account.currency)
            self.purpose.setCurrentIndex(max(0, self.purpose.findData(account.purpose)))
            self.balance.setValue(float(account.current_balance))
            self.limit.setValue(float(account.overdraft_limit or 0))
            self.rate.setValue(float((account.overdraft_interest_rate or 0) * 100))
        for label, field in (
            ("Name", self.name), ("Type", self.kind), ("Purpose", self.purpose), ("Currency", self.currency),
            ("Current balance", self.balance), ("Overdraft limit", self.limit),
            ("Overdraft annual rate", self.rate), ("Include in operating cash", self.cash),
            ("Include in net worth", self.net),
        ):
            form.addRow(label, field)
        form.addRow(self.credit_note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.kind.currentTextChanged.connect(self.sync_type_fields)
        if account is None:
            self.purpose.currentIndexChanged.connect(self.sync_new_purpose)
        self.sync_type_fields(self.kind.currentText())

    @staticmethod
    def money_spin(low, high):
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setDecimals(2)
        field.setPrefix("$ ")
        field.setGroupSeparatorShown(True)
        return field

    def sync_new_purpose(self):
        self.cash.setChecked(self.purpose.currentData() == "personal")

    def sync_type_fields(self, kind):
        overdraft = supports_overdraft(kind)
        self.form.setRowVisible(self.limit, overdraft)
        self.form.setRowVisible(self.rate, overdraft)
        self.credit_note.setVisible(kind == "credit_card")
        if kind == "credit_card":
            self.cash.setChecked(False)

    def validate(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Name required", "Enter an account name.")
            return
        if supports_overdraft(self.kind.currentText()) and self.limit.value() and self.balance.value() < -self.limit.value():
            QMessageBox.warning(self, "Overdraft exceeded", "The balance exceeds the entered overdraft limit.")
            return
        self.accept()

    def values(self):
        kind = self.kind.currentText()
        if supports_overdraft(kind) and self.limit.value():
            limit = Decimal(str(self.limit.value()))
        else:
            limit = None
        rate = Decimal(str(self.rate.value())) / Decimal("100") if supports_overdraft(kind) and self.rate.value() else None
        return dict(
            name=self.name.text().strip(), account_type=kind, purpose=self.purpose.currentData(),
            currency=self.currency.currentText(), current_balance=Decimal(str(self.balance.value())),
            overdraft_limit=limit, overdraft_interest_rate=rate,
            include_in_cash=False if kind == "credit_card" else self.cash.isChecked(),
            include_in_net_worth=self.net.isChecked(),
        )


class Accounts(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = page_layout(
            self, "Accounts",
            "Chequing accounts can have overdraft. Credit cards belong under Debts.",
        )
        controls = QHBoxLayout()
        controls.addStretch()
        edit = QPushButton("Edit")
        edit.clicked.connect(self.edit)
        remove = QPushButton("Delete")
        remove.clicked.connect(self.delete_account)
        add = QPushButton("Add account")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        for button in (edit, remove, add):
            controls.addWidget(button)
        box.addLayout(controls)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Purpose", "Balance", "Overdraft limit", "Rate", "Headroom"])
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table)

    def refresh(self):
        with session_scope() as session:
            accounts = session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)).all()
            self.table.setRowCount(len(accounts))
            for row, account in enumerate(accounts):
                overdraft = supports_overdraft(account.account_type)
                rate = (
                    f"{account.overdraft_interest_rate * 100:.2f}%"
                    if overdraft and account.overdraft_interest_rate is not None else "—"
                )
                values = (
                    account.name, account.account_type.replace("_", " ").title(), account.purpose.title(),
                    format_money(account.current_balance, account.currency),
                    format_money(account.overdraft_limit, account.currency) if overdraft and account.overdraft_limit is not None else "—",
                    rate,
                    format_money(overdraft_headroom(account), account.currency) if overdraft else "—",
                )
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, account.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)

    def delete_account(self):
        ident = selected_id(self.table)
        if ident is None:
            return
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
                account = Account(**dialog.values())
                session.add(account)
                session.flush()
                update_account_balance(session, account, account.current_balance, date.today())
            self.refresh()
            self.changed.emit()

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            account = session.get(Account, ident)
            if account is None:
                return
            dialog = AccountDialog(account, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            account = session.get(Account, ident)
            values = dialog.values()
            old_balance = account.current_balance
            for key, value in values.items():
                if key != "current_balance":
                    setattr(account, key, value)
            if values["current_balance"] != old_balance:
                update_account_balance(session, account, values["current_balance"], date.today())
        self.refresh()
        self.changed.emit()


class CashFlow(QWidget):
    FILTERS = (
        ("income", "Income", frozenset({"income"})),
        ("bills", "Bills", frozenset({"expense"})),
        ("cards", "Card charges", frozenset({"card_charge"})),
        ("debt", "Debt payments", frozenset({"debt_payment"})),
        ("transfers", "Transfers", frozenset({"deposit", "adjustment"})),
    )

    def __init__(self):
        super().__init__()
        box = page_layout(
            self, "Cash Flow",
            "The complete scheduled timeline. Filters hide rows only; running balances always include every event.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Horizon"))
        self.days = QComboBox()
        self.days.addItems(["7", "30", "60", "90", "180", "365"])
        self.days.currentTextChanged.connect(self.refresh)
        self.apply_settings()
        controls.addWidget(self.days)
        controls.addWidget(QLabel("days"))
        controls.addSpacing(20)
        controls.addWidget(QLabel("Purpose"))
        self.purpose_filter = QComboBox()
        self.purpose_filter.addItem("All", "all")
        self.purpose_filter.addItem("Personal", "personal")
        self.purpose_filter.addItem("Business", "business")
        self.purpose_filter.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.purpose_filter)
        controls.addStretch()
        box.addLayout(controls)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Show"))
        self.type_filters = {}
        for key, label, _event_types in self.FILTERS:
            field = QCheckBox(label)
            field.setChecked(True)
            field.toggled.connect(self.refresh)
            self.type_filters[key] = field
            filters.addWidget(field)
        filters.addStretch()
        box.addLayout(filters)

        cards = QGridLayout()
        self.committed, self.minimum, self.safe = Card("Committed cash"), Card("Minimum cash"), Card("Safe to spend")
        self.proj_cards, self.proj_available, self.proj_debt = Card("Projected cards"), Card("Credit available"), Card("Projected debt")
        self.flow_cards = (self.committed, self.minimum, self.safe, self.proj_cards, self.proj_available, self.proj_debt)
        for index, card in enumerate(self.flow_cards):
            cards.addWidget(card, index / 3, index % 3)
        box.addLayout(cards)

        self.filter_status = QLabel()
        self.filter_status.setObjectName("muted")
        box.addWidget(self.filter_status)
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Description", "Type", "Purpose", "Amount", "Currency", "Funding",
             "Cash", "Investments", "Cards", "Credit available", "Debt"],
        )
        configure_table(self.table)
        box.addWidget(self.table)

    def apply_settings(self):
        with session_scope() as session:
            days, _, _ = projection_prefs(session)
        self.days.blockSignals(True)
        self.days.setCurrentText(str(days))
        self.days.blockSignals(False)

    def _visible(self, event):
        enabled_types = set()
        for key, _label, event_types in self.FILTERS:
            if self.type_filters[key].isChecked():
                enabled_types.update(event_types)
        purpose = self.purpose_filter.currentData()
        return event.event_type in enabled_types and (purpose == "all" or event.purpose == purpose)

    def refresh(self):
        try:
            with session_scope() as session:
                _, reserve, currency = projection_prefs(session)
                horizon = int(self.days.currentText())
                sheet = current_balance_sheet(session, currency)
                events = generate_events(session, date.today(), date.today() + timedelta(days=horizon), currency)
                rows = project(sheet.operating_cash, events, sheet.credit_cards, sheet.debts, sheet.investments, sheet.credit_limit)
                self.committed.value.setText(format_money(committed_cash(rows), currency))
                self.minimum.value.setText(format_money(lowest_projected_balance(sheet.operating_cash, events), currency))
                self.safe.value.setText(format_money(safe_to_spend(sheet.operating_cash, events, reserve), currency))
                if rows:
                    self.proj_cards.value.setText(format_money(rows[-1].running_cards, currency))
                    self.proj_available.value.setText(format_money(rows[-1].running_available_credit, currency))
                    self.proj_debt.value.setText(format_money(rows[-1].running_debt, currency))
                else:
                    self.proj_cards.value.setText(format_money(sheet.credit_cards, currency))
                    self.proj_available.value.setText(format_money(sheet.available_credit, currency))
                    self.proj_debt.value.setText(format_money(sheet.debts, currency))

                visible = [event for event in rows if self._visible(event)]
                self.filter_status.setText(
                    f"Showing {len(visible)} of {len(rows)} events. Summary cards and running columns retain the complete schedule."
                )
                self.table.setRowCount(len(visible))
                for row, event in enumerate(visible):
                    values = (
                        event.date.isoformat(), event.description, event.event_type.replace("_", " ").title(),
                        event.purpose.title(), format_money(event.amount, event.currency), event.currency,
                        event.funding_summary or "-", format_money(event.running_balance, currency),
                        format_money(event.running_investments, currency), format_money(event.running_cards, currency),
                        format_money(event.running_available_credit, currency), format_money(event.running_debt, currency),
                    )
                    for col, value in enumerate(values):
                        self.table.setItem(row, col, QTableWidgetItem(value))
                fit_table_columns(self.table)
                self.table.setToolTip("")
        except Exception as exc:
            for card in self.flow_cards:
                card.value.setText("Unavailable")
            self.table.setRowCount(0)
            self.table.setToolTip(str(exc))


class UpdateFinances(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = page_layout(
            self, "Update Finances",
            "Look at the bank / brokerage / debt apps, type what they say, save. "
            "That becomes today's snapshot. Holdings and stock prices stay on Investments.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("As of"))
        self.snapshot_date = QDateEdit(QDate.currentDate())
        self.snapshot_date.setCalendarPopup(True)
        controls.addWidget(self.snapshot_date)
        controls.addStretch()
        box.addLayout(controls)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Type", "Name", "On file", "New amount", "Note"])
        configure_table(self.table)
        self.table.verticalHeader().setDefaultSectionSize(48)
        box.addWidget(self.table)
        save = QPushButton("Save updates")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        box.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        self.rows = []

    def _amount_field(self, value):
        field = QDoubleSpinBox()
        field.setRange(-999999999, 999999999)
        field.setDecimals(2)
        field.setPrefix("$ ")
        field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        field.setGroupSeparatorShown(False)
        field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        field.setMinimumSize(200, 36)
        field.setValue(float(value))
        return field

    def refresh(self):
        rows = []
        with session_scope() as session:
            for account in session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)):
                interest = estimated_overdraft_interest(account, 30)
                note = f"Overdraft ~{format_money(interest, account.currency)} if you stay here 30 days" if interest else "—"
                rows.append(("account", account.id, "Bank", account.name,
                             format_money(account.current_balance, account.currency),
                             account.current_balance, note))
            for debt in session.scalars(select(Debt).where(Debt.active.is_(True)).order_by(Debt.name)):
                rows.append(("debt", debt.id, "Debt", debt.name,
                             format_money(debt.current_balance, debt.currency),
                             debt.current_balance, "Amount still owed"))
            for account in session.scalars(
                select(InvestmentAccount).where(InvestmentAccount.active.is_(True)).order_by(InvestmentAccount.name)
            ):
                rows.append(("investment", account.id, "Investment cash", account.name,
                             format_money(account.cash_balance, account.cash_currency),
                             account.cash_balance, "Cash in the account, not holdings"))
            for asset in session.scalars(
                select(MaterialAsset).where(MaterialAsset.active.is_(True)).order_by(MaterialAsset.name)
            ):
                rows.append(("asset", asset.id, "Asset", asset.name,
                             format_money(asset.current_value, asset.currency),
                             asset.current_value, "Estimated resale"))
        self.rows = [(kind, ident) for kind, ident, *_ in rows]
        self.table.setRowCount(len(rows))
        for row, (_, _, kind, name, previous, amount, note) in enumerate(rows):
            self.table.setItem(row, 0, QTableWidgetItem(kind))
            self.table.setItem(row, 1, QTableWidgetItem(name))
            self.table.setItem(row, 2, QTableWidgetItem(previous))
            self.table.setCellWidget(row, 3, self._amount_field(amount))
            self.table.setItem(row, 4, QTableWidgetItem(note))
        fit_table_columns(self.table)
        self.table.setColumnWidth(3, max(self.table.columnWidth(3), 220))
        self.table.setColumnWidth(4, max(self.table.columnWidth(4), 280))
        self.table.resizeRowsToContents()
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, max(self.table.rowHeight(row), 48))

    def save(self):
        on_date = self.snapshot_date.date().toPython()
        with session_scope() as session:
            for row, (kind, ident) in enumerate(self.rows):
                value = Decimal(str(self.table.cellWidget(row, 3).value()))
                if kind == "account":
                    update_account_balance(session, session.get(Account, ident), value, on_date)
                elif kind == "debt":
                    update_debt_balance(session, session.get(Debt, ident), value, on_date)
                elif kind == "investment":
                    account = session.get(InvestmentAccount, ident)
                    account.cash_balance = value
                    session.add(InvestmentSnapshot(
                        investment_account_id=account.id,
                        market_value=value_account(session, account, account.cash_currency, on_date),
                        reporting_currency=account.cash_currency,
                        cash_balance=value,
                        snapshot_date=on_date,
                    ))
                elif kind == "asset":
                    update_material_asset_value(session, session.get(MaterialAsset, ident), value, on_date)
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Saved", "Those amounts are now on file, with a snapshot for this date.")


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
        self.apply_theme()
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
            ("Dashboard", Dashboard()), ("Cash Flow", CashFlow()), ("Spending", SpendingPage()),
            ("Outlook", Outlook()), ("Trends", TrendsPage()),
            ("Accounts", Accounts()),
            ("Income", ManagedIncomePage()), ("Deposits", ManagedDepositPage()),
            ("Recurring Expenses", ManagedExpensePage()),
            ("Debts", ManagedDebtPage()), ("Assets", ManagedAssetPage()), ("One-Time Events", EventPage()),
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

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_tables_fitted", False):
            return
        self._tables_fitted = True
        for table in self.findChildren(QTableWidget):
            fit_table_columns(table)

    def navigate(self, index):
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)
        self.pages[index].refresh()

    def apply_theme(self):
        with session_scope() as session:
            setting = session.get(Setting, "theme")
            name = setting.value if setting is not None else "system"
        self.setStyleSheet(stylesheet(name))

    def refresh_all(self):
        self.apply_theme()
        for page in self.pages:
            if hasattr(page, "apply_settings"):
                page.apply_settings()
            page.refresh()
