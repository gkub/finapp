from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QWidget,
)
from sqlalchemy import select

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import Account, Category, SpendingEntry
from finance_tracker.services.spending_service import monthly_period, summarize_spending
from finance_tracker.ui.domain_pages import configure_table, fit_table_columns, money_spin, projection_prefs, titled_page
from finance_tracker.utils.money import format_money, format_signed

_USER_ID = 256


class SpendingDialog(QDialog):
    def __init__(self, entry: SpendingEntry | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit spending check-in" if entry else "Add spending check-in")
        self.setMinimumWidth(430)
        form = QFormLayout(self)
        self.description = QLineEdit(entry.description or "" if entry else "")
        self.entry_type = QComboBox()
        self.entry_type.addItem("General spending", "general")
        self.entry_type.addItem("Category total", "category")
        self.entry_type.addItem("Notable purchase", "notable")
        self.amount = money_spin()
        self.currency = QComboBox()
        self.currency.addItems(["CAD", "USD"])
        self.entry_date = QDateEdit(QDate.currentDate())
        self.entry_date.setCalendarPopup(True)
        self.category = QComboBox()
        self.category.addItem("Uncategorized", None)
        self.account = QComboBox()
        self.account.addItem("Any / not specified", None)
        with session_scope() as session:
            for item in session.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.name)):
                self.category.addItem(item.name, item.id)
            for item in session.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)):
                self.account.addItem(item.name, item.id)
        if entry:
            self.entry_type.setCurrentIndex(max(self.entry_type.findData(entry.entry_type), 0))
            self.amount.setValue(float(entry.amount))
            self.currency.setCurrentText(entry.currency)
            self.entry_date.setDate(QDate(entry.entry_date.year, entry.entry_date.month, entry.entry_date.day))
            category_index = self.category.findData(entry.category_id)
            account_index = self.account.findData(entry.account_id)
            self.category.setCurrentIndex(max(category_index, 0))
            self.account.setCurrentIndex(max(account_index, 0))
        form.addRow("What was it?", self.description)
        form.addRow("Entry type", self.entry_type)
        form.addRow("Amount", self.amount)
        form.addRow("Currency", self.currency)
        form.addRow("Date", self.entry_date)
        form.addRow("Category (optional)", self.category)
        form.addRow("Account (optional)", self.account)
        note = QLabel("This allocates the general-spending estimate; it does not reduce the bank balance again.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _validate(self):
        if self.amount.value() <= 0:
            QMessageBox.warning(self, "Amount required", "Enter an amount greater than zero.")
            return
        self.accept()

    def values(self):
        return {
            "description": self.description.text().strip() or None,
            "entry_type": self.entry_type.currentData(),
            "amount": Decimal(str(self.amount.value())),
            "currency": self.currency.currentText(),
            "entry_date": self.entry_date.date().toPython(),
            "category_id": self.category.currentData(),
            "account_id": self.account.currentData(),
        }


class SpendingPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Spending",
            "No itemized bookkeeping required. General spending is estimated from balance updates after known cash flows.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("From"))
        start, end = monthly_period()
        self.start = QDateEdit(QDate(start.year, start.month, start.day))
        self.start.setCalendarPopup(True)
        controls.addWidget(self.start)
        controls.addWidget(QLabel("To"))
        self.end = QDateEdit(QDate(end.year, end.month, end.day))
        self.end.setCalendarPopup(True)
        controls.addWidget(self.end)
        controls.addStretch()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        controls.addWidget(refresh)
        box.addLayout(controls)

        summary = QGridLayout()
        self.metrics = {}
        for index, (key, title) in enumerate((
            ("known", "Known spending"), ("general", "Estimated general"),
            ("total", "Total observed"), ("unallocated", "Still uncategorized"),
            ("previous", "Previous comparable period"), ("change", "Change"),
        )):
            title_label = QLabel(title)
            title_label.setObjectName("muted")
            value = QLabel("—")
            value.setObjectName("metric")
            cell = QWidget()
            cell_box = QFormLayout(cell)
            cell_box.setContentsMargins(10, 8, 10, 8)
            cell_box.addRow(title_label)
            cell_box.addRow(value)
            summary.addWidget(cell, index // 3, index % 3)
            self.metrics[key] = value
        box.addLayout(summary)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        box.addWidget(self.status)

        actions = QHBoxLayout()
        actions.addWidget(QLabel("Optional check-ins and notable purchases"))
        actions.addStretch()
        edit = QPushButton("Edit")
        edit.clicked.connect(self.edit)
        remove = QPushButton("Delete")
        remove.clicked.connect(self.remove)
        add = QPushButton("Add check-in")
        add.setObjectName("primary")
        add.clicked.connect(self.add)
        for button in (edit, remove, add):
            actions.addWidget(button)
        box.addLayout(actions)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Date", "Description", "Type", "Category", "Account", "Amount"])
        configure_table(self.table)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
        box.addWidget(self.table, 1)
        self.start.dateChanged.connect(self.refresh)
        self.end.dateChanged.connect(self.refresh)

    def _dates(self):
        return self.start.date().toPython(), self.end.date().toPython()

    def refresh(self):
        start, end = self._dates()
        if end < start:
            self.status.setText("The end date must not be before the start date.")
            return
        try:
            with session_scope() as session:
                _, _, currency = projection_prefs(session)
                current = summarize_spending(session, start, end, currency)
                span = end - start
                prior_end = start - timedelta(days=1)
                prior_start = prior_end - span
                previous = summarize_spending(session, prior_start, prior_end, currency)
                values = {
                    "known": current.known_spending,
                    "general": current.estimated_general_spending,
                    "total": current.total_spending,
                    "unallocated": current.unallocated_general_spending,
                    "previous": previous.total_spending,
                    "change": current.total_spending - previous.total_spending,
                }
                for key, value in values.items():
                    self.metrics[key].setText("—" if value is None else (format_signed(value, currency) if key == "change" else format_money(value, currency)))
                if current.has_balance_observation:
                    self.status.setText(
                        f"Estimated from balance updates dated {current.observed_start} through {current.observed_end}. "
                        "Known transfers, deposits, debt payments, income, and bills are reconciled before general spending is inferred."
                    )
                else:
                    self.status.setText(
                        "Two balance-update dates are needed for an automatic general-spending estimate. "
                        "Use Update Finances periodically; check-ins remain optional."
                    )
                entries = session.scalars(select(SpendingEntry).where(
                    SpendingEntry.entry_date.between(start, end),
                ).order_by(SpendingEntry.entry_date.desc(), SpendingEntry.id.desc())).all()
                self.table.setRowCount(len(entries))
                for row, entry in enumerate(entries):
                    category = session.get(Category, entry.category_id) if entry.category_id else None
                    account = session.get(Account, entry.account_id) if entry.account_id else None
                    values = (entry.entry_date.isoformat(), entry.description or "General spending",
                              entry.entry_type.replace("_", " ").title(), category.name if category else "—",
                              account.name if account else "—", format_money(entry.amount, entry.currency))
                    for column, text in enumerate(values):
                        item = QTableWidgetItem(text)
                        if column == 0:
                            item.setData(_USER_ID, entry.id)
                        self.table.setItem(row, column, item)
                fit_table_columns(self.table)
        except Exception as exc:
            self.status.setText(f"Spending summary unavailable: {exc}")

    def _selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select a row", "Select a check-in first.")
            return None
        return self.table.item(row, 0).data(_USER_ID)

    def add(self):
        dialog = SpendingDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            session.add(SpendingEntry(**dialog.values()))
        self.refresh()
        self.changed.emit()

    def edit(self, *_):
        ident = self._selected_id()
        if ident is None:
            return
        with session_scope() as session:
            entry = session.get(SpendingEntry, ident)
            session.expunge(entry)
        dialog = SpendingDialog(entry, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        with session_scope() as session:
            target = session.get(SpendingEntry, ident)
            for key, value in dialog.values().items():
                setattr(target, key, value)
        self.refresh()
        self.changed.emit()

    def remove(self):
        ident = self._selected_id()
        if ident is None:
            return
        answer = QMessageBox.question(self, "Delete check-in", "Permanently delete this spending check-in?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        with session_scope() as session:
            session.delete(session.get(SpendingEntry, ident))
        self.refresh()
        self.changed.emit()
