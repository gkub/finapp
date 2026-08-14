from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import (
    Account, Category, Debt, DebtSnapshot, Deposit, IncomeSource, InvestmentAccount,
    InvestmentHolding, InvestmentSnapshot, MaterialAsset, OneTimeEvent, RecurringExpense,
    Schedule,
)
from finance_tracker.services.balance_service import record_debt_paydown, update_material_asset_value
from finance_tracker.services.currency_service import upsert_rate
from finance_tracker.services.investment_service import PriceUnavailable, latest_price, upsert_price, value_holding
from finance_tracker.services.market_data import MarketDataError, fetch_quote as download_quote, fetch_usd_cad
from finance_tracker.services.schedule_service import occurrences
from finance_tracker.ui.domain_pages import (
    DebtDialog, DepositDialog, ExpenseDialog, HoldingDialog, IncomeDialog, InvestmentAccountDialog,
    MaterialAssetDialog, ScheduleFields, account_choices, configure_table, debt_choices, destination_ids,
    destination_label, fit_table_columns, money_spin, payment_method_choices, payment_method_ids,
    payment_method_label, set_destination, set_payment_method, titled_page,
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

    def controls(self, box, add_callback, edit_callback, delete_callback, extras=()):
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
        for button in (toggle, edit, remove, *extras, add):
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
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
            fit_table_columns(self.table)


class ManagedDepositPage(ManagedPage):
    model = Deposit

    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Deposits",
            "Move money into a bank or TFSA/FHSA/RRSP on a schedule. One-time is a schedule type. "
            "This is a plan: update chequing and the destination when you actually send it. "
            "Buying stocks stays manual on Investments.",
        )
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this deposit"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Amount", "From", "To", "Schedule", "Next date", "Status"])
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table)

    def add(self):
        dialog = DepositDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dest_account, dest_investment = destination_ids(dialog.destination)
        if dest_account is None and dest_investment is None:
            QMessageBox.warning(self, "Destination required", "Choose the account this deposit goes to.")
            return
        with session_scope() as session:
            schedule = dialog.schedule.create()
            session.add(schedule)
            session.flush()
            session.add(Deposit(
                name=dialog.name.text().strip(), amount=Decimal(str(dialog.amount.value())),
                currency=dialog.currency.currentText(), schedule_id=schedule.id,
                source_account_id=dialog.source.currentData(),
                destination_account_id=dest_account, destination_investment_id=dest_investment,
            ))
        self.refresh()
        self.changed.emit()

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            item = session.get(Deposit, ident)
            schedule = session.get(Schedule, item.schedule_id)
            dialog = DepositDialog(self)
            dialog.setWindowTitle("Edit deposit")
            dialog.name.setText(item.name)
            dialog.amount.setValue(float(item.amount))
            dialog.currency.setCurrentText(item.currency)
            set_combo_data(dialog.source, item.source_account_id)
            set_destination(dialog.destination, item.destination_account_id, item.destination_investment_id)
            fill_schedule(dialog.schedule, schedule)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            dest_account, dest_investment = destination_ids(dialog.destination)
            if dest_account is None and dest_investment is None:
                QMessageBox.warning(self, "Destination required", "Choose the account this deposit goes to.")
                return
            item.name = dialog.name.text().strip()
            item.amount = Decimal(str(dialog.amount.value()))
            item.currency = dialog.currency.currentText()
            item.source_account_id = dialog.source.currentData()
            item.destination_account_id = dest_account
            item.destination_investment_id = dest_investment
            apply_schedule(schedule, dialog.schedule)
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(Deposit).order_by(Deposit.active.desc(), Deposit.name)).all()
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                schedule = session.get(Schedule, item.schedule_id)
                dates = occurrences(schedule, date.today(), date.today().replace(year=date.today().year + 2))
                source = session.get(Account, item.source_account_id) if item.source_account_id else None
                values = (
                    item.name, format_money(item.amount, item.currency),
                    source.name if source else "New money",
                    destination_label(session, item.destination_account_id, item.destination_investment_id),
                    ScheduleFields.describe(schedule),
                    dates[0].isoformat() if dates else "—",
                    "Active" if item.active else "Disabled",
                )
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class ManagedExpensePage(ManagedPage):
    model = RecurringExpense

    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Recurring Expenses",
            "Bank-paid bills hit cash flow. Charges to a credit card wait until you pay the card.",
        )
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this recurring expense"))
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Name", "Amount", "Category", "Priority", "Paid from", "Schedule", "Next date", "Status"]
        )
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
            account_id, debt_id = payment_method_ids(dialog.account)
            session.add(RecurringExpense(
                name=dialog.name.text().strip(), amount=Decimal(str(dialog.amount.value())),
                currency=dialog.currency.currentText(), schedule_id=schedule.id,
                category_id=category.id if category else None, priority=dialog.priority.currentText(),
                payment_account_id=account_id, payment_debt_id=debt_id,
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
            set_payment_method(dialog.account, item.payment_account_id, item.payment_debt_id)
            fill_schedule(dialog.schedule, schedule)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            item.name = dialog.name.text().strip()
            item.amount = Decimal(str(dialog.amount.value()))
            item.currency = dialog.currency.currentText()
            category = self.category(session, dialog.category.text().strip())
            item.category_id = category.id if category else None
            item.priority = dialog.priority.currentText()
            item.payment_account_id, item.payment_debt_id = payment_method_ids(dialog.account)
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
                          item.priority.title(),
                          payment_method_label(session, item.payment_account_id, item.payment_debt_id),
                          ScheduleFields.describe(schedule),
                          dates[0].isoformat() if dates else "—", "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class ManagedDebtPage(ManagedPage):
    model = Debt

    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Debts",
            "Loans can keep a scheduled payment. Cards and anything you pay by feel use Pay down: "
            "today or earlier moves cash and the debt; a future date is only a plan.",
        )
        self.total = QLabel()
        self.total.setObjectName("metric")
        box.addWidget(self.total)
        pay = QPushButton("Pay down")
        pay.clicked.connect(self.pay_down)
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this debt and its snapshots"), extras=(pay,))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Balance", "Rate", "Scheduled", "Schedule", "Status"])
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
                interest_rate=dialog.annual_rate(),
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
            dialog.set_annual_rate(item.interest_rate)
            dialog.payment.setValue(float(item.minimum_payment or 0))
            set_combo_data(dialog.account, item.payment_account_id)
            fill_schedule(dialog.schedule, schedule)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            item.name = dialog.name.text().strip()
            item.debt_type = dialog.kind.currentText()
            item.current_balance = Decimal(str(dialog.balance.value()))
            item.currency = dialog.currency.currentText()
            item.interest_rate = dialog.annual_rate()
            item.minimum_payment = Decimal(str(dialog.payment.value()))
            item.payment_account_id = dialog.account.currentData()
            apply_schedule(schedule, dialog.schedule)
        self.refresh()
        self.changed.emit()

    def pay_down(self):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            debt = session.get(Debt, ident)
            dialog = PaydownDialog(debt, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            amount = Decimal(str(dialog.amount.value()))
            if amount <= 0:
                QMessageBox.warning(self, "Amount required", "Enter a payment amount.")
                return
            account = session.get(Account, dialog.account.currentData())
            if account is None:
                QMessageBox.warning(self, "Account required", "Choose the bank account this payment comes from.")
                return
            on_date = dialog.on_date.date().toPython()
            record_debt_paydown(session, debt, amount, on_date, account)
            applied = on_date <= date.today()
        self.refresh()
        self.changed.emit()
        if applied:
            QMessageBox.information(self, "Paid", "Cash and this debt were updated. A snapshot was saved.")
        else:
            QMessageBox.information(
                self, "Planned",
                "This payment is on the calendar. Balances stay until that date; "
                "use Pay down again that day to book it.",
            )

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
                          f"{item.interest_rate * 100:.2f}% / yr" if item.interest_rate is not None else "—",
                          format_money(item.minimum_payment, item.currency) if item.minimum_payment else "—",
                          ScheduleFields.describe(schedule) if schedule else "—",
                          "Active" if item.active else "Disabled")
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class ManagedAssetPage(ManagedPage):
    model = MaterialAsset

    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Material Assets",
            "Cars, property, and other stuff you own. Estimated resale value counts in net worth. "
            "The loan on a car stays on Debts.",
        )
        self.total = QLabel()
        self.total.setObjectName("metric")
        box.addWidget(self.total)
        self.controls(box, self.add, self.edit, lambda: self.delete_record("this asset and its value history"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Estimated value", "Net worth", "Notes", "Status"])
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table)

    def add(self):
        dialog = MaterialAssetDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            asset = MaterialAsset(
                name=dialog.name.text().strip(), asset_type=dialog.kind.currentText(),
                current_value=Decimal(str(dialog.value.value())), currency=dialog.currency.currentText(),
                include_in_net_worth=dialog.net.isChecked(),
                notes=dialog.notes.text().strip() or None,
            )
            session.add(asset)
            session.flush()
            update_material_asset_value(session, asset, asset.current_value, date.today())
        self.refresh()
        self.changed.emit()

    def edit(self, *_):
        ident = selected_id(self.table)
        if ident is None:
            return
        with session_scope() as session:
            item = session.get(MaterialAsset, ident)
            dialog = MaterialAssetDialog(self)
            dialog.setWindowTitle("Edit asset")
            dialog.name.setText(item.name)
            dialog.kind.setCurrentText(item.asset_type)
            dialog.value.setValue(float(item.current_value))
            dialog.currency.setCurrentText(item.currency)
            dialog.net.setChecked(item.include_in_net_worth)
            dialog.notes.setText(item.notes or "")
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            item.name = dialog.name.text().strip()
            item.asset_type = dialog.kind.currentText()
            item.currency = dialog.currency.currentText()
            item.include_in_net_worth = dialog.net.isChecked()
            item.notes = dialog.notes.text().strip() or None
            update_material_asset_value(session, item, Decimal(str(dialog.value.value())), date.today())
        self.refresh()
        self.changed.emit()

    def refresh(self):
        with session_scope() as session:
            items = session.scalars(select(MaterialAsset).order_by(MaterialAsset.active.desc(), MaterialAsset.name)).all()
            cad = sum(
                (item.current_value for item in items if item.active and item.include_in_net_worth and item.currency == "CAD"),
                Decimal("0"),
            )
            self.total.setText(f"CAD assets in net worth: {format_money(cad)}")
            self.table.setRowCount(len(items))
            for row, item in enumerate(items):
                values = (
                    item.name, item.asset_type.replace("_", " ").title(),
                    format_money(item.current_value, item.currency),
                    "Yes" if item.include_in_net_worth else "No",
                    item.notes or "—",
                    "Active" if item.active else "Disabled",
                )
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class PaydownDialog(QDialog):
    def __init__(self, debt, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Pay down {debt.name}")
        self.setMinimumWidth(400)
        form = QFormLayout(self)
        self.amount = money_spin()
        self.amount.setValue(float(max(debt.current_balance, Decimal("0"))))
        self.on_date = QDateEdit(QDate.currentDate())
        self.on_date.setCalendarPopup(True)
        self.account = QComboBox()
        account_choices(self.account, include_blank=False)
        set_combo_data(self.account, debt.payment_account_id)
        form.addRow("Amount", self.amount)
        form.addRow("Date", self.on_date)
        form.addRow("Paid from", self.account)
        note = QLabel("Today or earlier moves cash and the debt now. A later date is a plan for Cash Flow and Outlook.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class EventDialog(QDialog):
    def __init__(self, event=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit one-time event" if event else "Add one-time event")
        form = QFormLayout(self)
        self.form = form
        self.name = QLineEdit(event.name if event else "")
        self.kind = QComboBox()
        self.kind.addItem("expense", "expense")
        self.kind.addItem("income", "income")
        self.kind.addItem("debt payment", "debt_payment")
        self.amount = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.on_date = QDateEdit(QDate.currentDate())
        self.on_date.setCalendarPopup(True)
        self.account = QComboBox()
        payment_method_choices(self.account)
        self.debt = QComboBox()
        debt_choices(self.debt)
        self.from_account = QComboBox()
        account_choices(self.from_account)
        if event:
            index = self.kind.findData(event.event_type)
            if index >= 0:
                self.kind.setCurrentIndex(index)
            self.amount.setValue(float(event.amount))
            self.currency.setCurrentText(event.currency)
            self.on_date.setDate(QDate(event.event_date.year, event.event_date.month, event.event_date.day))
            set_payment_method(self.account, event.account_id, event.payment_debt_id)
            set_combo_data(self.debt, event.payment_debt_id)
            set_combo_data(self.from_account, event.account_id)
        form.addRow("Name", self.name)
        form.addRow("Type", self.kind)
        form.addRow("Amount", self.amount)
        form.addRow("Currency", self.currency)
        form.addRow("Date", self.on_date)
        form.addRow("Paid from / charged to", self.account)
        form.addRow("Debt", self.debt)
        form.addRow("Paid from", self.from_account)
        self.kind.currentIndexChanged.connect(self.sync_kind)
        self.sync_kind()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def sync_kind(self):
        paydown = self.kind.currentData() == "debt_payment"
        self.form.setRowVisible(self.account, not paydown)
        self.form.setRowVisible(self.debt, paydown)
        self.form.setRowVisible(self.from_account, paydown)

    def values(self):
        if self.kind.currentData() == "debt_payment":
            return dict(
                name=self.name.text().strip(),
                event_type="debt_payment",
                amount=Decimal(str(self.amount.value())),
                currency=self.currency.currentText(),
                event_date=self.on_date.date().toPython(),
                account_id=self.from_account.currentData(),
                payment_debt_id=self.debt.currentData(),
            )
        account_id, debt_id = payment_method_ids(self.account)
        return dict(
            name=self.name.text().strip(),
            event_type=self.kind.currentData(),
            amount=Decimal(str(self.amount.value())),
            currency=self.currency.currentText(),
            event_date=self.on_date.date().toPython(),
            account_id=account_id,
            payment_debt_id=debt_id,
        )


class EventPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "One-Time Events",
            "Bank-paid events hit cash. Card charges wait until you pay the card. "
            "Debt payments here are plans; Debts → Pay down books them against cash and the balance.",
        )
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
        self.table.setHorizontalHeaderLabels(["Name", "Date", "Type", "Amount", "Paid from"])
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table)

    def save_dialog(self, event=None):
        dialog = EventDialog(event, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        values = dialog.values()
        if not values["name"]:
            QMessageBox.warning(self, "Name required", "Enter an event name.")
            return False
        if values["event_type"] == "debt_payment" and (not values["payment_debt_id"] or not values["account_id"]):
            QMessageBox.warning(self, "Payment details", "Choose the debt and the bank account it is paid from.")
            return False
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
                if item.event_type == "debt_payment":
                    paid = payment_method_label(session, item.account_id)
                    target = session.get(Debt, item.payment_debt_id) if item.payment_debt_id else None
                    paid_label = f"{paid} → {target.name}" if target else paid
                    status = "Booked" if item.applied else "Planned"
                    kind = f"Debt payment ({status.lower()})"
                else:
                    paid_label = payment_method_label(session, item.account_id, item.payment_debt_id)
                    kind = item.event_type.replace("_", " ").title()
                values = (item.name, item.event_date.isoformat(), kind,
                          format_money(item.amount, item.currency), paid_label)
                for col, value in enumerate(values):
                    cell = QTableWidgetItem(value)
                    if col == 0:
                        cell.setData(256, item.id)
                    self.table.setItem(row, col, cell)
            fit_table_columns(self.table)


class InvestmentManagementPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(self, "Investments", "Manual prices, or fetch quotes and USD/CAD when you are online.")
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
        configure_table(self.accounts)
        self.accounts.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        box.addWidget(self.accounts)
        holding_row = QHBoxLayout()
        holding_row.addWidget(QLabel("Holdings"))
        holding_row.addStretch()
        fetch = QPushButton("Fetch quotes & FX")
        fetch.clicked.connect(self.fetch_market_data)
        holding_row.addWidget(fetch)
        for text, handler in (("Edit holding / price", self.edit_holding), ("Delete holding", self.delete_holding), ("Add holding", self.add_holding)):
            button = QPushButton(text)
            if text == "Add holding":
                button.setObjectName("primary")
            button.clicked.connect(handler)
            holding_row.addWidget(button)
        box.addLayout(holding_row)
        self.holdings = QTableWidget(0, 6)
        self.holdings.setHorizontalHeaderLabels(["Symbol", "Account", "Units", "Price", "Native value", "CAD value"])
        configure_table(self.holdings)
        self.holdings.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
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
            upsert_price(session, symbol, Decimal(str(dialog.price.value())),
                         dialog.currency.currentText(), dialog.price_date.date().toPython())
        self.refresh()
        self.changed.emit()

    def edit_holding(self):
        ident = selected_id(self.holdings)
        if ident is None:
            return
        with session_scope() as session:
            holding = session.get(InvestmentHolding, ident)
            try:
                price = latest_price(session, holding.symbol)
                price_value, price_currency = float(price.price), price.currency
            except PriceUnavailable:
                price_value, price_currency = 0.0, holding.quote_currency
            snapshot = dict(
                account_id=holding.investment_account_id, symbol=holding.symbol, name=holding.name,
                asset_type=holding.asset_type, quantity=float(holding.quantity),
                price=price_value, currency=price_currency,
            )
        dialog = HoldingDialog(self)
        dialog.setWindowTitle("Edit holding and add current price")
        set_combo_data(dialog.account, snapshot["account_id"])
        dialog.symbol.setText(snapshot["symbol"])
        dialog.name.setText(snapshot["name"])
        dialog.asset.setCurrentText(snapshot["asset_type"])
        dialog.quantity.setValue(snapshot["quantity"])
        dialog.price.setValue(snapshot["price"])
        dialog.currency.setCurrentText(snapshot["currency"])
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            holding = session.get(InvestmentHolding, ident)
            holding.investment_account_id = dialog.account.currentData()
            holding.symbol = dialog.symbol.text().strip().upper()
            holding.name = dialog.name.text().strip()
            holding.asset_type = dialog.asset.currentText()
            holding.quantity = Decimal(str(dialog.quantity.value()))
            holding.quote_currency = dialog.currency.currentText()
            upsert_price(session, holding.symbol, Decimal(str(dialog.price.value())),
                         dialog.currency.currentText(), dialog.price_date.date().toPython())
        self.refresh()
        self.changed.emit()

    def fetch_market_data(self):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        notes = []
        try:
            try:
                rate, rate_date = fetch_usd_cad()
                with session_scope() as session:
                    upsert_rate(session, "USD", "CAD", rate, rate_date, "api")
                notes.append(f"USD/CAD {rate} on {rate_date.isoformat()}")
            except MarketDataError as exc:
                notes.append(f"USD/CAD: {exc}")
            with session_scope() as session:
                symbols = sorted({item.symbol for item in session.scalars(select(InvestmentHolding).where(InvestmentHolding.active.is_(True)))})
            for symbol in symbols:
                try:
                    price, currency, price_date = download_quote(symbol)
                    with session_scope() as session:
                        upsert_price(session, symbol, price, currency, price_date, "api")
                    notes.append(f"{symbol}: {price} {currency}")
                except MarketDataError as exc:
                    notes.append(f"{symbol}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()
        self.changed.emit()
        QMessageBox.information(self, "Market data", "\n".join(notes) if notes else "No holdings to update.")

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
            fit_table_columns(self.accounts)
            fit_table_columns(self.holdings)
