from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget,
)

from finance_tracker.db.database import session_scope
from finance_tracker.services.analytics_service import historical_metrics
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
    return format_money(value, currency) if value is not None else "-"


class TrendsPage(QWidget):
    def __init__(self):
        super().__init__()
        today = date.today()
        self._changing_dates = False
        box = titled_page(
            self, "History & Trends",
            "Only recorded balance snapshots appear here. Scheduled forecasts and what-if choices live in Outlook.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Window"))
        self.history_preset = QComboBox()
        for label, days in (("30 days", 30), ("90 days", 90), ("6 months", 183), ("1 year", 365), ("Custom", None)):
            self.history_preset.addItem(label, days)
        self.history_preset.setCurrentIndex(1)
        controls.addWidget(self.history_preset)
        controls.addWidget(QLabel("From"))
        self.history_start = _date_edit(today - timedelta(days=90))
        self.history_start.setMaximumDate(QDate.currentDate())
        controls.addWidget(self.history_start)
        controls.addWidget(QLabel("To"))
        self.history_end = _date_edit(today)
        self.history_end.setMaximumDate(QDate.currentDate())
        self.history_end.setMinimumDate(self.history_start.date())
        self.history_start.setMaximumDate(self.history_end.date())
        controls.addWidget(self.history_end)
        controls.addStretch()
        box.addLayout(controls)

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
        box.addWidget(self.history_table, 1)

        guidance = QLabel(
            "Balance change is literal. Improvement reverses the sign for debt so a reduction reads positively. "
            "Investment changes still combine contributions and market movement."
        )
        guidance.setObjectName("muted")
        guidance.setWordWrap(True)
        box.addWidget(guidance)

        self.history_preset.currentIndexChanged.connect(self._apply_history_preset)
        self.history_start.dateChanged.connect(self._history_dates_changed)
        self.history_end.dateChanged.connect(self._history_dates_changed)

    def _select_custom(self):
        index = self.history_preset.findData(None)
        if index >= 0:
            self.history_preset.setCurrentIndex(index)

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
        self._select_custom()
        self._changing_dates = False
        self.refresh()

    def refresh(self):
        history_start, history_end = _python_date(self.history_start), _python_date(self.history_end)
        try:
            with session_scope() as session:
                _days, _reserve, currency = projection_prefs(session)
                history = historical_metrics(session, history_start, history_end, currency)
        except Exception as exc:
            self.history_status.setText(f"History unavailable: {exc}")
            self.history_table.setRowCount(0)
            return
        self._render_history(history, currency)

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
                metric.observed_start.isoformat() if metric.observed_start else "-",
                metric.observed_end.isoformat() if metric.observed_end else "-",
                _money(metric.start_value, currency),
                _money(metric.end_value, currency),
                format_signed(metric.balance_change, currency) if metric.balance_change is not None else "-",
                format_signed(metric.improvement, currency) if metric.improvement is not None else "-",
                format_signed(metric.monthly_pace, currency) if metric.monthly_pace is not None else "-",
                f"{dates}; {metric.coverage}; {metric.quality}",
            )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in {7, 8} and metric.improvement:
                    item.setForeground(_GOOD if metric.improvement > 0 else _BAD)
                self.history_table.setItem(row, col, item)
        self.history_status.setText(
            f"{comparable} historical comparison(s) in {currency}; {paced} have enough history for a monthly pace. "
            "Totals are withheld when any included account is missing history."
        )
        fit_table_columns(self.history_table)


ProgressPage = TrendsPage
