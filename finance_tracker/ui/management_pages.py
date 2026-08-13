from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import (
    Account, Category, Debt, DebtSnapshot, IncomeSource, InvestmentAccount,
    InvestmentHolding, InvestmentSnapshot, OneTimeEvent, RecurringExpense,
    Schedule, SecurityPrice,
)
from finance_tracker.services.investment_service import PriceUnavailable, latest_price, value_holding
from finance_tracker.services.schedule_service import occurrences
from finance_tracker.ui.domain_pages import (
    DebtDialog, ExpenseDialog, HoldingDialog, IncomeDialog, InvestmentAccountDialog,
    ScheduleFields, account_choices, money_spin, titled_page,
)
from finance_tracker.utils.money import format_money


def confirm_delete(parent, description):
    return QMessageBox.question(
        parent, "Confirm deletion",
        f"Permanently delete {description}?\n\nHistorical information may also be removed. "
        "Use Enable / Disable instead when you want to preserve it.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    ) == QMessageBox.StandardButton.Yes


def selected_id(table):
    row = table.currentRow()
    if row < 0:
        QMessageBox.information(table, "Select a row", "Select a record first.")
        return None
    return table.item(row, 0).data(256)


def set_combo_data(combo, value):
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)


def fill_schedule(fields, schedule):
    fields.kind.setCurrentText(schedule.schedule_type)
    if schedule.anchor_date:
        fields.anchor.setDate(QDate(schedule.anchor_date.year, schedule.anchor_date.month, schedule.anchor_date.day))
    fields.interval.setValue(schedule.interval or 1)
    if schedule.day_of_month:
        fields.day.setValue(schedule.day_of_month)
    if schedule.month_of_year:
        fields.month.setCurrentIndex(schedule.month_of_year - 1)


def apply_schedule(schedule, fields):
    candidate = fields.create()
    schedule.schedule_type = candidate.schedule_type
    schedule.anchor_date = candidate.anchor_date
    schedule.start_date = candidate.start_date
    schedule.interval = candidate.interval
    schedule.day_of_month = candidate.day_of_month
    schedule.month_of_year = candidate.month_of_year


class ManagedPage(QWidget):
    changed = Signal()
    model = None

    def controls(self, box, add_callback, edit_callback, delete_callback):
        row = QHBoxLayout()
        row.addStretch()
        toggle = QPushButton("Enable / disable")
        toggle.clicked.connect(self.toggle)
        edit = QPushButton("Edit")
        edit.clicked.connect(edit_callback)
        remove = QPushButton("Delete")
        remove.clicked.connect(delete_callback)
        add = QPushButton("Add")
        add.setObjectName("primary")
        add.clicked.connect(add_callback)
        for button in (toggle, edit, remove, add):
            row.addWidget(button)
        box.addLayout(row)

    def toggle(self):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            item = session.get(self.model, ident)
            item.active = not item.active
        self.refresh()
        self.changed.emit()

    def delete_record(self, description):
        ident = selected_id(self.table)
        if ident is None or not confirm_delete(self, description):
            return
        try:
            with session_scope() as session:
                item = session.get(self.model, ident)
                session.delete(item)
        except IntegrityError:
            QMessageBox.warning(
                self, "Cannot delete",
                "This record is still referenced by other financial data. Disable it, "
                "or remove the dependent records first.",
            )
            return
        self.refresh()
        self.changed.emit()


class ManagedIncomePage(ManagedPage):
    model = IncomeSource

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Income", "Create, edit, disable, or permanently delete recurring income.")
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this income source"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Amount", "Schedule", "Next date", "Destination", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
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

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            item = session.get(IncomeSource, ident)
            schedule = session.get(Schedule, item.schedule_id)
            dialog = IncomeDialog(self)
            dialog.setWindowTitle("Edit income")
            dialog.name.setText(item.name)
            dialog.amount.setValue(float(item.amount))
            dialog.currency.setCurrentText(item.currency)
            set_combo_data(dialog.account, item.destination_account_id)
            fill_schedule(dialog.schedule, schedule)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            item.name = dialog.name.text().strip()
            item.amount = Decimal(str(dialog.amount.value()))
            item.currency = dialog.currency.currentText()
            item.destination_account_id = dialog.account.currentData()
            apply_schedule(schedule, dialog.schedule)
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
                          dates[0].isoformat() if dates else "—", account.name if account else "—",
                          "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)


