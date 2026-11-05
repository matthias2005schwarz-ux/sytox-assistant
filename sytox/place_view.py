"""Optional embedded Instant Street View in SYTOX's native right panel."""
from __future__ import annotations

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
)

from .place_queries import instant_street_view_url, normalize_place


class InstantStreetViewPanel(QFrame):
    """Show a location hint without contacting third parties until clicked.

    Qt WebEngine is loaded lazily. If unavailable or incompatible with the
    service, the official website can still be opened in the system browser.
    """
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('utilityCard')
        self.viewer = None
        self._current_url = None
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(9)

        top = QHBoxLayout()
        heading = QLabel('◈  INSTANT STREET VIEW')
        heading.setObjectName('sectionTitle')
        top.addWidget(heading)
        top.addStretch()
        dismiss = QPushButton('✕')
        dismiss.setToolTip('Straßenansicht schließen')
        dismiss.setMaximumWidth(36)
        dismiss.clicked.connect(lambda: self.dismissed.emit())
        top.addWidget(dismiss)
        box.addLayout(top)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText('Ort oder Adresse eingeben …')
        self.location_edit.setAccessibleName('Street View Ort oder Adresse')
        self.location_edit.returnPressed.connect(self.load_place)
        box.addWidget(self.location_edit)

        actions = QHBoxLayout()
        self.show_button = QPushButton('Ansicht laden')
        self.show_button.setObjectName('primary')
        self.show_button.clicked.connect(self.load_place)
        actions.addWidget(self.show_button)

        self.browser_button = QPushButton('Im Browser')
        self.browser_button.setObjectName('subtle')
        self.browser_button.clicked.connect(self.open_browser)
        actions.addWidget(self.browser_button)
        box.addLayout(actions)

        self.message = QLabel(
            'Die Straßenansicht kommt von instantstreetview.com. '
            'Erst nach deinem Klick wird der eingegebene Ort dorthin übertragen.'
        )
        self.message.setObjectName('panelDescription')
        self.message.setWordWrap(True)
        box.addWidget(self.message)

        self.view_area = QWidget()
        self.view_area.setObjectName('streetViewSurface')
        self.view_layout = QVBoxLayout(self.view_area)
        self.view_layout.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.view_area, 1)
        self.view_area.hide()
        self.hide()

    def offer_location(self, place: str):
        """Offer an on-device suggestion; does not load a remote page."""
        location = normalize_place(place)
        if not location:
            return
        self.location_edit.setText(location)
        self.message.setText(
            'Ort erkannt. Klicke auf „Ansicht laden“, um ihn an Instant '
            'Street View zu senden, oder ändere die Adresse zuerst.'
        )
        self.setVisible(True)

    def _url_from_input(self):
        try:
            return QUrl(instant_street_view_url(self.location_edit.text()))
        except ValueError as exc:
            self.message.setText(str(exc))
            self.location_edit.setFocus()
            return None

    def load_place(self):
        url = self._url_from_input()
        if url is None:
            return
        # Do not insert Qt WebEngine into startup or the offline test runner.
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except (ImportError, OSError):
            self.message.setText(
                'Die eingebettete Ansicht benötigt Qt WebEngine. '
                '„Im Browser“ öffnet den Ort trotzdem ohne eigenen API-Schlüssel.'
            )
            return
        if self.viewer is None:
            self.viewer = QWebEngineView(self.view_area)
            self.viewer.setMinimumHeight(330)
            self.viewer.setAccessibleName('Interaktive Street View Straßenansicht')
            self.viewer.loadFinished.connect(self._view_loaded)
            self.view_layout.addWidget(self.viewer)
        self.view_area.show()
        self._current_url = url
        self.message.setText('Verbinde mit Instant Street View …')
        self.viewer.load(url)

    def _view_loaded(self, success: bool):
        self.message.setText(
            'Street View geladen. Du kannst dich direkt in der Ansicht umsehen.'
            if success else
            'Die Website konnte nicht eingebettet werden. '
            'Öffne denselben Ort mit „Im Browser“.'
        )

    def open_browser(self):
        url = self._url_from_input()
        if url is not None:
            if QDesktopServices.openUrl(url):
                self.message.setText('Instant Street View im Browser geöffnet.')
            else:
                self.message.setText('Browser konnte nicht geöffnet werden.')
