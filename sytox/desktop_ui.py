"""Native, consent-first desktop controls for Windows.

The panel only discovers running windows and Start Menu shortcuts.
Launching a shortcut or activating an existing window needs an explicit click
and approval. It never types, clicks controls, or executes shell commands.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QListWidget, QListWidgetItem, QMessageBox, QGroupBox,
)

from .pc_control import WindowsDesktop


class DesktopControlDialog(QDialog):
    """Human-driven window picker and shortcut launcher; no automatic execution."""

    def __init__(self, desktop=None, parent=None):
        super().__init__(parent)
        self.desktop = desktop if desktop is not None else WindowsDesktop()
        self.setWindowTitle('SYTOX · Windows-Steuerung')
        self.resize(680, 600)
        self.setMinimumWidth(530)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        heading = QLabel('WINDOWS-STEUERUNG')
        heading.setObjectName('sectionTitle')
        root.addWidget(heading)
        help_text = QLabel(
            'Finde geöffnete Fenster oder Programme. SYTOX startet und fokussiert '
            'nichts ohne deine ausdrückliche Bestätigung.'
        )
        help_text.setWordWrap(True)
        help_text.setObjectName('panelDescription')
        root.addWidget(help_text)

        windows_box = QGroupBox('Offene Fenster')
        windows_lay = QVBoxLayout(windows_box)
        self.window_list = QListWidget()
        self.window_list.setObjectName('desktopWindowList')
        self.window_list.setAccessibleName('Offene Windows-Fenster')
        windows_lay.addWidget(self.window_list)
        windows_buttons = QHBoxLayout()
        refresh = QPushButton('Fenster aktualisieren')
        refresh.clicked.connect(self.refresh_windows)
        windows_buttons.addWidget(refresh)
        focus = QPushButton('Fenster aktivieren')
        focus.setObjectName('subtle')
        focus.clicked.connect(self.focus_window)
        windows_buttons.addWidget(focus)
        windows_lay.addLayout(windows_buttons)
        root.addWidget(windows_box, 1)

        apps_box = QGroupBox('Programme suchen')
        apps_lay = QVBoxLayout(apps_box)
        search_row = QHBoxLayout()
        self.app_query = QLineEdit()
        self.app_query.setObjectName('desktopAppQuery')
        self.app_query.setAccessibleName('Programmname')
        self.app_query.setPlaceholderText('z. B. Editor, Rechner oder Firefox')
        self.app_query.returnPressed.connect(self.search_apps)
        search_row.addWidget(self.app_query)
        find = QPushButton('Suchen')
        find.clicked.connect(self.search_apps)
        search_row.addWidget(find)
        apps_lay.addLayout(search_row)
        self.app_list = QListWidget()
        self.app_list.setObjectName('desktopAppList')
        self.app_list.setAccessibleName('Gefundene Programme')
        apps_lay.addWidget(self.app_list)
        launch = QPushButton('Ausgewähltes Programm starten')
        launch.setObjectName('primary')
        launch.clicked.connect(self.launch_app)
        apps_lay.addWidget(launch)
        root.addWidget(apps_box, 1)

        self.status = QLabel('Bereit · Änderungen an Windows brauchen deine Zustimmung.')
        self.status.setObjectName('panelDescription')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.refresh_windows()

    def _problem(self, action, exc):
        self.status.setText(f'{action}: {exc}')
        QMessageBox.warning(self, 'Windows-Steuerung', str(exc))

    def refresh_windows(self):
        self.window_list.clear()
        try:
            entries = self.desktop.windows()
        except Exception as exc:
            self.status.setText('Fenster konnten nicht geladen werden: ' + str(exc))
            return
        for entry in entries:
            item = QListWidgetItem(
                ('Aktiv · ' if entry.get('active') else '') + str(entry['title'])
            )
            item.setData(Qt.UserRole, entry['id'])
            self.window_list.addItem(item)
        self.status.setText(f'{len(entries)} Fenster gefunden. Aktivieren nur nach Bestätigung.')

    def focus_window(self):
        item = self.window_list.currentItem()
        if item is None:
            self.status.setText('Bitte zuerst ein Fenster auswählen.')
            return
        window_id = item.data(Qt.UserRole)
        try:
            target = self.desktop.window(window_id)
            answer = QMessageBox.question(
                self, 'Fenster aktivieren?',
                f"Zu diesem Fenster wechseln?\n\n{target['title']}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                self.status.setText('Fensterwechsel abgebrochen.')
                return
            self.desktop.activate(target['id'])
            self.status.setText('Fenster aktiviert.')
            self.refresh_windows()
        except Exception as exc:
            self._problem('Fensterwechsel fehlgeschlagen', exc)

    def search_apps(self):
        query = self.app_query.text().strip()
        self.app_list.clear()
        try:
            entries = self.desktop.find_apps(query)
        except Exception as exc:
            self.status.setText('Programmsuche: ' + str(exc))
            return
        for entry in entries:
            item = QListWidgetItem(str(entry['name']))
            item.setData(Qt.UserRole, str(entry['path']))
            item.setToolTip(str(entry['path']))
            self.app_list.addItem(item)
        self.status.setText(
            f'{len(entries)} Programme gefunden. Erst auswählen, dann Start bestätigen.'
        )

    def launch_app(self):
        item = self.app_list.currentItem()
        if item is None:
            self.status.setText('Bitte zuerst ein Programm auswählen.')
            return
        path = Path(item.data(Qt.UserRole))
        if not path.is_file() or path.suffix.casefold() not in ('.lnk', '.exe'):
            self.status.setText('Programmverknüpfung nicht mehr vorhanden. Suche erneut.')
            return
        answer = QMessageBox.question(
            self, 'Programm wirklich starten?',
            f'Dieses Programm auf deinem PC starten?\n\n{item.text()}\n{path}',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if answer != QMessageBox.Yes:
            self.status.setText('Programmstart abgebrochen.')
            return
        try:
            if not path.is_file():
                raise FileNotFoundError('Verknüpfung wurde entfernt.')
            self.desktop.open_app(path)
            self.status.setText('Startbefehl an Windows übergeben.')
        except Exception as exc:
            self._problem('Programmstart fehlgeschlagen', exc)
