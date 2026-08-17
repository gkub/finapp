from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from finance_tracker.db.database import default_database_path, session_scope
from finance_tracker.db.models import (
    Account, Category, Debt, IncomeSource, InvestmentAccount, InvestmentHolding,
    RecurringExpense, Schedule, ScheduleType, SecurityPrice, Setting,
)
from finance_tracker.services.currency_service import latest_rate, upsert_rate
from finance_tracker.services.investment_service import PriceUnavailable, upsert_price, value_account
from finance_tracker.services.market_data import MarketDataError, fetch_quote as download_quote, fetch_usd_cad
from finance_tracker.services.schedule_service import occurrences
from finance_tracker.utils.money import format_money


def money_spin():
    field = QDoubleSpinBox()
    field.setRange(0, 999_999_999)
    field.setDecimals(2)
    field.setPrefix("$ ")
    field.setGroupSeparatorShown(True)
    return field


def quantity_spin():
    field = QDoubleSpinBox()
    field.setRange(0, 999_999_999)
    field.setDecimals(8)
    field.setGroupSeparatorShown(True)
    return field


def titled_page(widget, title, subtitle):
    box = QVBoxLayout(widget)
    box.setContentsMargins(28, 24, 28, 24)
    box.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("title")
    note = QLabel(subtitle)
    note.setObjectName("muted")
    note.setWordWrap(True)
    box.addWidget(heading)
    box.addWidget(note)
    return box


def projection_prefs(session):
    days, reserve, currency = 30, Decimal("0"), "CAD"
    for item in session.scalars(select(Setting)):
        if item.key == "default_projection_days":
            days = int(item.value)
        elif item.key == "cash_reserve_amount":
            reserve = Decimal(item.value)
        elif item.key == "reporting_currency":
            currency = item.value
    return days, reserve, currency


def configure_table(table):
    """Size every column to its header and cells instead of stretching one column."""
    table.setAlternatingRowColors(True)
    table.setWordWrap(False)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setTextElideMode(Qt.TextElideMode.ElideRight)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setStretchLastSection(False)
    header.setMinimumSectionSize(72)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setTextElideMode(Qt.TextElideMode.ElideNone)
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)


def fit_table_columns(table, max_width=280):
    header = table.horizontalHeader()
    metrics = header.fontMetrics()
    table.resizeColumnsToContents()
    for col in range(table.columnCount()):
        item = table.horizontalHeaderItem(col)
        label = item.text() if item else ""
        header_width = metrics.horizontalAdvance(label) + 28
        width = max(table.columnWidth(col) + 16, header_width)
        has_widget = False
        for row in range(table.rowCount()):
            widget = table.cellWidget(row, col)
            if widget is not None:
                has_widget = True
                width = max(width, widget.sizeHint().width() + 20)
        cap = width if has_widget else min(width, max_width)
        table.setColumnWidth(col, max(header_width, cap))


def account_choices(combo, include_blank=True):
    if include_blank:
        combo.addItem("None", None)
    with session_scope() as session:
        for account in session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)):
            combo.addItem(account.name, account.id)


def debt_choices(combo, include_blank=True):
    combo.clear()
    if include_blank:
        combo.addItem("None", None)
    with session_scope() as session:
        for debt in session.scalars(select(Debt).where(Debt.active.is_(True)).order_by(Debt.name)):
            combo.addItem(debt.name, debt.id)


def payment_method_choices(combo, include_blank=True):
    combo.clear()
    if include_blank:
        combo.addItem("None", None)
    with session_scope() as session:
        for account in session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)):
            combo.addItem(account.name, f"account:{account.id}")
        cards = session.scalars(
            select(Debt).where(Debt.active.is_(True), Debt.debt_type == "credit_card").order_by(Debt.name)
        )
        for debt in cards:
            combo.addItem(f"{debt.name} (credit card)", f"debt:{debt.id}")


def payment_method_ids(combo):
    data = combo.currentData()
    if not data:
        return None, None
    kind, _, ident = data.partition(":")
    if not ident:
        return None, None
    value = int(ident)
    if kind == "debt":
        return None, value
    return value, None


