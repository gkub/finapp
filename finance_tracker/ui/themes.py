from __future__ import annotations

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication


PALETTES = {
    "dark": {
        "background": "#11151c", "surface": "#1a202a", "sidebar": "#171c25",
        "text": "#e8edf5", "muted": "#93a0b3", "border": "#354154",
        "button": "#242c39", "button_hover": "#2d3747", "primary": "#285fc7",
        "primary_text": "#ffffff", "selection": "#263650", "accent": "#78a7ff",
        "alternate": "#1b222d", "header": "#202733",
    },
    "light": {
        "background": "#f5f7fa", "surface": "#ffffff", "sidebar": "#e9eef5",
        "text": "#202733", "muted": "#596474", "border": "#c8d1dd",
        "button": "#e3e9f1", "button_hover": "#d5deea", "primary": "#2f67d8",
        "primary_text": "#ffffff", "selection": "#d9e5fb", "accent": "#2457b8",
        "alternate": "#f1f4f8", "header": "#e4eaf2",
    },
    "pink": {
        "background": "#fff7fb", "surface": "#fffafd", "sidebar": "#f8e8f1",
        "text": "#2f2430", "muted": "#695866", "border": "#d9bdcc",
        "button": "#f1d9e5", "button_hover": "#e8c7d8", "primary": "#9f456f",
        "primary_text": "#ffffff", "selection": "#edd0df", "accent": "#8d365f",
        "alternate": "#fdf0f7", "header": "#f3dce8",
    },
}


def resolved_theme(name: str) -> str:
    if name in {"dark", "light", "pink"}:
        return name
    app = QApplication.instance()
    if app is not None:
        window = app.palette().color(QPalette.ColorRole.Window)
        return "dark" if window.lightness() < 128 else "light"
    return "dark"


def stylesheet(name: str) -> str:
    p = PALETTES[resolved_theme(name)]
    return f"""
QWidget {{ background:{p["background"]}; color:{p["text"]}; font-size:14px; }}
QFrame#sidebar {{ background:{p["sidebar"]}; border-right:1px solid {p["border"]}; }}
QLabel#brand {{ font-size:20px; font-weight:700; padding:8px; }}
QLabel#title {{ font-size:28px; font-weight:700; }}
QLabel#muted {{ color:{p["muted"]}; }}
QPushButton {{ background:{p["button"]}; border:1px solid {p["border"]}; border-radius:7px; padding:8px 14px; }}
QPushButton:hover {{ background:{p["button_hover"]}; }}
QPushButton#primary {{ background:{p["primary"]}; border-color:{p["primary"]}; color:{p["primary_text"]}; font-weight:600; }}
QPushButton#nav {{ text-align:left; border:none; background:transparent; padding:10px 14px; }}
QPushButton#nav:checked {{ background:{p["selection"]}; color:{p["accent"]}; border-left:3px solid {p["primary"]}; }}
QFrame#card {{ background:{p["surface"]}; border:1px solid {p["border"]}; border-radius:10px; }}
QLabel#metric {{ font-size:23px; font-weight:700; }}
QLineEdit,QComboBox,QDoubleSpinBox,QDateEdit {{ background:{p["surface"]}; border:1px solid {p["border"]}; border-radius:6px; padding:7px; }}
QTableWidget {{ background:{p["surface"]}; alternate-background-color:{p["alternate"]}; border:1px solid {p["border"]}; gridline-color:{p["border"]}; }}
QTableWidget::item {{ padding:6px 10px; }}
QTableWidget QDoubleSpinBox {{ padding:2px 10px; min-height:34px; font-size:15px; }}
QHeaderView::section {{ background:{p["header"]}; color:{p["text"]}; border:none; padding:8px 12px; font-weight:600; }}
QToolTip {{ background:{p["surface"]}; color:{p["text"]}; border:1px solid {p["border"]}; }}
"""
