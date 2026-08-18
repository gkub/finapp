from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget,
)

from finance_tracker.db.database import session_scope
from finance_tracker.services.analytics_service import forecast_interval, historical_metrics
from finance_tracker.ui.domain_pages import configure_table, fit_table_columns, projection_prefs, titled_page
from finance_tracker.utils.money import format_money, format_signed

_GOOD = QColor("#63b58a")
_BAD = QColor("#d86f6f")


def _date_edit(value: date) -> QDateEdit:
    field = QDateEdit(QDate(value.year, value.month, value.day))
    field.setCalendarPopup(True)
    field.setDisplayFormat("yyyy-MM-dd")
    return field


def _python_date(field: QDateEdit) -> date:
    value = field.date()
    return date(value.year(), value.month(), value.day())


def _money(value, currency):
    return format_money(value, currency) if value is not None else "—"


class ProgressPage(QWidget):
    def __init__(self):
        super().__init__()
        today = date.today()
        self._changing_dates = False
        box = titled_page(
            self, "Progress",
            "Actual history compares recorded balance snapshots. Scheduled interval forecasts configured future "
            "income, bills, transfers, card charges, and debt payments. They are deliberately kept separate.",
        )

        history_heading = QLabel("<b>Actual history</b> — what changed between recorded balances")
        box.addWidget(history_heading)
        history_controls = QHBoxLayout()
        history_controls.addWidget(QLabel("Window"))
        self.history_preset = QComboBox()
        for label, days in (("30 days", 30), ("90 days", 90), ("6 months", 183), ("1 year", 365), ("Custom", None)):
            self.history_preset.addItem(label, days)
        self.history_preset.setCurrentIndex(1)
        history_controls.addWidget(self.history_preset)
        history_controls.addWidget(QLabel("From"))
        self.history_start = _date_edit(today - timedelta(days=90))
        self.history_start.setMaximumDate(QDate.currentDate())
        history_controls.addWidget(self.history_start)
        history_controls.addWidget(QLabel("To"))
        self.history_end = _date_edit(today)
        self.history_end.setMaximumDate(QDate.currentDate())
        self.history_end.setMinimumDate(self.history_start.date())
        self.history_start.setMaximumDate(self.history_end.date())
        history_controls.addWidget(self.history_end)
        history_controls.addStretch()
        box.addLayout(history_controls)

        self.history_status = QLabel()
        self.history_status.setObjectName("muted")
        self.history_status.setWordWrap(True)
        box.addWidget(self.history_status)
        self.history_table = QTableWidget(0, 10)
        self.history_table.setHorizontalHeaderLabels([
            "Type", "Metric", "Observed from", "Through", "Starting balance", "Latest balance",
            "Balance change", "Improvement", "Pace / month", "Coverage & quality",
        ])
        configure_table(self.history_table)
        self.history_table.setMinimumHeight(210)
        box.addWidget(self.history_table, 1)

        forecast_heading = QLabel("<b>Scheduled interval</b> — what configured plans say will happen")
        box.addWidget(forecast_heading)
        forecast_controls = QHBoxLayout()
        forecast_controls.addWidget(QLabel("Quick range"))
        self.forecast_preset = QComboBox()
        for label, days in (("30 days", 30), ("90 days", 90), ("6 months", 183), ("1 year", 365), ("Custom", None)):
            self.forecast_preset.addItem(label, days)
        self.forecast_preset.setCurrentIndex(1)
        forecast_controls.addWidget(self.forecast_preset)
        forecast_controls.addWidget(QLabel("From"))
        self.forecast_start = _date_edit(today)
        self.forecast_start.setMinimumDate(QDate.currentDate())
        forecast_controls.addWidget(self.forecast_start)
        forecast_controls.addWidget(QLabel("To"))
        self.forecast_end = _date_edit(today + timedelta(days=90))
        self.forecast_end.setMinimumDate(QDate.currentDate())
        forecast_controls.addWidget(self.forecast_end)
        forecast_controls.addStretch()
        box.addLayout(forecast_controls)

        self.forecast_status = QLabel()
        self.forecast_status.setObjectName("muted")
        self.forecast_status.setWordWrap(True)
        box.addWidget(self.forecast_status)
        self.forecast_table = QTableWidget(0, 4)
        self.forecast_table.setHorizontalHeaderLabels(["Metric", "At interval start", "At interval end", "Interval result"])
        configure_table(self.forecast_table)
        self.forecast_table.setMinimumHeight(150)
        box.addWidget(self.forecast_table)

        debt_heading = QLabel("<b>Debt detail</b> — payments and new charges reconcile opening to closing debt")
        box.addWidget(debt_heading)
        self.debt_table = QTableWidget(0, 6)
        self.debt_table.setHorizontalHeaderLabels([
            "Debt", "Owed at start", "Payments", "New charges", "Net reduction", "Owed at end",
        ])
        configure_table(self.debt_table)
        self.debt_table.setMinimumHeight(170)
        box.addWidget(self.debt_table, 1)

        self.history_preset.currentIndexChanged.connect(self._apply_history_preset)
        self.history_start.dateChanged.connect(self._history_dates_changed)
        self.history_end.dateChanged.connect(self._history_dates_changed)
        self.forecast_preset.currentIndexChanged.connect(self._apply_forecast_preset)
        self.forecast_start.dateChanged.connect(self._forecast_dates_changed)
        self.forecast_end.dateChanged.connect(self._forecast_dates_changed)

    def _select_custom(self, combo):
        index = combo.findData(None)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _apply_history_preset(self):
        days = self.history_preset.currentData()
        if days is None or self._changing_dates:
            return
        self._changing_dates = True
        end = _python_date(self.history_end)
        self.history_start.setDate(QDate(end.year, end.month, end.day).addDays(-int(days)))
        self._changing_dates = False
        self.refresh()

    def _history_dates_changed(self):
        if self._changing_dates:
            return
        self._changing_dates = True
        self.history_start.setMaximumDate(self.history_end.date())
        self.history_end.setMinimumDate(self.history_start.date())
        self._select_custom(self.history_preset)
        self._changing_dates = False
        self.refresh()

    def _apply_forecast_preset(self):
        days = self.forecast_preset.currentData()
        if days is None or self._changing_dates:
            return
        self._changing_dates = True
        start = self.forecast_start.date()
        self.forecast_end.setMinimumDate(start)
        self.forecast_end.setDate(start.addDays(int(days)))
        self._changing_dates = False
        self.refresh()

    def _forecast_dates_changed(self):
        if self._changing_dates:
            return
        self._changing_dates = True
        self.forecast_end.setMinimumDate(self.forecast_start.date())
        if self.forecast_end.date() < self.forecast_start.date():
            self.forecast_end.setDate(self.forecast_start.date())
        self._select_custom(self.forecast_preset)
        self._changing_dates = False
        self.refresh()

    def refresh(self):
        history_start, history_end = _python_date(self.history_start), _python_date(self.history_end)
        forecast_start, forecast_end = _python_date(self.forecast_start), _python_date(self.forecast_end)
        try:
            with session_scope() as session:
                _days, _reserve, currency = projection_prefs(session)
                history = historical_metrics(session, history_start, history_end, currency)
                forecast = forecast_interval(session, forecast_start, forecast_end, currency)
        except Exception as exc:
            message = f"Progress unavailable: {exc}"
            self.history_status.setText(message)
            self.forecast_status.setText(message)
            self.history_table.setRowCount(0)
            self.forecast_table.setRowCount(0)
            self.debt_table.setRowCount(0)
            return
        self._render_history(history, currency)
        self._render_forecast(forecast, currency)

    def _render_history(self, metrics, currency):
        self.history_table.setRowCount(len(metrics))
        comparable = 0
        paced = 0
        for row, metric in enumerate(metrics):
            if metric.balance_change is not None:
                comparable += 1
            if metric.monthly_pace is not None:
                paced += 1
            dates = f"{metric.observation_count} snapshot date" + ("s" if metric.observation_count != 1 else "")
            values = (
                metric.kind,
                metric.label,
                metric.observed_start.isoformat() if metric.observed_start else "—",
                metric.observed_end.isoformat() if metric.observed_end else "—",
                _money(metric.start_value, currency),
                _money(metric.end_value, currency),
                format_signed(metric.balance_change, currency) if metric.balance_change is not None else "—",
                format_signed(metric.improvement, currency) if metric.improvement is not None else "—",
                format_signed(metric.monthly_pace, currency) if metric.monthly_pace is not None else "—",
                f"{dates}; {metric.coverage}; {metric.quality}",
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in {7, 8} and metric.improvement:
                    item.setForeground(_GOOD if metric.improvement > 0 else _BAD)
                self.history_table.setItem(row, col, item)
        self.history_status.setText(
            f"{comparable} historical comparison(s) in {currency}; {paced} have enough history for a monthly pace. "
            "Totals are withheld when any included account is missing history. Debt improvement is net reduction "
            "in amount owed, not gross payments. Investment changes include both "
            "contributions and market movement."
        )
        fit_table_columns(self.history_table)

    def _render_forecast(self, forecast, currency):
        self.forecast_table.setRowCount(len(forecast.summary))
        for row, metric in enumerate(forecast.summary):
            if metric.lower_is_better:
                result = (f"{format_money(metric.improvement, currency)} net reduction" if metric.improvement >= 0
                          else f"{format_money(-metric.improvement, currency)} net increase")
            else:
                result = format_signed(metric.change, currency)
            values = (metric.label, format_money(metric.start_value, currency),
                      format_money(metric.end_value, currency), result)
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 3 and metric.improvement:
                    item.setForeground(_GOOD if metric.improvement > 0 else _BAD)
                self.forecast_table.setItem(row, col, item)
        fit_table_columns(self.forecast_table)

        self.debt_table.setRowCount(len(forecast.debts))
        for row, debt in enumerate(forecast.debts):
            values = (debt.label, format_money(debt.start_balance, currency), format_money(debt.payments, currency),
                      format_money(debt.charges, currency), format_signed(debt.net_reduction, currency),
                      format_money(debt.end_balance, currency))
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 4 and debt.net_reduction:
                    item.setForeground(_GOOD if debt.net_reduction > 0 else _BAD)
                self.debt_table.setItem(row, col, item)
        fit_table_columns(self.debt_table)
        interval_days = (forecast.end - forecast.start).days + 1
        self.forecast_status.setText(
            f"Scheduled activity from {forecast.start.isoformat()} through {forecast.end.isoformat()} "
            f"({interval_days} inclusive days) in {currency}. Payments are capped at the remaining amount owed; "
            "new card spending is shown separately."
        )