def set_payment_method(combo, account_id=None, debt_id=None):
    if debt_id:
        target = f"debt:{debt_id}"
    elif account_id:
        target = f"account:{account_id}"
    else:
        target = None
    index = combo.findData(target)
    if index >= 0:
        combo.setCurrentIndex(index)


def payment_method_label(session, account_id=None, debt_id=None):
    if debt_id:
        debt = session.get(Debt, debt_id)
        return f"{debt.name} (card)" if debt else "—"
    if account_id:
        account = session.get(Account, account_id)
        return account.name if account else "—"
    return "—"


def destination_choices(combo, include_blank=False):
    combo.clear()
    if include_blank:
        combo.addItem("None", None)
    with session_scope() as session:
        for account in session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)):
            combo.addItem(account.name, f"account:{account.id}")
        for item in session.scalars(
            select(InvestmentAccount).where(InvestmentAccount.active.is_(True)).order_by(InvestmentAccount.name)
        ):
            combo.addItem(f"{item.name} ({item.account_type.upper()})", f"investment:{item.id}")


def destination_ids(combo):
    data = combo.currentData()
    if not data:
        return None, None
    kind, _, ident = data.partition(":")
    if not ident:
        return None, None
    value = int(ident)
    if kind == "investment":
        return None, value
    return value, None


def set_destination(combo, account_id=None, investment_id=None):
    if investment_id:
        target = f"investment:{investment_id}"
    elif account_id:
        target = f"account:{account_id}"
    else:
        target = None
    index = combo.findData(target)
    if index >= 0:
        combo.setCurrentIndex(index)


def destination_label(session, account_id=None, investment_id=None):
    if investment_id:
        item = session.get(InvestmentAccount, investment_id)
        return f"{item.name} ({item.account_type.upper()})" if item else "—"
    if account_id:
        account = session.get(Account, account_id)
        return account.name if account else "—"
    return "—"


class ScheduleFields:
    def __init__(self, form, default="monthly"):
        self.kind = QComboBox()
        self.kind.addItems(["monthly", "every_n_weeks", "weekly", "every_n_months", "yearly", "one_time"])
        self.kind.setCurrentText(default)
        self.anchor = QDateEdit(QDate.currentDate())
        self.anchor.setCalendarPopup(True)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1, 52)
        self.interval.setDecimals(0)
        self.interval.setValue(1)
        self.day = QDoubleSpinBox()
        self.day.setRange(1, 31)
        self.day.setDecimals(0)
        self.day.setValue(QDate.currentDate().day())
        self.month = QComboBox()
        self.month.addItems(["January", "February", "March", "April", "May", "June",
                             "July", "August", "September", "October", "November", "December"])
        self.month.setCurrentIndex(QDate.currentDate().month() - 1)
        form.addRow("Schedule", self.kind)
        form.addRow("Anchor/start date", self.anchor)
        form.addRow("Interval", self.interval)
        form.addRow("Day of month", self.day)
        form.addRow("Month (yearly)", self.month)

    def create(self):
        kind = self.kind.currentText()
        schedule = Schedule(
            schedule_type=kind, interval=int(self.interval.value()),
            anchor_date=self.anchor.date().toPython(), start_date=self.anchor.date().toPython(),
        )
        if kind in ("monthly", "every_n_months", "yearly"):
            schedule.day_of_month = int(self.day.value())
        if kind == "yearly":
            schedule.month_of_year = self.month.currentIndex() + 1
        return schedule

    @staticmethod
    def describe(schedule):
        kind = schedule.schedule_type
        if kind == "every_n_weeks":
            return f"Every {schedule.interval} weeks"
        if kind == "weekly":
            return "Weekly"
        if kind == "monthly":
            return f"Monthly, day {schedule.day_of_month}"
        if kind == "every_n_months":
            return f"Every {schedule.interval} months, day {schedule.day_of_month}"
        if kind == "yearly":
            return f"Yearly, {schedule.month_of_year}/{schedule.day_of_month}"
        return f"Once, {schedule.anchor_date}"


