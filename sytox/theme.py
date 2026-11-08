"""SYTOX native desktop visual system.

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
QFrame#sidebar {{ background-color: #101012; border-right: 1px solid {EDGE}; }}
QFrame#right {{ background-color: #101012; border-left: 1px solid {EDGE}; }}
QFrame#topbar {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #1B161A, stop:1 #111013);
    border-bottom: 1px solid #3A282F;
}}
QFrame#composePanel {{ background-color: #0E0C0F; border-top: 1px solid #30232A; }}
QFrame#inputCard {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #1D171C, stop:1 #141215);
    border: 1px solid #5A3742; border-radius: 18px;
}}
QFrame#inputCard:hover {{ border-color: #8B4653; }}
QFrame#inputCard[composing="true"] {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #231A20, stop:1 #171216);
    border-color: #CB5865;
}}
QFrame#utilityCard {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #1D1A1D, stop:1 #161417);
    border: 1px solid #3B2E35; border-radius: 15px;
}}
QFrame#hero {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #3B1821, stop:0.43 #20151B, stop:1 #111013);
    border: 1px solid #763642; border-radius: 22px;
}}
QLabel#brandName {{ color: #FFFFFF; font-size: 24px; font-weight: 900; }}
QLabel#brandSubtitle {{ color: #A79CA2; font-size: 10px; font-weight: 650; }}
QLabel#sectionTitle {{ color: #E7DBDE; font-size: 10px; font-weight: 800; }}
QPushButton#sectionToggle {{ text-align: left; color: #E7DBDE; font-size: 10px;
    font-weight: 800; padding: 7px 2px; border: none; background: transparent; }}
QPushButton#sectionToggle:hover {{ color: #FF9099; }}
QPushButton#sectionToggle:checked {{ color: #F6A1A9; }}
QPushButton#copyReplyButton, QPushButton#copyCodeButton {{ background: transparent; border: none;
    color: #A89CA0; font-size: 11px; padding: 4px 8px; }}
QPushButton#copyReplyButton:hover, QPushButton#copyCodeButton:hover {{
    color: #FFB2BA; background: #352029; border-radius: 6px;
}}
QPushButton#copyReplyButton:pressed, QPushButton#copyCodeButton:pressed {{
    color: #FFFFFF; background: #4B2731; border-radius: 6px;
}}
QLabel#panelDescription {{ color: #BBAFB5; font-size: 12px; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#motionHint {{ color: #BDAAB2; font-size: 11px; }}
QLabel#responseState {{ color: #B9AAB1; font-size: 12px; font-weight: 500; }}
QLabel#responseState[working="true"] {{ color: #F09AA6; font-weight: 650; }}
QLabel#heroEyebrow {{ color: #F39299; font-size: 11px; font-weight: 800; }}
QLabel#heroTitle {{ color: #FFFFFF; font-size: 27px; font-weight: 850; }}
QLabel#heroCopy {{ color: #C8B9BF; font-size: 13px; }}
QLabel#chatTitle {{ color: #F8F3F4; font-size: 18px; font-weight: 760; }}
QLabel#version {{ color: #91838C; font-size: 10px; }}
QLabel#statusChip {{ color: #E6D1D8; background: #2B1D24;
    border: 1px solid #60404A; border-radius: 11px;
    padding: 5px 11px; font-size: 11px; font-weight: 700; }}
QPushButton {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #2E272D, stop:1 #211C21);
    border: 1px solid #4B3741;
    border-radius: 10px; padding: 10px 13px; min-height: 17px;
    color: #EEE8EA; font-weight: 650; }}
QPushButton:hover {{ background: #3B2932; border-color: #A45765; color: #FFF8FA; }}
QPushButton:pressed {{ background: #21151B; border-color: #D56A78; }}
QPushButton:disabled {{ color: #877B83; background: #1B171B; border-color: #32282E; }}
QPushButton#primary {{
    background: qlineargradient(x1:0,y1:0,x2:0.6,y2:1,
        stop:0 #E14452, stop:0.5 #CC3443, stop:1 #A92433);
    border: 1px solid #F06773; color: #FFFFFF; font-weight: 800;
}}
QPushButton#primary:hover {{
    background: qlineargradient(x1:0,y1:0,x2:0.6,y2:1,
        stop:0 #F65B67, stop:1 #C32B3C);
    border-color: #FF9BA3;
}}
QPushButton#primary:pressed {{ background: #A02636; border-color: #F58590; }}
QPushButton#primary:disabled {{ background: #49232D; border-color: #62313D; color: #B98E99; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent;
    color: #ADA4A9; text-align: left; }}
QPushButton#ghost:hover {{ background: #211A1E;
    border-color: #453039; color: #FFF4F5; }}
QPushButton#subtle {{ background: #251B22; border-color: #51313E;
    color: #EEDDE0; }}
QPushButton#subtle:hover {{ background: #3B222D; border-color: #A64D60; }}
QPushButton#micButton {{
    background: #251C23; border: 1px solid #69404C;
    border-radius: 14px; padding: 0; min-height: 0;
}}
QPushButton#micButton:hover {{ background: #40212B; border-color: #D25966; }}
QPushButton#micButton:pressed, QPushButton#micButton:checked {{
    background: #69202E; border: 1px solid #FF6171;
}}
QPushButton#micButton:disabled {{ background: #231C21; border-color: #4A3038; }}
QPushButton#micButton:focus {{ border-color: #FC8290; }}
QPushButton#suggestion {{ background: #281B22; border: 1px solid #6A3543;
    color: #EBD5D9; border-radius: 12px; text-align: left; padding: 10px 14px; }}
QPushButton#suggestion:hover {{ background: #41202D; border-color: #D36474; }}
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
QListWidget::item {{ color: #C8B9C0; border: 1px solid transparent;
    border-radius: 10px; padding: 11px 12px; margin: 2px 4px; }}
QListWidget::item:selected {{
    color: #FFFFFF;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #57222F, stop:1 #2C171F);
    border: 1px solid #9D4558;
}}
QListWidget::item:hover:!selected {{ color: #FFF1F5; background: #2B1D25; border-color: #4C2D3A; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: #100E11; width: 8px; border: none; }}
QScrollBar::handle:vertical {{ background: #513B46; border-radius: 4px;
    min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #985163; }}
QScrollBar::handle:vertical:pressed {{ background: #CE6575; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QSplitter::handle {{ background: #38252F; }}
QSplitter::handle:hover {{ background: #A54A5D; }}
QFrame#bubbleUser {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #48202C, stop:1 #2C171F);
    border: 1px solid #974657; border-radius: 17px;
}}
QFrame#bubbleAssistant {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 #1E1A1F, stop:1 #161417);
    border: 1px solid #49333F; border-radius: 17px;
}}
QLabel#bubbleHeadingUser {{ background: transparent; border: none;
    color: #FFABB4; font-size: 11px; font-weight: 800; }}
QLabel#bubbleHeadingAssistant {{ background: transparent; border: none;
    color: #F2808B; font-size: 11px; font-weight: 800; }}
QLabel#bubbleContent {{ background: transparent; border: none;
    color: #F3EDEF; font-size: 13px; }}
QTextBrowser#markdownProse {{ background: transparent; border: none;
    padding: 0; color: #F3EDEF; font-size: 14px;
    selection-background-color: #8D2632; }}
QFrame#codeBlock {{ background: #100F13; border: 1px solid #583846;
    border-radius: 11px; }}
QWidget#codeHeader {{ background: #241A21; border: none; }}
QLabel#codeLanguage {{ color: #F097A0; font-size: 11px; font-weight: 700;
    background: transparent; border: none; }}
QPlainTextEdit#codeEditor {{ background: #100F13; color: #EFEAF1;
    border: none; border-radius: 0; padding: 10px 12px;
    selection-background-color: #71333F; }}
QPlainTextEdit#codeEditor:focus {{ border: none; }}
QProgressBar {{ background: #21171F; border: 1px solid #53313F;
    color: #EEE4E8; border-radius: 8px; text-align: center; min-height: 15px; }}
QProgressBar::chunk {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #B42A3D, stop:1 #EC606E); border-radius: 7px;
}}
QMenu {{ background: #191519; border: 1px solid #523740; border-radius: 9px;
    padding: 6px; }}
QMenu::item {{ padding: 8px 24px; border-radius: 5px; }}
QMenu::item:selected {{ background: #5A2637; color: #FFFFFF; }}
QPushButton#panelToggle {{
    background: #1E171B; border: 1px solid #483039;
    border-radius: 10px; padding: 9px 15px; color: #E9D7DB;
}}
QPushButton#panelToggle:hover {{ background: #302027;
    border-color: #A84551; color: #FFF7F8; }}
QPushButton#panelToggle:checked {{ background: #45212B;
    border-color: #B74755; color: #FFFFFF; }}
QPushButton:focus, QLineEdit:focus, QComboBox:focus {{
    border-color: #E26570;
}}
QLineEdit#chatSearch {{
    background: #171419; border: 1px solid #34272E;
    border-radius: 11px; padding: 11px 13px;
}}
QLineEdit#chatSearch:focus {{ background: #20181D;
    border-color: #A84551; }}
QFrame#utilityCard:hover {{ border-color: #69404F; }}
QGroupBox {{
    background: #141115; border: 1px solid #3C2B34;
    border-radius: 12px; margin-top: 15px; padding: 12px 11px 10px;
    font-weight: 700; color: #F0DDE2;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 13px; padding: 0 5px;
    color: #DFA3AD;
}}
QListWidget#desktopWindowList, QListWidget#desktopAppList {{
    background: #171318; border: 1px solid #33252C;
    border-radius: 9px; min-height: 90px;
}}
QWidget#messageSurface {{ background: #09090C; }}
QScrollBar:horizontal {{ background: #100E11; height: 8px; border: none; }}
QScrollBar::handle:horizontal {{ background: #513B46; border-radius: 4px;
    min-width: 28px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::handle:horizontal:hover {{ background: #985163; }}
QScrollBar::handle:horizontal:pressed {{ background: #CE6575; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
"""