class ManagedExpensePage(ManagedPage):
    model = RecurringExpense

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Recurring Expenses", "Manage exact bill schedules and user-defined priorities.")
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this recurring expense"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Amount", "Category", "Priority", "Schedule", "Next date", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table)

    def category(self, session, name):
        if not name:
            return None
        item = session.scalar(select(Category).where(Category.name == name))
        if item is None:
            item = Category(name=name)
            session.add(item)
            session.flush()
        return item

    def add(self):
        dialog = ExpenseDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            schedule = dialog.schedule.create()
            session.add(schedule)
            category = self.category(session, dialog.category.text().strip())
            session.flush()
            session.add(RecurringExpense(
                name=dialog.name.text().strip(), amount=Decimal(str(dialog.amount.value())),
                currency=dialog.currency.currentText(), schedule_id=schedule.id,
                category_id=category.id if category else None, priority=dialog.priority.currentText(),
                payment_account_id=dialog.account.currentData(),
            ))
        self.refresh()
        self.changed.emit()

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            item = session.get(RecurringExpense, ident)
            schedule = session.get(Schedule, item.schedule_id)
            category = session.get(Category, item.category_id) if item.category_id else None
            dialog = ExpenseDialog(self)
            dialog.setWindowTitle("Edit recurring expense")
            dialog.name.setText(item.name)
            dialog.amount.setValue(float(item.amount))
            dialog.currency.setCurrentText(item.currency)
            dialog.category.setText(category.name if category else "")
            dialog.priority.setCurrentText(item.priority)
            set_combo_data(dialog.account, item.payment_account_id)
            fill_schedule(dialog.schedule, schedule)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            item.name = dialog.name.text().strip()
            item.amount = Decimal(str(dialog.amount.value()))
            item.currency = dialog.currency.currentText()
            category = self.category(session, dialog.category.text().strip())
            item.category_id = category.id if category else None
            item.priority = dialog.priority.currentText()
            item.payment_account_id = dialog.account.currentData()
            apply_schedule(schedule, dialog.schedule)
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
                          item.priority.title(), ScheduleFields.describe(schedule),
                          dates[0].isoformat() if dates else "—", "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)