class BaseDialog(QDialog):
    def finish(self, form):
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def validate(self):
        if hasattr(self, "name") and not self.name.text().strip():
            QMessageBox.warning(self, "Name required", "Enter a name.")
            return
        self.accept()


class IncomeDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add income")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.amount = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.account = QComboBox()
        account_choices(self.account)
        form.addRow("Name", self.name)
        form.addRow("Amount", self.amount)
        form.addRow("Currency", self.currency)
        form.addRow("Destination", self.account)
        self.schedule = ScheduleFields(form)
        self.finish(form)


class DepositDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add deposit")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.amount = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.source = QComboBox()
        account_choices(self.source)
        if self.source.count():
            self.source.setItemText(0, "New money")
        self.destination = QComboBox()
        destination_choices(self.destination)
        form.addRow("Name", self.name)
        form.addRow("Amount", self.amount)
        form.addRow("Currency", self.currency)
        form.addRow("From", self.source)
        form.addRow("To", self.destination)
        self.schedule = ScheduleFields(form)
        self.finish(form)


class MaterialAssetDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add asset")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["vehicle", "property", "electronics", "jewellery", "collectible", "other"])
        self.value = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.net = QCheckBox()
        self.net.setChecked(True)
        self.notes = QLineEdit()
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Estimated value", self.value)
        form.addRow("Currency", self.currency)
        form.addRow("Include in net worth", self.net)
        form.addRow("Notes", self.notes)
        self.finish(form)


class ExpenseDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add recurring expense")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.amount = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.category = QLineEdit()
        self.priority = QComboBox()
        self.priority.addItems(["essential", "important", "luxury", "expendable"])
        self.account = QComboBox()
        payment_method_choices(self.account)
        self.backup = QComboBox()
        account_choices(self.backup)
        for label, field in (("Name", self.name), ("Amount", self.amount), ("Currency", self.currency),
                             ("Category", self.category), ("Priority", self.priority),
                             ("Paid from / charged to", self.account), ("Backup bank account", self.backup)):
            form.addRow(label, field)
        self.schedule = ScheduleFields(form)
        self.finish(form)

    def validate(self):
        backup_id = self.backup.currentData()
        if backup_id is not None and self.account.currentData() == f"account:{backup_id}":
            QMessageBox.warning(self, "Choose another backup", "The backup account must differ from the primary account.")
            return
        super().validate()


class DebtDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add debt")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["student_loan", "credit_card", "vehicle_loan", "personal_loan", "line_of_credit", "other"])
        self.balance = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 999)
        self.rate.setDecimals(4)
        self.rate.setSuffix(" %")
        self.rate_period = QComboBox()
        self.rate_period.addItems(["per year", "per month"])
        self.rate_period.setToolTip("Monthly rates are converted to an annual rate (× 12) when saved.")
        self._period = "per year"
        self.rate_period.currentTextChanged.connect(self.convert_rate_period)
        rate_row = QHBoxLayout()
        rate_row.addWidget(self.rate, 1)
        rate_row.addWidget(self.rate_period)
        self.credit_limit = money_spin()
        self.payment = money_spin()
        self.account = QComboBox()
        account_choices(self.account)
        for label, field in (("Name", self.name), ("Type", self.kind), ("Balance owed", self.balance),
                             ("Currency", self.currency)):
            form.addRow(label, field)
        form.addRow("Interest rate", rate_row)
        form.addRow("Credit limit", self.credit_limit)
        form.addRow("Scheduled payment", self.payment)
        self.payment.setToolTip("Optional. Use for loans with a fixed bill. Leave $0 if you pay this down manually.")
        form.addRow("Paid from (bank)", self.account)
        self.schedule = ScheduleFields(form)
        self.finish(form)
        self.kind.currentTextChanged.connect(
            lambda value: form.setRowVisible(self.credit_limit, value == "credit_card")
        )
        form.setRowVisible(self.credit_limit, self.kind.currentText() == "credit_card")

    def convert_rate_period(self, period):
        if period == self._period:
            return
        value = self.rate.value()
        if self._period == "per year" and period == "per month":
            self.rate.setValue(value / 12)
        elif self._period == "per month" and period == "per year":
            self.rate.setValue(value * 12)
        self._period = period

    def annual_rate(self):
        if not self.rate.value():
            return None
        fraction = Decimal(str(self.rate.value())) / Decimal("100")
        if self.rate_period.currentText() == "per month":
            return fraction * Decimal("12")
        return fraction

    def set_annual_rate(self, annual):
        self.rate_period.blockSignals(True)
        self.rate_period.setCurrentText("per year")
        self._period = "per year"
        self.rate_period.blockSignals(False)
        self.rate.setValue(float((annual or 0) * 100))


