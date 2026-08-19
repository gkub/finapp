from __future__ import annotations

from datetime import date
from decimal import Decimal

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from sqlalchemy import select

from finance_tracker.db.database import session_scope
from finance_tracker.db.models import RecurringExpense
from finance_tracker.services.analytics_service import forecast_interval
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
    ("cash", "Operating cash"),
    ("investments", "Investments"),
    ("cards", "Cards owed"),
    ("credit_available", "Credit available"),
    ("debt", "Total debt"),
    ("net_worth", "Net worth"),
)


def _to_date(edit: QDateEdit) -> date:
    value = edit.date()
    return date(value.year(), value.month(), value.day())


def _date_edit(value: date) -> QDateEdit:
    field = QDateEdit(QDate(value.year, value.month, value.day))
    field.setCalendarPopup(True)
    field.setDisplayFormat("yyyy-MM-dd")
    return field


class Outlook(QWidget):
    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Outlook",
            "Scheduled forecasts and temporary what-if choices. Nothing on this page changes saved records.",
        )
        self.tabs = QTabWidget()
        box.addWidget(self.tabs, 1)
        self._build_scenario_tab()
        self._build_forecast_tab()
        self.paused_ids: set[int] = set()
        self._loading = False
        self._changing_dates = False
        self.apply_settings(initial=True)

    def _build_scenario_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        note = QLabel(
            "Compare the current schedule with selected subscriptions paused. From is the start of that day; "
            "As of includes every scheduled item on that date."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
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
        layout.addLayout(controls)
        self.start.dateChanged.connect(self._recompute_scenario)
        self.end.dateChanged.connect(self._recompute_scenario)

        self.summary = QTableWidget(len(_ROWS), 6)
        self.summary.setHorizontalHeaderLabels(["", "From", "As of", "Change", "If paused", "vs keeping"])
        configure_table(self.summary)
        self.summary.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.summary.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.summary.setMinimumHeight(300)
        self.summary.setMaximumHeight(320)
        layout.addWidget(self.summary)

        paused = QLabel("Pause subscriptions for this scenario")
        paused.setObjectName("muted")
        layout.addWidget(paused)
        self.expenses = QTableWidget(0, 5)
        self.expenses.setHorizontalHeaderLabels(["Pause", "Name", "Amount", "Paid from", "Hits in range"])
        configure_table(self.expenses)
        self.expenses.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.expenses.itemChanged.connect(self._pause_changed)
        layout.addWidget(self.expenses, 1)
        self.tabs.addTab(tab, "Scenario")

    def _build_forecast_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)
        note = QLabel(
            "Inspect a future interval from configured income, bills, transfers, card charges, and debt payments."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Quick range"))
        self.forecast_preset = QComboBox()
        for label, days in (("30 days", 30), ("90 days", 90), ("6 months", 183), ("1 year", 365), ("Custom", None)):
            self.forecast_preset.addItem(label, days)
        self.forecast_preset.setCurrentIndex(1)
        controls.addWidget(self.forecast_preset)
        controls.addWidget(QLabel("From"))
        self.forecast_start = _date_edit(date.today())
        self.forecast_start.setMinimumDate(QDate.currentDate())
        controls.addWidget(self.forecast_start)
        controls.addWidget(QLabel("To"))
        self.forecast_end = _date_edit(date.today())
        self.forecast_end.setMinimumDate(QDate.currentDate())
        controls.addWidget(self.forecast_end)
        controls.addStretch()
        layout.addLayout(controls)

        self.forecast_status = QLabel()
        self.forecast_status.setObjectName("muted")
        self.forecast_status.setWordWrap(True)
        layout.addWidget(self.forecast_status)
        self.forecast_table = QTableWidget(0, 4)
        self.forecast_table.setHorizontalHeaderLabels(["Metric", "At interval start", "At interval end", "Interval result"])
        configure_table(self.forecast_table)
        self.forecast_table.setMaximumHeight(190)
        layout.addWidget(self.forecast_table)

        heading = QLabel("<b>Debt reconciliation</b> - opening owed + new charges - payments = closing owed")
        layout.addWidget(heading)
        self.debt_table = QTableWidget(0, 6)
        self.debt_table.setHorizontalHeaderLabels(
            ["Debt", "Owed at start", "Payments", "New charges", "Net reduction", "Owed at end"],
        )
        configure_table(self.debt_table)
        layout.addWidget(self.debt_table, 1)
        self.forecast_preset.currentIndexChanged.connect(self._apply_forecast_preset)
        self.forecast_start.dateChanged.connect(self._forecast_dates_changed)
        self.forecast_end.dateChanged.connect(self._forecast_dates_changed)
        self.tabs.addTab(tab, "Scheduled debt")

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

        self.forecast_start.blockSignals(True)
        self.forecast_end.blockSignals(True)
        self.forecast_start.setMinimumDate(today)
        self.forecast_end.setMinimumDate(self.forecast_start.date())
        if self.forecast_start.date() < today:
            self.forecast_start.setDate(today)
        if initial:
            preset_days = self.forecast_preset.currentData() or days
            self.forecast_end.setDate(today.addDays(int(preset_days)))
        elif self.forecast_end.date() < self.forecast_start.date():
            self.forecast_end.setDate(self.forecast_start.date())
        self.forecast_start.blockSignals(False)
        self.forecast_end.blockSignals(False)

    def refresh(self):
        self._reload_expenses()
        self._recompute_scenario()
        self._recompute_forecast()

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
        self._recompute_scenario()

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
                    pause.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                    pause.setCheckState(Qt.CheckState.Checked if item.id in self.paused_ids else Qt.CheckState.Unchecked)
                    pause.setData(_USER_ID, item.id)
                    self.expenses.setItem(row, 0, pause)
                    name = QTableWidgetItem(item.name)
                    name.setData(_USER_ID, item.id)
                    self.expenses.setItem(row, 1, name)
                    self.expenses.setItem(row, 2, QTableWidgetItem(format_money(item.amount, item.currency)))
                    self.expenses.setItem(
                        row, 3, QTableWidgetItem(payment_method_label(session, item.payment_account_id, item.payment_debt_id)),
                    )
                    self.expenses.setItem(row, 4, QTableWidgetItem("-"))
        finally:
            self._loading = False

    def _recompute_scenario(self):
        start_date, end_date = _to_date(self.start), _to_date(self.end)
        paused = frozenset(self.paused_ids)
        try:
            with session_scope() as session:
                _, _, currency = projection_prefs(session)
                sheet = current_balance_sheet(session, currency)
                horizon_end = max(start_date, end_date)
                baseline_events = generate_events(session, date.today(), horizon_end, currency)
                start_args = (sheet.operating_cash, sheet.credit_cards, sheet.debts, sheet.investments, sheet.net_worth)
                baseline = project(
                    sheet.operating_cash, baseline_events, sheet.credit_cards, sheet.debts,
                    sheet.investments, sheet.credit_limit,
                )
                if paused:
                    paused_events = generate_events(session, date.today(), horizon_end, currency, paused)
                    simulated = project(
                        sheet.operating_cash, paused_events, sheet.credit_cards, sheet.debts,
                        sheet.investments, sheet.credit_limit,
                    )
                else:
                    simulated = baseline
                origin = position_at(start_date, baseline, *start_args, inclusive=False)
                as_of = position_at(end_date, baseline, *start_args, inclusive=True)
                paused_as_of = position_at(end_date, simulated, *start_args, inclusive=True)
                change = PositionDelta.between(origin, as_of)
                versus = PositionDelta.between(as_of, paused_as_of)
                lo, hi = min(start_date, end_date), max(start_date, end_date)
                hits = {}
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
            "cards": (origin.cards, as_of.cards, change.cards, paused_as_of.cards, versus.cards),
            "credit_available": (
                max(sheet.credit_limit - origin.cards, Decimal("0")),
                max(sheet.credit_limit - as_of.cards, Decimal("0")),
                -change.cards,
                max(sheet.credit_limit - paused_as_of.cards, Decimal("0")),
                -versus.cards,
            ),
            "debt": (origin.debt, as_of.debt, change.debt, paused_as_of.debt, versus.debt),
            "net_worth": (origin.net_worth, as_of.net_worth, change.net_worth, paused_as_of.net_worth, versus.net_worth),
        }
        lower_is_better = {"cards", "debt"}
        for row, (key, label) in enumerate(_ROWS):
            start_value, end_value, delta, paused_value, vs_keep = values[key]
            cells = (
                label, format_money(start_value), format_money(end_value), format_signed(delta),
                format_money(paused_value), format_signed(vs_keep),
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
                self.expenses.setItem(row, 4, QTableWidgetItem(str(count) if count else "-"))
            fit_table_columns(self.expenses)
        finally:
            self._loading = False

    def _select_custom(self):
        index = self.forecast_preset.findData(None)
        if index >= 0:
            self.forecast_preset.setCurrentIndex(index)

    def _apply_forecast_preset(self):
        days = self.forecast_preset.currentData()
        if days is None or self._changing_dates:
            return
        self._changing_dates = True
        start = self.forecast_start.date()
        self.forecast_end.setMinimumDate(start)
        self.forecast_end.setDate(start.addDays(int(days)))
        self._changing_dates = False
        self._recompute_forecast()

    def _forecast_dates_changed(self):
        if self._changing_dates:
            return
        self._changing_dates = True
        self.forecast_end.setMinimumDate(self.forecast_start.date())
        if self.forecast_end.date() < self.forecast_start.date():
            self.forecast_end.setDate(self.forecast_start.date())
        self._select_custom()
        self._changing_dates = False
        self._recompute_forecast()

    def _recompute_forecast(self):
        start_date, end_date = _to_date(self.forecast_start), _to_date(self.forecast_end)
        try:
            with session_scope() as session:
                _, _, currency = projection_prefs(session)
                forecast = forecast_interval(session, start_date, end_date, currency)
        except Exception as exc:
            self.forecast_status.setText(f"Scheduled forecast unavailable: {exc}")
            self.forecast_table.setRowCount(0)
            self.debt_table.setRowCount(0)
            return

        self.forecast_table.setRowCount(len(forecast.summary))
        for row, metric in enumerate(forecast.summary):
            if metric.lower_is_better:
                result = (
                    f"{format_money(metric.improvement, currency)} net reduction"
                    if metric.improvement >= 0 else f"{format_money(-metric.improvement, currency)} net increase"
                )
            else:
                result = format_signed(metric.change, currency)
            for col, value in enumerate((
                metric.label, format_money(metric.start_value, currency),
                format_money(metric.end_value, currency), result,
            )):
                item = QTableWidgetItem(value)
                if col == 3 and metric.improvement:
                    item.setForeground(_GOOD if metric.improvement > 0 else _BAD)
                self.forecast_table.setItem(row, col, item)
        fit_table_columns(self.forecast_table)

        self.debt_table.setRowCount(len(forecast.debts))
        for row, debt in enumerate(forecast.debts):
            values = (
                debt.label, format_money(debt.start_balance, currency), format_money(debt.payments, currency),
                format_money(debt.charges, currency), format_signed(debt.net_reduction, currency),
                format_money(debt.end_balance, currency),
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 4 and debt.net_reduction:
                    item.setForeground(_GOOD if debt.net_reduction > 0 else _BAD)
                self.debt_table.setItem(row, col, item)
        fit_table_columns(self.debt_table)
        interval_days = (forecast.end - forecast.start).days + 1
        self.forecast_status.setText(
            f"Scheduled activity from {forecast.start.isoformat()} through {forecast.end.isoformat()} "
            f"({interval_days} inclusive days) in {currency}. Payments stop at zero owed; new card charges are separate."
        )
