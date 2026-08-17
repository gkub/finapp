from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QWidget,
)
from sqlalchemy import select

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import RecurringExpense
from finance_tracker.services.balance_service import current_balance_sheet
from finance_tracker.services.projection_service import (
    PositionDelta, generate_events, position_at, project,
)
from finance_tracker.ui.domain_pages import (
    configure_table, fit_table_columns, payment_method_label, projection_prefs, titled_page,
)
from finance_tracker.utils.money import format_money, format_signed

_USER_ID = Qt.ItemDataRole.UserRole
_GOOD = QColor("#7dcea0")
_BAD = QColor("#e07a7a")
_ROWS = (
    ("cash", "Cash"),
    ("investments", "Investments"),
    ("material", "Material assets"),
    ("cards", "Cards owed"),
    ("credit_available", "Credit available"),
    ("debt", "Total debt"),
    ("net_worth", "Net worth"),
)


def _to_date(edit: QDateEdit) -> date:
    value = edit.date()
    return date(value.year(), value.month(), value.day())


class Outlook(QWidget):
    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Outlook",
            "From is the start of that day (right now, if today). As of is after every scheduled item on that date. "
            "Investments stay at today's market value. Pausing a subscription here does not change Recurring Expenses.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("From"))
        self.start = QDateEdit(QDate.currentDate())
        self.start.setCalendarPopup(True)
        self.start.setMinimumDate(QDate.currentDate())
        controls.addWidget(self.start)
        controls.addWidget(QLabel("As of"))
        self.end = QDateEdit(QDate.currentDate().addDays(30))
        self.end.setCalendarPopup(True)
        self.end.setMinimumDate(QDate.currentDate())
        controls.addWidget(self.end)
        controls.addStretch()
        box.addLayout(controls)
        self.start.dateChanged.connect(self._recompute)
        self.end.dateChanged.connect(self._recompute)

        self.summary = QTableWidget(len(_ROWS), 6)
        self.summary.setHorizontalHeaderLabels(
            ["", "From", "As of", "Change", "If paused", "vs keeping"],
        )
        configure_table(self.summary)
        self.summary.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.summary.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.summary.setMaximumHeight(270)
        box.addWidget(self.summary)

        paused = QLabel("Pause subscriptions for this view")
        paused.setObjectName("muted")
        box.addWidget(paused)
        self.expenses = QTableWidget(0, 5)
        self.expenses.setHorizontalHeaderLabels(["Pause", "Name", "Amount", "Paid from", "Hits in range"])
        configure_table(self.expenses)
        self.expenses.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.expenses.itemChanged.connect(self._pause_changed)
        box.addWidget(self.expenses, 1)
        self.paused_ids: set[int] = set()
        self._loading = False
        self.apply_settings(initial=True)

    def apply_settings(self, initial=False):
        with session_scope() as session:
            days, _, _ = projection_prefs(session)
        today = QDate.currentDate()
        self.start.blockSignals(True)
        self.end.blockSignals(True)
        self.start.setMinimumDate(today)
        self.end.setMinimumDate(today)
        if self.start.date() < today:
            self.start.setDate(today)
        if initial:
            self.end.setDate(today.addDays(days))
        elif self.end.date() < today:
            self.end.setDate(today)
        self.start.blockSignals(False)
        self.end.blockSignals(False)

    def refresh(self):
        self._reload_expenses()
        self._recompute()

    def _pause_changed(self, item: QTableWidgetItem):
        if self._loading or item.column() != 0:
            return
        ident = item.data(_USER_ID)
        if ident is None:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self.paused_ids.add(ident)
        else:
            self.paused_ids.discard(ident)
        self._recompute()

    def _reload_expenses(self):
        self._loading = True
        try:
            with session_scope() as session:
                items = session.scalars(
                    select(RecurringExpense).where(RecurringExpense.active.is_(True)).order_by(RecurringExpense.name)
                ).all()
                known = {item.id for item in items}
                self.paused_ids &= known
                self.expenses.setRowCount(len(items))
                for row, item in enumerate(items):
                    pause = QTableWidgetItem()
                    pause.setFlags(
                        Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable
                    )
                    pause.setCheckState(
                        Qt.CheckState.Checked if item.id in self.paused_ids else Qt.CheckState.Unchecked
                    )
                    pause.setData(_USER_ID, item.id)
                    self.expenses.setItem(row, 0, pause)
                    name = QTableWidgetItem(item.name)
                    name.setData(_USER_ID, item.id)
                    self.expenses.setItem(row, 1, name)
                    self.expenses.setItem(row, 2, QTableWidgetItem(format_money(item.amount, item.currency)))
                    self.expenses.setItem(
                        row, 3, QTableWidgetItem(payment_method_label(session, item.payment_account_id, item.payment_debt_id)),
                    )
                    self.expenses.setItem(row, 4, QTableWidgetItem("—"))
        finally:
            self._loading = False

    def _recompute(self):
        start_date, end_date = _to_date(self.start), _to_date(self.end)
        paused = frozenset(self.paused_ids)
        try:
            with session_scope() as session:
                _, _, currency = projection_prefs(session)
                sheet = current_balance_sheet(session, currency)
                horizon_end = max(start_date, end_date)
                baseline_events = generate_events(session, date.today(), horizon_end, currency)
                start_args = (
                    sheet.operating_cash, sheet.credit_cards, sheet.debts, sheet.investments, sheet.net_worth,
                )
                baseline = project(
                    sheet.operating_cash, baseline_events, sheet.credit_cards, sheet.debts, sheet.investments, sheet.credit_limit,
                )
                if paused:
                    paused_events = generate_events(session, date.today(), horizon_end, currency, paused)
                    simulated = project(
                        sheet.operating_cash, paused_events, sheet.credit_cards, sheet.debts, sheet.investments, sheet.credit_limit,
                    )
                else:
                    simulated = baseline
                origin = position_at(start_date, baseline, *start_args, inclusive=False)
                as_of = position_at(end_date, baseline, *start_args, inclusive=True)
                paused_as_of = position_at(end_date, simulated, *start_args, inclusive=True)
                change = PositionDelta.between(origin, as_of)
                versus = PositionDelta.between(as_of, paused_as_of)
                material = sheet.material_assets
                lo, hi = min(start_date, end_date), max(start_date, end_date)
                hits: dict[int, int] = {}
                for event in baseline_events:
                    if event.event_type in {"expense", "card_charge"} and lo <= event.date <= hi:
                        hits[event.source_record_id] = hits.get(event.source_record_id, 0) + 1
        except Exception as exc:
            self.summary.setToolTip(str(exc))
            return
        self.summary.setToolTip("")
        values = {
            "cash": (origin.cash, as_of.cash, change.cash, paused_as_of.cash, versus.cash),
            "investments": (origin.investments, as_of.investments, change.investments, paused_as_of.investments, versus.investments),
            "material": (material, material, Decimal("0"), material, Decimal("0")),
            "cards": (origin.cards, as_of.cards, change.cards, paused_as_of.cards, versus.cards),
            "credit_available": (
                max(sheet.credit_limit - origin.cards, Decimal("0")),
                max(sheet.credit_limit - as_of.cards, Decimal("0")),
                -(change.cards),
                max(sheet.credit_limit - paused_as_of.cards, Decimal("0")),
                -(versus.cards),
            ),
            "debt": (origin.debt, as_of.debt, change.debt, paused_as_of.debt, versus.debt),
            "net_worth": (origin.net_worth, as_of.net_worth, change.net_worth, paused_as_of.net_worth, versus.net_worth),
        }
        lower_is_better = {"cards", "debt"}
        for row, (key, label) in enumerate(_ROWS):
            start_value, end_value, delta, paused_value, vs_keep = values[key]
            cells = (
                label,
                format_money(start_value),
                format_money(end_value),
                format_signed(delta),
                format_money(paused_value),
                format_signed(vs_keep),
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col in {3, 5}:
                    amount = delta if col == 3 else vs_keep
                    better = amount < 0 if key in lower_is_better else amount > 0
                    if amount != 0:
                        item.setForeground(_GOOD if better else _BAD)
                self.summary.setItem(row, col, item)
        fit_table_columns(self.summary)
        self._loading = True
        try:
            for row in range(self.expenses.rowCount()):
                ident = self.expenses.item(row, 0).data(_USER_ID)
                count = hits.get(ident, 0)
                self.expenses.setItem(row, 4, QTableWidgetItem(str(count) if count else "—"))
            fit_table_columns(self.expenses)
        finally:
            self._loading = False