class ManagedDebtPage(ManagedPage):
    model = Debt

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Debts", "Edit balances and repayment terms or preserve them by disabling.")
        self.total = QLabel()
        self.total.setObjectName("metric")
        box.addWidget(self.total)
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this debt and its snapshots"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Balance", "Rate", "Minimum", "Schedule", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
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
                interest_rate=Decimal(str(dialog.rate.value())) / Decimal("100") if dialog.rate.value() else None,
                minimum_payment=Decimal(str(dialog.payment.value())),
                payment_schedule_id=schedule.id, payment_account_id=dialog.account.currentData(),
            ))
        self.refresh()
        self.changed.emit()

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            item = session.get(Debt, ident)
            schedule = session.get(Schedule, item.payment_schedule_id)
            dialog = DebtDialog(self)
            dialog.setWindowTitle("Edit debt")
            dialog.name.setText(item.name)
            dialog.kind.setCurrentText(item.debt_type)
            dialog.balance.setValue(float(item.current_balance))
            dialog.currency.setCurrentText(item.currency)
            dialog.rate.setValue(float((item.interest_rate or 0) * 100))
            dialog.payment.setValue(float(item.minimum_payment or 0))
            set_combo_data(dialog.account, item.payment_account_id)
            fill_schedule(dialog.schedule, schedule)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            item.name = dialog.name.text().strip()
            item.debt_type = dialog.kind.currentText()
            item.current_balance = Decimal(str(dialog.balance.value()))
            item.currency = dialog.currency.currentText()
            item.interest_rate = Decimal(str(dialog.rate.value())) / Decimal("100") if dialog.rate.value() else None
            item.minimum_payment = Decimal(str(dialog.payment.value()))
            item.payment_account_id = dialog.account.currentData()
            apply_schedule(schedule, dialog.schedule)
        self.refresh()
        self.changed.emit()

    def delete_record(self, description):
        ident = selected_id(self.table)
        if ident is None or not confirm_delete(self, description):
            return
        with session_scope() as session:
            session.execute(delete(DebtSnapshot).where(DebtSnapshot.debt_id == ident))
            session.delete(session.get(Debt, ident))
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(Debt).order_by(Debt.active.desc(), Debt.name)).all()
            cad = sum((item.current_balance for item in items if item.active and item.currency == "CAD"), Decimal("0"))
            self.total.setText(f"CAD debt: {format_money(cad)}")
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                schedule = session.get(Schedule, item.payment_schedule_id) if item.payment_schedule_id else None
                values = (item.name, item.debt_type.replace("_", " ").title(),
                          format_money(item.current_balance, item.currency),
                          f"{item.interest_rate * 100:.2f}%" if item.interest_rate is not None else "—",
                          format_money(item.minimum_payment or Decimal("0"), item.currency),
                          ScheduleFields.describe(schedule) if schedule else "—",
                          "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)


class EventDialog(QDialog):
    def __init__(self, event=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit one-time event" if event else "Add one-time event")
        form = QFormLayout(self)
        self.name = QLineEdit(event.name if event else "")
        self.kind = QComboBox()
        self.kind.addItems(["expense", "income"])
        self.amount = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.on_date = QDateEdit(QDate.currentDate())
        self.on_date.setCalendarPopup(True)
        self.account = QComboBox()
        account_choices(self.account)
        if event:
            self.kind.setCurrentText(event.event_type)
            self.amount.setValue(float(event.amount))
            self.currency.setCurrentText(event.currency)
            self.on_date.setDate(QDate(event.event_date.year, event.event_date.month, event.event_date.day))
            set_combo_data(self.account, event.account_id)
        for label, field in (("Name", self.name), ("Type", self.kind), ("Amount", self.amount),
                             ("Currency", self.currency), ("Date", self.on_date), ("Account", self.account)):
            form.addRow(label, field)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class EventPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(self, "One-Time Events", "Future income and expenses that occur on one exact date.")
        row = QHBoxLayout()
        row.addStretch()
        edit = QPushButton("Edit")
        edit.clicked.connect(self.edit)
        remove = QPushButton("Delete")
        remove.clicked.connect(self.remove)
        add = QPushButton("Add event")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        for button in (edit, remove, add):
            row.addWidget(button)
        box.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Name", "Date", "Type", "Amount", "Account"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table)

    def save_dialog(self, event=None):
        dialog = EventDialog(event, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        if not dialog.name.text().strip():
            QMessageBox.warning(self, "Name required", "Enter an event name.")
            return False
        values = dict(name=dialog.name.text().strip(), event_type=dialog.kind.currentText(),
                      amount=Decimal(str(dialog.amount.value())), currency=dialog.currency.currentText(),
                      event_date=dialog.on_date.date().toPython(), account_id=dialog.account.currentData())
        if event is None:
            with session_scope() as session:
                session.add(OneTimeEvent(**values))
        else:
            with session_scope() as session:
                target = session.get(OneTimeEvent, event.id)
                for key, value in values.items():
                    setattr(target, key, value)
        return True

    def add(self):
        if self.save_dialog():
            self.refresh()
            self.changed.emit()

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            event = session.get(OneTimeEvent, ident)
            session.expunge(event)
        if self.save_dialog(event):
            self.refresh()
            self.changed.emit()

    def remove(self):
        ident = selected_id(self.table)
        if ident is None or not confirm_delete(self, "this one-time event"):
            return
        with session_scope() as session:
            session.delete(session.get(OneTimeEvent, ident))
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(OneTimeEvent).order_by(OneTimeEvent.event_date)).all()
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                account = session.get(Account, item.account_id) if item.account_id else None
                values = (item.name, item.event_date.isoformat(), item.event_type.title(),
                          format_money(item.amount, item.currency), account.name if account else "—")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)


class InvestmentManagementPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Investments", "Manage accounts, holdings, quantities, and manual prices.")
        account_row = QHBoxLayout()
        account_row.addWidget(QLabel("Investment accounts"))
        account_row.addStretch()
        for text, handler in (("Edit account", self.edit_account), ("Delete account", self.delete_account), ("Add account", self.add_account)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            account_row.addWidget(button)
        box.addLayout(account_row)
        self.accounts = QTableWidget(0, 4)
        self.accounts.setHorizontalHeaderLabels(["Name", "Type", "Cash", "Status"])
        self.accounts.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.accounts.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.accounts.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        box.addWidget(self.accounts)
        holding_row = QHBoxLayout()
        holding_row.addWidget(QLabel("Holdings"))
        holding_row.addStretch()
        for text, handler in (("Edit holding / price", self.edit_holding), ("Delete holding", self.delete_holding), ("Add holding", self.add_holding)):
            button = QPushButton(text)
            if text == "Add holding":
                button.setObjectName("primary")
            button.clicked.connect(handler)
            holding_row.addWidget(button)
        box.addLayout(holding_row)
        self.holdings = QTableWidget(0, 6)
        self.holdings.setHorizontalHeaderLabels(["Symbol", "Account", "Units", "Price", "Native value", "CAD value"])
        self.holdings.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.holdings.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.holdings.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        box.addWidget(self.holdings)

    def add_account(self):
        dialog = InvestmentAccountDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            session.add(InvestmentAccount(name=dialog.name.text().strip(), account_type=dialog.kind.currentText(),
                                          cash_balance=Decimal(str(dialog.cash.value())),
                                          cash_currency=dialog.currency.currentText()))
        self.refresh()
        self.changed.emit()

    def edit_account(self):
        ident = selected_id(self.accounts)
        if ident is None:
            return
        with session_scope() as session:
            account = session.get(InvestmentAccount, ident)
            dialog = InvestmentAccountDialog(self)
            dialog.setWindowTitle("Edit investment account")
            dialog.name.setText(account.name)
            dialog.kind.setCurrentText(account.account_type)
            dialog.cash.setValue(float(account.cash_balance))
            dialog.currency.setCurrentText(account.cash_currency)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            account.name = dialog.name.text().strip()
            account.account_type = dialog.kind.currentText()
            account.cash_balance = Decimal(str(dialog.cash.value()))
            account.cash_currency = dialog.currency.currentText()
        self.refresh()
        self.changed.emit()

    def delete_account(self):
        ident = selected_id(self.accounts)
        if ident is None or not confirm_delete(self, "this investment account and all its holdings/snapshots"):
            return
        with session_scope() as session:
            session.execute(delete(InvestmentSnapshot).where(InvestmentSnapshot.investment_account_id == ident))
            session.execute(delete(InvestmentHolding).where(InvestmentHolding.investment_account_id == ident))
            session.delete(session.get(InvestmentAccount, ident))
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
            session.add(SecurityPrice(symbol=symbol, price=Decimal(str(dialog.price.value())),
                                      currency=dialog.currency.currentText(),
                                      price_date=dialog.price_date.date().toPython()))
        self.refresh()
        self.changed.emit()

    def edit_holding(self):
        ident = selected_id(self.holdings)
        if ident is None:
            return
        with session_scope() as session:
            holding = session.get(InvestmentHolding, ident)
            price = latest_price(session, holding.symbol)
            dialog = HoldingDialog(self)
            dialog.setWindowTitle("Edit holding and add current price")
            set_combo_data(dialog.account, holding.investment_account_id)
            dialog.symbol.setText(holding.symbol)
            dialog.name.setText(holding.name)
            dialog.asset.setCurrentText(holding.asset_type)
            dialog.quantity.setValue(float(holding.quantity))
            dialog.price.setValue(float(price.price))
            dialog.currency.setCurrentText(price.currency)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            holding.investment_account_id = dialog.account.currentData()
            holding.symbol = dialog.symbol.text().strip().upper()
            holding.name = dialog.name.text().strip()
            holding.asset_type = dialog.asset.currentText()
            holding.quantity = Decimal(str(dialog.quantity.value()))
            holding.quote_currency = dialog.currency.currentText()
            session.add(SecurityPrice(symbol=holding.symbol, price=Decimal(str(dialog.price.value())),
                                      currency=dialog.currency.currentText(),
                                      price_date=dialog.price_date.date().toPython()))
        self.refresh()
        self.changed.emit()

    def delete_holding(self):
        ident = selected_id(self.holdings)
        if ident is None or not confirm_delete(self, "this holding"):
            return
        with session_scope() as session:
            session.delete(session.get(InvestmentHolding, ident))
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            accounts = session.scalars(select(InvestmentAccount).order_by(InvestmentAccount.active.desc(), InvestmentAccount.name)).all()
            self.accounts.setRowCount(len(accounts))
            for row, account in enumerate(accounts):
                values = (account.name, account.account_type.upper(),
                          format_money(account.cash_balance, account.cash_currency),
                          "Active" if account.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, account.id)
                    self.accounts.setItem(row, col, cell)
            holdings = session.scalars(select(InvestmentHolding).order_by(InvestmentHolding.symbol)).all()
            self.holdings.setRowCount(len(holdings))
            for row, holding in enumerate(holdings):
                account = session.get(InvestmentAccount, holding.investment_account_id)
                try:
                    price = latest_price(session, holding.symbol)
                    value = value_holding(session, holding)
                    values = (holding.symbol, account.name, f"{holding.quantity:f}",
                              format_money(price.price, price.currency),
                              format_money(value.native_value, value.native_currency),
                              format_money(value.reporting_value))
                except (PriceUnavailable, LookupError) as exc:
                    values = (holding.symbol, account.name, f"{holding.quantity:f}", "Missing", "—", str(exc))
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, holding.id)
                    self.holdings.setItem(row, col, cell)
