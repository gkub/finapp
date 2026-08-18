from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget

from finance_tracker.db.database import session_scope
from finance_tracker.services.analytics_service import progress_metrics
from finance_tracker.ui.domain_pages import configure_table, fit_table_columns, projection_prefs, titled_page
from finance_tracker.utils.money import format_money, format_signed


_GOOD = QColor("#63b58a")
_BAD = QColor("#d86f6f")


class ProgressPage(QWidget):
    def __init__(self):
        super().__init__()
        box = titled_page(
            self,
            "Progress & Pace",
            "Observed pace comes from dated balance snapshots. The forward estimate extends that pace linearly; "
            "it is not a promise or an assumed investment return.",
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Measure the last"))
        self.lookback = QComboBox()
        for label, days in (("30 days", 30), ("90 days", 90), ("6 months", 183), ("1 year", 365)):
            self.lookback.addItem(label, days)
        self.lookback.setCurrentIndex(1)
        controls.addWidget(self.lookback)
        controls.addWidget(QLabel("Project that pace for"))
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
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "Metric", "Observed from", "Through", "Starting value", "Latest observed",
            "Progress", "Pace / month", "At current pace", "Coverage",
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
                metrics = progress_metrics(
                    session, today - timedelta(days=lookback_days), today, months, currency,
                )
        except Exception as exc:
            self.status.setText(f"Progress unavailable: {exc}")
            self.table.setRowCount(0)
            return

        self.table.setHorizontalHeaderItem(7, QTableWidgetItem(f"In {months} months"))
        self.table.setRowCount(len(metrics))
        available = 0
        for row, metric in enumerate(metrics):
            entity_coverage = (
                f"; {metric.covered_entities}/{metric.total_entities} records"
                if metric.total_entities else "; no matching records"
            )
            if metric.available:
                available += 1
                values = (
                    metric.label, metric.observed_start.isoformat(), metric.observed_end.isoformat(),
                    format_money(metric.start_value, currency), format_money(metric.end_value, currency),
                    format_signed(metric.change, currency), format_signed(metric.monthly_pace, currency),
                    format_money(metric.projected_value, currency), f"{metric.observation_count} snapshot dates{entity_coverage}",
                )
            else:
                values = (
                    metric.label, "—", "—", "—", "—", "—", "—", "Not enough history",
                    f"{metric.observation_count} snapshot dates{entity_coverage}",
                )
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if metric.available and col in {5, 6} and metric.change:
                    item.setForeground(_GOOD if metric.change > 0 else _BAD)
                self.table.setItem(row, col, item)
        if available:
            self.status.setText(
                f"Showing {available} measurable areas in {currency}. Update Finances periodically for a steadier pace. "
                "Investment value change currently combines contributions and market movement."
            )
        else:
            self.status.setText(
                "At least two dated snapshots are needed for each metric. Use Update Finances on different dates; "
                "nothing needs to be entered manually on this page."
            )
        fit_table_columns(self.table)
