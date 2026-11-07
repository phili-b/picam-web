'''
© 2025, Philippe Baetens
'''

# Dark look with a green accent, shared with the web UI:
# charcoal ground, green #9ACD56 accent, grey #91969D.
# artwork/icon.png is the app icon; a logo in artwork/logo.png is shown in the status bar if present.

from abc import ABC
from PyQt5.QtGui import QColor, QPalette, QPixmap
from PyQt5.QtWidgets import QLabel, QStatusBar, QWidget
import os

APP_NAME = "Picam-web"
APP_SUBTITLE = "for Raspberry Pi"
ARTWORK_DIR = os.path.join(os.path.dirname(__file__), "artwork")

GREEN = "#9ACD56"
GREY = "#91969D"
SURFACE = "#353835"
BASE = "#2B2E2B"
BUTTON = "#414441"
TEXT = "#DCDEDA"


class Style(ABC):

    COLOR_ACCENT = QColor(GREEN)
    COLOR_GREY = QColor(GREY)

    # Qt's platform independent desktop style "Fusion"
    STYLE_NAME = "Fusion"

    # Font: Lexend (SIL Open Font License, ttf embedded since not installed by default)
    FONT_NAME = "Lexend Light"
    FONT_FAMILY = "Lexend"
    FONT_STYLE = "Light"
    FONT_FILE = "/fonts/Lexend/Lexend-Light.ttf"
    FONT_SIZE = 12

    ICON_FILE = os.path.join(ARTWORK_DIR, "icon.png")
    LOGO_FILE = os.path.join(ARTWORK_DIR, "logo.png")

    default_palette = QPalette()
    for role, colour in (
        (QPalette.Window, (53, 56, 53)),
        (QPalette.WindowText, (220, 222, 218)),
        (QPalette.Base, (43, 46, 43)),
        (QPalette.AlternateBase, (58, 61, 58)),
        (QPalette.ToolTipBase, (53, 56, 53)),
        (QPalette.ToolTipText, (220, 222, 218)),
        (QPalette.Text, (220, 222, 218)),
        (QPalette.BrightText, (255, 80, 80)),
        (QPalette.Button, (65, 68, 65)),
        (QPalette.ButtonText, (220, 222, 218)),
        (QPalette.Highlight, (154, 205, 86)),
        (QPalette.HighlightedText, (20, 22, 20)),
        (QPalette.Link, (154, 205, 86)),
        (QPalette.LinkVisited, (120, 160, 60)),
    ):
        default_palette.setColor(role, QColor(*colour))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        default_palette.setColor(QPalette.Disabled, role, QColor(118, 122, 118))
    default_palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(70, 90, 40))

    STYLESHEET = f"""
        QToolTip {{ background-color: {SURFACE}; color: {TEXT}; border: 1px solid {GREY}; padding: 4px; }}
        QTabBar::tab:selected {{ color: {GREEN}; }}
        QTabWidget::pane {{ border: 1px solid {BUTTON}; }}
        QPushButton:hover {{ border: 1px solid {GREEN}; }}
        QGroupBox {{ border: 1px solid {BUTTON}; margin-top: 1.2em; padding-top: 4px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 8px; color: {GREY}; }}
        QSlider::handle:horizontal {{ background: {GREEN}; border-radius: 3px; width: 10px; margin: -4px 0; }}
        QStatusBar {{ border-top: 1px solid {GREEN}; }}
    """

    @staticmethod
    def create_status_bar(version):
        status_bar = QStatusBar()
        name = QLabel(f"{APP_NAME} <span style='color:{GREY}'>{APP_SUBTITLE} · v{version}</span>")
        status_bar.addPermanentWidget(name)
        spacer = QWidget()
        spacer.setFixedWidth(12)
        status_bar.addPermanentWidget(spacer)
        if os.path.isfile(Style.LOGO_FILE):
            logo = QLabel()
            logo.setPixmap(QPixmap(Style.LOGO_FILE))
            status_bar.addPermanentWidget(logo)
        status_bar.setSizeGripEnabled(False)
        return status_bar
