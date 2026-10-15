"""Uygulama teması: marka renkleri, logo ve stil sayfası."""
from __future__ import annotations

import os

from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

BRAND_NAME = "Suspend Global"
DESIGNER = "furkan özgül"

NAVY = "#17202a"
NAVY_2 = "#24313f"
BLUE = "#1fa7e3"
BLUE_DARK = "#1786bf"
BG = "#f4f7fa"
BORDER = "#cfd8e1"
TEXT = "#17202a"
MUTED = "#5b6875"


def asset_path(name: str) -> str:
    # PyInstaller onefile'da da modülün yanındaki assets klasörü kullanılır (--add-data ile)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)


def app_icon() -> QIcon:
    return QIcon(asset_path("app.ico"))


STYLESHEET = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ font-family: "Segoe UI"; font-size: 10pt; color: {TEXT}; }}

#Header {{ background: {NAVY}; }}
#HeaderTitle {{ color: white; font-size: 15pt; font-weight: 600; }}
#HeaderSub {{ color: #7fd0f5; font-size: 9pt; letter-spacing: 2px; }}
/* Satisfy programla birlikte gelir (assets/fonts); yüklenemezse Windows'un el yazısı fontu */
#HeaderCredit {{
    color: #e8c77a; font-family: "Satisfy", "Segoe Script";
    font-size: 12pt;
}}

QMenuBar {{ background: {NAVY}; color: white; }}
QMenuBar::item {{ padding: 4px 10px; background: transparent; color: white; }}
QMenuBar::item:selected {{ background: {NAVY_2}; }}
QMenu {{ background: white; border: 1px solid {BORDER}; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: #e3f3fc; color: {TEXT}; }}

QStatusBar {{ background: {NAVY}; color: #cfd8e1; }}
QStatusBar QLabel {{ color: #cfd8e1; }}

QGroupBox {{
    background: white; border: 1px solid {BORDER}; border-radius: 8px;
    margin-top: 14px; padding: 12px 8px 8px 8px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {NAVY}; }}

QPushButton {{
    background: white; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 12px; color: {TEXT};
}}
QPushButton:hover {{ border-color: {BLUE}; background: #eef8fd; }}
QPushButton:pressed {{ background: #dbeffa; }}
QPushButton:disabled {{ color: #9aa6b2; background: #f1f4f7; border-color: #e1e6eb; }}
QPushButton[primary="true"] {{
    background: {BLUE}; color: white; border: 1px solid {BLUE_DARK}; font-weight: 600;
}}
QPushButton[primary="true"]:hover {{ background: {BLUE_DARK}; }}
QPushButton[primary="true"]:disabled {{ background: #a9d9ef; border-color: #a9d9ef; color: white; }}

QLineEdit, QComboBox, QDateTimeEdit, QPlainTextEdit, QListWidget {{
    background: white; border: 1px solid {BORDER}; border-radius: 5px; padding: 4px 6px;
    selection-background-color: {BLUE}; selection-color: white;
}}
QLineEdit:focus, QComboBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus, QListWidget:focus {{
    border-color: {BLUE};
}}

QTableWidget {{
    background: white; border: 1px solid {BORDER}; border-radius: 5px;
    gridline-color: #e6ebf0; alternate-background-color: #f7f9fb;
    selection-background-color: #cdeaf9; selection-color: {TEXT};
}}
QHeaderView::section {{
    background: #eef2f6; border: none; border-bottom: 1px solid {BORDER};
    border-right: 1px solid #e1e6eb; padding: 6px; font-weight: 600; color: {NAVY};
}}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent; padding: 8px 18px; border: none;
    border-bottom: 3px solid transparent; color: {MUTED}; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {NAVY}; border-bottom-color: {BLUE}; }}
#MainTabs > QTabBar::tab {{ font-size: 11pt; padding: 10px 22px; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border: 1px solid #8a9aab; border-radius: 4px; background: white;
}}
QCheckBox::indicator:hover {{ border-color: {BLUE}; }}
QCheckBox::indicator:checked {{ background: {BLUE}; border-color: {BLUE_DARK}; image: url(%CHECK%); }}
QCheckBox::indicator:disabled {{ background: #eef2f6; border-color: #d5dde5; }}

QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: transparent; }}
QToolTip {{ background: {NAVY}; color: white; border: none; padding: 4px; }}
"""


def apply_theme(app: QApplication) -> None:
    # Fusion + açık palet: işletim sistemi koyu temada olsa da tasarım tutarlı kalır
    if "fusion" in [s.lower() for s in QStyleFactory.keys()]:
        app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor("white"))
    pal.setColor(QPalette.AlternateBase, QColor("#f7f9fb"))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor("white"))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(BLUE))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor(NAVY))
    pal.setColor(QPalette.ToolTipText, QColor("white"))
    pal.setColor(QPalette.PlaceholderText, QColor("#8a96a3"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#9aa6b2"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#9aa6b2"))
    app.setPalette(pal)
    QFontDatabase.addApplicationFont(asset_path(os.path.join("fonts", "Satisfy-Regular.ttf")))
    app.setStyleSheet(STYLESHEET.replace("%CHECK%", asset_path("check.png").replace("\\", "/")))
    app.setWindowIcon(app_icon())