class CrudPage(QWidget):
    changed = Signal()
    model = None

    def action_row(self, box, add_text, callback):
        row = QHBoxLayout()
        row.addStretch()
        toggle = QPushButton("Enable / disable selected")
        toggle.clicked.connect(self.toggle)
        add = QPushButton(add_text)
        add.setObjectName("primary")
        add.clicked.connect(callback)
        row.addWidget(toggle)
        row.addWidget(add)
        box.addLayout(row)

    def toggle(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a row", "Select a record first.")
            return
        ident = int(self.table.item(row, 0).data(256))
        with session_scope() as session:
            item = session.get(self.model, ident)
            item.active = not item.active
        self.refresh()
        self.changed.emit()


class IncomePage(CrudPage):
    model = IncomeSource

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Income", "Recurring income uses exact occurrence dates.")
        self.action_row(box, "Add income", self.add)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Amount", "Schedule", "Next date", "Destination", "Status"])
        configure_table(self.table)
        box.addWidget(self.table)

    def add(self):
        dialog = IncomeDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            schedule = dialog.schedule.create()
            session.add(schedule)
            session.flush()
            session.add(IncomeSource(
                name=dialog.name.text().strip(), amount=Decimal(str(dialog.amount.value())),
                currency=dialog.currency.currentText(), schedule_id=schedule.id,
                destination_account_id=dialog.account.currentData(),
            ))
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(IncomeSource).order_by(IncomeSource.active.desc(), IncomeSource.name)).all()
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                schedule = session.get(Schedule, item.schedule_id)
                dates = occurrences(schedule, date.today(), date.today().replace(year=date.today().year + 2))
                account = session.get(Account, item.destination_account_id) if item.destination_account_id else None
                values = (item.name, format_money(item.amount, item.currency), ScheduleFields.describe(schedule),
                          dates[0].isoformat() if dates else "—", account.name if account else "—", "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class ExpensePage(CrudPage):
    model = RecurringExpense

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Recurring Expenses", "Bills are projected from their actual schedules, never monthly averages.")
        self.action_row(box, "Add expense", self.add)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Amount", "Category", "Priority", "Schedule", "Next date", "Status"])
        configure_table(self.table)
        box.addWidget(self.table)

    def add(self):
        dialog = ExpenseDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            schedule = dialog.schedule.create()
            session.add(schedule)
            category = None
            if dialog.category.text().strip():
                category = session.scalar(select(Category).where(Category.name == dialog.category.text().strip()))
                if category is None:
                    category = Category(name=dialog.category.text().strip())
                    session.add(category)
            session.flush()
            session.add(RecurringExpense(
                name=dialog.name.text().strip(), amount=Decimal(str(dialog.amount.value())),
                currency=dialog.currency.currentText(), schedule_id=schedule.id,
                category_id=category.id if category else None, priority=dialog.priority.currentText(),
                payment_account_id=payment_method_ids(dialog.account)[0],
                payment_debt_id=payment_method_ids(dialog.account)[1],
            ))
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(RecurringExpense).order_by(RecurringExpense.active.desc(), RecurringExpense.name)).all()
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                schedule = session.get(Schedule, item.schedule_id)
                category = session.get(Category, item.category_id) if item.category_id else None
                dates = occurrences(schedule, date.today(), date.today().replace(year=date.today().year + 2))
                values = (item.name, format_money(item.amount, item.currency), category.name if category else "—",
                          item.priority.title(), ScheduleFields.describe(schedule), dates[0].isoformat() if dates else "—",
                          "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class DebtPage(CrudPage):
    model = Debt

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Debts", "Balances are positive amounts owed and are subtracted from net worth.")
        self.total = QLabel()
        self.total.setObjectName("metric")
        box.addWidget(self.total)
        self.action_row(box, "Add debt", self.add)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Balance", "Rate", "Minimum", "Schedule", "Status"])
        configure_table(self.table)
        box.addWidget(self.table)

    def add(self):
        dialog = DebtDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            schedule = dialog.schedule.create()
            session.add(schedule)
            session.flush()
            session.add(Debt(
                name=dialog.name.text().strip(), debt_type=dialog.kind.currentText(),
                current_balance=Decimal(str(dialog.balance.value())), currency=dialog.currency.currentText(),
                interest_rate=dialog.annual_rate(),
                minimum_payment=Decimal(str(dialog.payment.value())), payment_schedule_id=schedule.id,
                payment_account_id=dialog.account.currentData(),
            ))
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(Debt).order_by(Debt.active.desc(), Debt.name)).all()
            cad_total = sum((item.current_balance for item in items if item.active and item.currency == "CAD"), Decimal("0"))
            self.total.setText(f"CAD debt: {format_money(cad_total)}")
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                schedule = session.get(Schedule, item.payment_schedule_id) if item.payment_schedule_id else None
                values = (item.name, item.debt_type.replace("_", " ").title(), format_money(item.current_balance, item.currency),
                          f"{item.interest_rate * 100:.2f}% / yr" if item.interest_rate is not None else "—",
                          format_money(item.minimum_payment or Decimal('0'), item.currency),
                          ScheduleFields.describe(schedule) if schedule else "—", "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class InvestmentAccountDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add investment account")
        form = QFormLayout(self)
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["tfsa", "fhsa", "rrsp", "non_registered", "other"])
        self.cash = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        for label, field in (("Name", self.name), ("Type", self.kind), ("Cash balance", self.cash), ("Cash currency", self.currency)):
            form.addRow(label, field)
        self.finish(form)


class HoldingDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add holding and price")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.account = QComboBox()
        with session_scope() as session:
            for account in session.scalars(select(InvestmentAccount).where(InvestmentAccount.active.is_(True)).order_by(InvestmentAccount.name)):
                self.account.addItem(account.name, account.id)
        self.symbol = QLineEdit()
        self.name = QLineEdit()
        self.asset = QComboBox()
        self.asset.addItems(["etf", "stock", "mutual_fund", "cash_equivalent", "other"])
        self.quantity = quantity_spin()
        self.price = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.price_date = QDateEdit(QDate.currentDate())
        self.price_date.setCalendarPopup(True)
        for label, field in (("Account", self.account), ("Symbol", self.symbol), ("Name", self.name),
                             ("Asset type", self.asset), ("Quantity", self.quantity), ("Price", self.price),
                             ("Quote currency", self.currency), ("Price date", self.price_date)):
            form.addRow(label, field)
        fetch = QPushButton("Fetch quote")
        fetch.clicked.connect(self.fetch_quote)
        form.addRow(fetch)
        self.finish(form)

    def fetch_quote(self):
        symbol = self.symbol.text().strip().upper()
        if not symbol:
            QMessageBox.warning(self, "Symbol required", "Enter a ticker such as AAPL or VFV.TO.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            price, currency, price_date = download_quote(symbol)
        except MarketDataError as exc:
            QMessageBox.warning(self, "Quote unavailable", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.symbol.setText(symbol)
        if not self.name.text().strip():
            self.name.setText(symbol)
        self.price.setValue(float(price))
        if self.currency.findText(currency) >= 0:
            self.currency.setCurrentText(currency)
        self.price_date.setDate(QDate(price_date.year, price_date.month, price_date.day))

    def validate(self):
        if self.account.currentData() is None or not self.symbol.text().strip():
            QMessageBox.warning(self, "Required fields", "Select an account and enter a symbol.")
            return
        if not self.name.text().strip():
            self.name.setText(self.symbol.text().strip().upper())
        self.accept()


class InvestmentPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Investments", "TFSA, FHSA, and other accounts with manual offline prices.")
        row = QHBoxLayout()
        row.addStretch()
        account = QPushButton("Add account")
        account.clicked.connect(self.add_account)
        holding = QPushButton("Add holding / price")
        holding.setObjectName("primary")
        holding.clicked.connect(self.add_holding)
        row.addWidget(account)
        row.addWidget(holding)
        box.addLayout(row)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Account", "Type", "Symbol", "Units", "Latest price", "Reporting value"])
        configure_table(self.table)
        box.addWidget(self.table)

    def add_account(self):
        dialog = InvestmentAccountDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            session.add(InvestmentAccount(name=dialog.name.text().strip(), account_type=dialog.kind.currentText(),
                                          cash_balance=Decimal(str(dialog.cash.value())), cash_currency=dialog.currency.currentText()))
        self.refresh()
        self.changed.emit()

    def add_holding(self):
        dialog = HoldingDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        symbol = dialog.symbol.text().strip().upper()
        with session_scope() as session:
            session.add(InvestmentHolding(
                investment_account_id=dialog.account.currentData(), symbol=symbol,
                name=dialog.name.text().strip(), asset_type=dialog.asset.currentText(),
                quantity=Decimal(str(dialog.quantity.value())), quote_currency=dialog.currency.currentText(),
            ))
            upsert_price(session, symbol, Decimal(str(dialog.price.value())),
                         dialog.currency.currentText(), dialog.price_date.date().toPython())
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            accounts = session.scalars(select(InvestmentAccount).where(InvestmentAccount.active.is_(True)).order_by(InvestmentAccount.name)).all()
            rows = []
            for account in accounts:
                holdings = session.scalars(select(InvestmentHolding).where(
                    InvestmentHolding.investment_account_id == account.id, InvestmentHolding.active.is_(True))).all()
                if not holdings:
                    rows.append((account, None))
                else:
                    rows.extend((account, holding) for holding in holdings)
            self.table.setRowCount(len(rows))
            for row, (account, holding) in enumerate(rows):
                if holding is None:
                    values = (account.name, account.account_type.upper(), "Cash", "—", "—", format_money(account.cash_balance, account.cash_currency))
                else:
                    price = session.scalar(select(SecurityPrice).where(SecurityPrice.symbol == holding.symbol).order_by(SecurityPrice.price_date.desc()))
                    try:
                        total = value_account(session, account)
                        report = format_money(total) if len([x for x in rows if x[0].id == account.id]) == 1 else "Included in account"
                    except (PriceUnavailable, LookupError) as exc:
                        report = str(exc)
                    values = (account.name, account.account_type.upper(), holding.symbol, f"{holding.quantity:f}",
                              format_money(price.price, price.currency) if price else "Missing", report)
                for col, value in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(value))
            fit_table_columns(self.table)


class SettingsPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Settings", "Reporting preferences and local database backup.")
        form = QFormLayout()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.days = QComboBox()
        self.days.addItems(["7", "30", "60", "90", "180", "365"])
        self.reserve = money_spin()
        self.theme = QComboBox()
        self.theme.addItems(["system", "dark", "light", "pink"])
        form.addRow("Reporting currency", self.currency)
        form.addRow("Default projection days", self.days)
        form.addRow("Cash reserve", self.reserve)
        form.addRow("Theme", self.theme)
        box.addLayout(form)
        box.addWidget(QLabel("USD / CAD"))
        self.fx_status = QLabel("No USD/CAD rate saved yet.")
        self.fx_status.setObjectName("muted")
        box.addWidget(self.fx_status)
        fx_form = QFormLayout()
        self.fx_rate = QDoubleSpinBox()
        self.fx_rate.setDecimals(4)
        self.fx_rate.setRange(0.0001, 10)
        self.fx_rate.setSingleStep(0.0001)
        self.fx_rate.setValue(1.35)
        self.fx_date = QDateEdit(QDate.currentDate())
        self.fx_date.setCalendarPopup(True)
        fx_form.addRow("CAD per 1 USD", self.fx_rate)
        fx_form.addRow("Rate date", self.fx_date)
        box.addLayout(fx_form)
        fx_row = QHBoxLayout()
        save_fx = QPushButton("Save USD/CAD rate")
        save_fx.clicked.connect(self.save_fx)
        fetch_fx = QPushButton("Fetch Bank of Canada rate")
        fetch_fx.clicked.connect(self.fetch_fx)
        fx_row.addWidget(fetch_fx)
        fx_row.addStretch()
        fx_row.addWidget(save_fx)
        box.addLayout(fx_row)
        row = QHBoxLayout()
        save = QPushButton("Save settings")
        save.setObjectName("primary")
        save.clicked.connect(self.save)
        backup = QPushButton("Back up database")
        backup.clicked.connect(self.backup)
        row.addWidget(backup)
        row.addStretch()
        row.addWidget(save)
        box.addLayout(row)
        path = QLabel(f"Database: {default_database_path()}")
        path.setObjectName("muted")
        box.addWidget(path)
        box.addStretch()

    def refresh(self):
        with session_scope() as session:
            values = {item.key: item.value for item in session.scalars(select(Setting))}
        self.currency.setCurrentText(values.get("reporting_currency", "CAD"))
        self.days.setCurrentText(values.get("default_projection_days", "30"))
        self.reserve.setValue(float(values.get("cash_reserve_amount", "0")))
        self.theme.setCurrentText(values.get("theme", "system"))
        with session_scope() as session:
            rate = latest_rate(session)
        if rate is None:
            self.fx_status.setText("No USD/CAD rate saved yet. Fetch one or enter CAD per 1 USD.")
        else:
            self.fx_status.setText(f"Latest saved: 1 USD = {rate.rate} CAD on {rate.rate_date.isoformat()} ({rate.source})")
            self.fx_rate.setValue(float(rate.rate))
            self.fx_date.setDate(QDate(rate.rate_date.year, rate.rate_date.month, rate.rate_date.day))

    def save(self):
        values = {
            "reporting_currency": self.currency.currentText(),
            "default_projection_days": self.days.currentText(),
            "cash_reserve_amount": str(self.reserve.value()),
            "theme": self.theme.currentText(),
        }
        with session_scope() as session:
            for key, value in values.items():
                setting = session.get(Setting, key)
                if setting is None:
                    session.add(Setting(key=key, value=value))
                else:
                    setting.value = value
        self.changed.emit()
        QMessageBox.information(self, "Saved", "Settings were saved.")

    def save_fx(self):
        with session_scope() as session:
            upsert_rate(session, "USD", "CAD", Decimal(str(self.fx_rate.value())),
                        self.fx_date.date().toPython(), "manual")
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Saved", "USD/CAD rate was saved.")

    def fetch_fx(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            rate, rate_date = fetch_usd_cad()
        except MarketDataError as exc:
            QMessageBox.warning(self, "Rate unavailable", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        with session_scope() as session:
            upsert_rate(session, "USD", "CAD", rate, rate_date, "api")
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Fetched", f"Saved Bank of Canada rate: 1 USD = {rate} CAD on {rate_date.isoformat()}.")

    def backup(self):
        suggested = f"finance-backup-{date.today().isoformat()}.db"
        destination, _ = QFileDialog.getSaveFileName(self, "Back up database", suggested, "SQLite database (*.db)")
        if not destination:
            return
        source = sqlite3.connect(default_database_path())
        target = sqlite3.connect(Path(destination))
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        QMessageBox.information(self, "Backup complete", f"Database backed up to:\n{destination}")
