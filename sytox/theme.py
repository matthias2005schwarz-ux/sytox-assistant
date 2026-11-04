"""SYTOX 0.3.2 desktop visual system.

A native Qt stylesheet, not a web view. Accent colors deliberately stay in a
red/black spectrum; green/yellow are reserved for genuine readiness states.
"""
from __future__ import annotations

BACKGROUND = '#09090C'
PANEL = '#111115'
SURFACE = '#19171D'
ACCENT = '#D83B46'
ACCENT_HOVER = '#F34E59'
TEXT = '#F5F1F2'
MUTED = '#A59BA1'
EDGE = '#2B252A'

STYLE = f"""
QWidget {{
    background-color: {BACKGROUND}; color: {TEXT};
    font-family: 'Segoe UI'; font-size: 13px;
    selection-background-color: #8D2632;
    selection-color: #FFFFFF;
}}
QMainWindow {{ background: {BACKGROUND}; }}
QLabel {{ background: transparent; border: none; }}
QWidget#messageRow {{ background: transparent; }}
QWidget#chatCenter {{ background: {BACKGROUND}; }}
QToolTip {{ background: #242025; border: 1px solid #554047;
    color: #FFFFFF; padding: 7px 10px; border-radius: 6px; }}
QFrame#sidebar {{ background-color: #101013; border-right: 1px solid {EDGE}; }}
QFrame#right {{ background-color: #101013; border-left: 1px solid {EDGE}; }}
QFrame#topbar {{ background-color: #111014; border-bottom: 1px solid {EDGE}; }}
QFrame#composePanel {{ background-color: #0D0C0F; border-top: 1px solid #242024; }}
QFrame#inputCard {{ background-color: #1A171B;
    border: 1px solid #453039; border-radius: 17px; }}
QFrame#utilityCard {{ background-color: #19171B;
    border: 1px solid #31282D; border-radius: 15px; }}
QFrame#hero {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #291318, stop:0.45 #191318, stop:1 #121115);
    border: 1px solid #58303A; border-radius: 22px;
}}
QLabel#brandName {{ color: #FFFFFF; font-size: 24px; font-weight: 900; }}
QLabel#brandSubtitle {{ color: #A79CA2; font-size: 10px; font-weight: 650; }}
QLabel#sectionTitle {{ color: #E7DBDE; font-size: 10px; font-weight: 800; }}
QLabel#panelDescription {{ color: #A89CA0; font-size: 12px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#heroEyebrow {{ color: #F39299; font-size: 11px; font-weight: 800; }}
QLabel#heroTitle {{ color: #FFFFFF; font-size: 27px; font-weight: 850; }}
QLabel#heroCopy {{ color: #C8B9BF; font-size: 13px; }}
QLabel#chatTitle {{ color: #F8F3F4; font-size: 18px; font-weight: 760; }}
QLabel#version {{ color: #746C72; font-size: 10px; }}
QLabel#statusChip {{ color: #DCC8CE; background: #282025;
    border: 1px solid #47353B; border-radius: 11px;
    padding: 5px 11px; font-size: 11px; font-weight: 700; }}
QPushButton {{ background: #252126; border: 1px solid #3B3036;
    border-radius: 10px; padding: 10px 13px; min-height: 17px;
    color: #EEE8EA; font-weight: 650; }}
QPushButton:hover {{ background: #33282E; border-color: #7C4650; }}
QPushButton:pressed {{ background: #22191E; border-color: #A73C4A; }}
QPushButton:disabled {{ color: #716A70; background: #1A171B; border-color: #2A2529; }}
QPushButton#primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #AD2634, stop:1 #D63C46);
    border: 1px solid #E0525A; color: #FFFFFF; font-weight: 800;
}}
QPushButton#primary:hover {{ background: #E4414D; border-color: #FF7A81; }}
QPushButton#primary:pressed {{ background: #9E2431; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent;
    color: #ADA4A9; text-align: left; }}
QPushButton#ghost:hover {{ background: #211A1E;
    border-color: #453039; color: #FFF4F5; }}
QPushButton#subtle {{ background: #241B20; border-color: #402C34;
    color: #EEDDE0; }}
QPushButton#subtle:hover {{ background: #372128; border-color: #8A3945; }}
QPushButton#suggestion {{ background: #23191F; border: 1px solid #57303A;
    color: #EBD5D9; border-radius: 12px; text-align: left; padding: 10px 14px; }}
QPushButton#suggestion:hover {{ background: #3A1D26; border-color: #C14A56; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background: #211D22; border: 1px solid #3B3239;
    border-radius: 10px; padding: 9px 11px; color: #F4F0F1;
    selection-background-color: #8D2632;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
    border-color: #AF4350;
}}
QTextEdit#chatInput {{ background: transparent; border: none;
    color: #F7F3F4; padding: 8px; font-size: 14px; }}
QTextEdit#chatInput:focus {{ border: none; }}
QPlainTextEdit#activityLog {{ background: #131115; border: 1px solid #31252B;
    font-family: 'Consolas'; font-size: 11px; color: #AEA3A8; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: #211B20; border: 1px solid #493038;
    color: #F5EDF0; selection-background-color: #592732; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ color: #B8ADB1; border: 1px solid transparent;
    border-radius: 10px; padding: 11px 12px; margin: 2px 4px; }}
QListWidget::item:selected {{ color: #FFFFFF; background: #3B1B24;
    border: 1px solid #793543; }}
QListWidget::item:hover:!selected {{ color: #F3E7EA; background: #211B1F; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: #100F12; width: 9px; border: none; }}
QScrollBar::handle:vertical {{ background: #47343D; border-radius: 4px;
    min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #71404B; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QSplitter::handle {{ background: #2B2026; }}
QFrame#bubbleUser {{ background: #351B23; border: 1px solid #7B3644;
    border-radius: 17px; }}
QFrame#bubbleAssistant {{ background: #19171C; border: 1px solid #352C32;
    border-radius: 17px; }}
QLabel#bubbleHeadingUser {{ background: transparent; border: none;
    color: #FFABB4; font-size: 11px; font-weight: 800; }}
QLabel#bubbleHeadingAssistant {{ background: transparent; border: none;
    color: #F2808B; font-size: 11px; font-weight: 800; }}
QLabel#bubbleContent {{ background: transparent; border: none;
    color: #F3EDEF; font-size: 13px; }}
QProgressBar {{ background: #241D22; border: 1px solid #49353F;
    color: #EEE4E8; border-radius: 8px; text-align: center; min-height: 15px; }}
QProgressBar::chunk {{ background: #CE3B47; border-radius: 7px; }}
QMenu {{ background: #191519; border: 1px solid #523740; border-radius: 9px;
    padding: 6px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 5px; }}
QMenu::item:selected {{ background: #48202B; }}
"""
