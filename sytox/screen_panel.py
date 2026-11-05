"""Visible screen controls for the local desktop app."""
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QScrollArea


class ScreenPanel:
    def build_ui(self):
        super().build_ui()
        top = self.findChild(QFrame, 'topbar')
        self.screen_indicator = QLabel('● BILDSCHIRM AUS')
        top.layout().insertWidget(2, self.screen_indicator)
        card = QFrame()
        card.setObjectName('utilityCard')
        box = QVBoxLayout(card)
        box.addWidget(QLabel('BILDSCHIRMHILFE'))
        self.screen_state = QLabel('Aus · keine Aufnahme')
        box.addWidget(self.screen_state)
        self.screen_toggle = QPushButton('Bildschirmhilfe einschalten')
        self.screen_toggle.clicked.connect(self.toggle_screen)
        box.addWidget(self.screen_toggle)
        self.screen_ask = QPushButton('Bildschirm jetzt erklären')
        self.screen_ask.setEnabled(False)
        self.screen_ask.clicked.connect(
            lambda: self.ask_screen('Was zeigt mein Bildschirm?'))
        box.addWidget(self.screen_ask)
        column = self.utility_panel.layout()
        scroll = next(column.itemAt(i).widget() for i in range(column.count())
                      if isinstance(column.itemAt(i).widget(), QScrollArea))
        contents = scroll.widget().layout()
        contents.insertWidget(max(0, contents.count() - 1), card)
