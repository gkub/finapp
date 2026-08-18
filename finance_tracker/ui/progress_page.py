from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget

from finance_tracker.db.database import session_scope
from finance_tracker.services.analytics_service import MIN_PACE_DAYS, progress_metrics, scheduled_metrics
from finance_tracker.ui.domain_pages import configure_table, fit_table_columns, projection_prefs, titled_page
from finance_tracker.utils.money import format_money, format_signed

_GOOD = QColor("#63b58a")
_BAD = QColor("#d86f6f")


class ProgressPage(QWidget):
    def __init__(self):
        super().__init__()
        box = titled_page(
            self, "Progress & Pace",
            "Historical pace needs at least 28 days of snapshots. Scheduled forecast uses configured income, "
            "bills, deposits, and debt payments instead of extrapolating a short-term balance swing.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Measure the last"))
        self.lookback = QComboBox()
        for label, days in (("30 days", 30), ("90 days", 90), ("6 months", 183), ("1 year", 365)):
            self.lookback.addItem(label, days)
        self.lookback.setCurrentIndex(1)
        controls.addWidget(self.lookback)
        controls.addWidget(QLabel("Forecast schedules for"))
        self.horizon = QComboBox()
        for label, months in (("3 months", 3), ("6 months", 6), ("1 year", 12), ("2 years", 24)):
            self.horizon.addItem(label, months)
        self.horizon.setCurrentIndex(1)
        controls.addWidget(self.horizon)
        controls.addStretch()
        box.addLayout(controls)
        self.lookback.currentIndexChanged.connect(self.refresh)
        self.horizon.currentIndexChanged.connect(self.refresh)

        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels([
            "Metric", "Observed from", "Through", "Starting value", "Latest observed",
            "Progress", "Pace / month", "At observed pace", "Scheduled forecast", "Coverage",
        ])
        configure_table(self.table)
        box.addWidget(self.table, 1)

    def refresh(self):
        today = date.today()
        lookback_days = int(self.lookback.currentData())
        months = int(self.horizon.currentData())
        try:
            with session_scope() as session:
                _days, _reserve, currency = projection_prefs(session)
                metrics = progress_metrics(session, today - timedelta(days=lookback_days), today, months, currency)
                scheduled = scheduled_metrics(session, today, months, currency)
        except Exception as exc:
            self.status.setText(f"Progress unavailable: {exc}")
            self.table.setRowCount(0)
            return

        self.table.setHorizontalHeaderItem(7, QTableWidgetItem(f"Pace in {months} mo"))
        self.table.setHorizontalHeaderItem(8, QTableWidgetItem(f"Scheduled in {months} mo"))
        self.table.setRowCount(len(metrics))
        available = 0
        for row, metric in enumerate(metrics):
            forecast = scheduled[metric.key]
            scheduled_text = (
                format_money(forecast.future_value, currency)
                if forecast.future_value is not None else "Not tracked by account yet"
            )
            entity_coverage = (
                f"; {metric.covered_entities}/{metric.total_entities} records"
                if metric.total_entities else "; no matching records"
            )
            observed_from = metric.observed_start.isoformat() if metric.observed_start else "—"
            observed_through = metric.observed_end.isoformat() if metric.observed_end else "—"
            start_value = format_money(metric.start_value, currency) if metric.start_value is not None else "—"
            end_value = format_money(metric.end_value, currency) if metric.end_value is not None else "—"
            if metric.available:
                available += 1
                values = (
                    metric.label, observed_from, observed_through, start_value, end_value,
                    format_signed(metric.change, currency), format_signed(metric.monthly_pace, currency),
                    format_money(metric.projected_value, currency), scheduled_text,
                    f"{metric.observation_count} snapshot dates{entity_coverage}",
                )
            else:
                values = (
                    metric.label, observed_from, observed_through, start_value, end_value,
                    "—", "Need 28+ days", "Need 28+ days", scheduled_text,
                    f"{metric.observation_count} snapshot dates{entity_coverage}",
                )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if metric.available and col in {5, 6} and metric.change:
                    item.setForeground(_GOOD if metric.change > 0 else _BAD)
                self.table.setItem(row, col, item)
        if available:
            self.status.setText(
                f"Showing {available} historical trends in {currency}. Scheduled forecasts are calculated separately. "
                "Investment history currently combines contributions and market movement."
            )
        else:
            self.status.setText(
                f"Historical pace needs at least {MIN_PACE_DAYS} days between observations. Scheduled forecasts are "
                "still calculated from configured future events; nothing is annualized from the one-day change."
            )
        fit_table_columns(self.table)
