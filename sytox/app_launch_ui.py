"""Direct native app confirmation; discovery never runs application code."""
from __future__ import annotations

from pathlib import Path
import stat

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem,
)

from .app_launch import resolve_app_request
from .pc_control import WindowsDesktop


def _shortcut_state(raw):
    path = Path(str(raw))
    if not path.is_absolute() or path.suffix.casefold() not in ('.lnk', '.exe') or path.is_symlink():
        raise ValueError('Der gefundene Programmeintrag ist keine gültige lokale Programmdatei.')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('Der Programmeintrag ist keine Datei.')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


class _AppLookup(QThread):
    resolved = Signal(object)

    def __init__(self, desktop, query, parent):
        super().__init__(parent)
        self.desktop, self.query = desktop, query

    def run(self):
        if self.isInterruptionRequested():
            return
        try:
            result = dict(resolve_app_request(self.desktop, self.query))
            candidates = []
            for original in result.get('candidates', []):
                candidate = dict(original)
                if candidate.get('kind') == 'app':
                    try:
                        candidate['_file_state'] = _shortcut_state(candidate.get('path', ''))
                    except (OSError, ValueError):
                        candidate['_file_state'] = None
                candidates.append(candidate)
            result['candidates'] = candidates
        except Exception:
            result = {'status': 'unavailable', 'query': self.query, 'candidates': [],
                      'message': 'Die lokale Programmsuche ist gerade nicht verfügbar. Bitte erneut versuchen.'}
        if not self.isInterruptionRequested():
            self.resolved.emit(result)


class AppLaunchDialog(QDialog):
    """Resolve in a worker, then require one explicit, specific confirmation."""

    feedback = Signal(str)
    lookup_finished = Signal()

    def __init__(self, query, desktop=None, parent=None):
        super().__init__(parent)
        self.query = str(query)
        self.desktop = desktop if desktop is not None else WindowsDesktop()
        self._lookup_worker = None
        self._close_requested = False
        self._closed = False
        self._action_started = False
        self._candidates = []
        self._selected = None
        self.setWindowTitle('SYTOX · Programm öffnen')
        self.resize(590, 380)
        self.setMinimumWidth(450)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)
        self.heading = QLabel()
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setObjectName('chatTitle')
        self.heading.setWordWrap(True)
        root.addWidget(self.heading)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setObjectName('panelDescription')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        self.candidate_list = QListWidget()
        self.candidate_list.setObjectName('desktopAppList')
        self.candidate_list.setAccessibleName('Passendes Programm oder Fenster auswählen')
        self.candidate_list.setStyleSheet('QListWidget#desktopAppList { min-height: 150px; }')
        self.candidate_list.currentRowChanged.connect(self._choose_row)
        root.addWidget(self.candidate_list, 1)
        self.target_name = QLabel()
        self.target_name.setTextFormat(Qt.PlainText)
        self.target_name.setWordWrap(True)
        self.target_name.setObjectName('sectionTitle')
        root.addWidget(self.target_name)
        self.target_detail = QLabel()
        self.target_detail.setTextFormat(Qt.PlainText)
        self.target_detail.setWordWrap(True)
        self.target_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.target_detail.setObjectName('panelDescription')
        root.addWidget(self.target_detail)
        root.addStretch(1)
        buttons = QHBoxLayout()
        self.retry_button = QPushButton('Erneut suchen')
        self.retry_button.setAutoDefault(False)
        self.retry_button.clicked.connect(self.start_lookup)
        buttons.addWidget(self.retry_button)
        buttons.addStretch(1)
        self.cancel_button = QPushButton('Abbrechen')
        self.cancel_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.cancel_button)
        self.confirm_button = QPushButton('Starten')
        self.confirm_button.setObjectName('primary')
        self.confirm_button.setAutoDefault(False)
        self.confirm_button.setAccessibleName('Ausgewählten Programmstart bestätigen')
        self.confirm_button.clicked.connect(self.confirm_selected)
        buttons.addWidget(self.confirm_button)
        root.addLayout(buttons)
        self.start_lookup()

    @property
    def lookup_running(self):
        return self._lookup_worker is not None and self._lookup_worker.isRunning()

    @property
    def pending_confirmation(self):
        return bool(self._candidates and not self._closed and not self._close_requested
                    and not self._action_started)

    def _set_status(self, text):
        self.status.setText(text)
        self.feedback.emit(text)

    def start_lookup(self):
        if self._lookup_worker is not None or self._closed or self._close_requested or self._action_started:
            return
        self.heading.setText(f'„{self.query}“ öffnen')
        self._set_status('Suche auf deinem PC …')
        self._candidates = []
        self._selected = None
        self.candidate_list.clear()
        self.candidate_list.hide()
        self.target_name.clear()
        self.target_detail.clear()
        self.confirm_button.setEnabled(False)
        self.retry_button.hide()
        self.cancel_button.setText('Abbrechen')
        worker = _AppLookup(self.desktop, self.query, self)
        self._lookup_worker = worker
        worker.resolved.connect(self._lookup_ready)
        worker.finished.connect(self._lookup_done)
        worker.start()

    def _lookup_ready(self, result):
        if self._closed or self._close_requested:
            return
        self._candidates = list(result.get('candidates') or [])
        state = result.get('status')
        self._set_status(str(result.get('message') or 'Bitte den passenden Eintrag bestätigen.'))
        if state == 'single' and len(self._candidates) == 1:
            candidate = self._candidates[0]
            if candidate.get('kind') == 'app' and candidate.get('_file_state') is None:
                self._candidates = []
                self._set_status('Der Programmeintrag wurde entfernt oder ist nicht lesbar. Bitte erneut suchen.')
                self._show_candidate(None)
                self.retry_button.show()
                self.cancel_button.setText('Schließen')
            else:
                self._show_candidate(candidate)
        elif state == 'multiple' and self._candidates:
            self.candidate_list.show()
            for candidate in self._candidates:
                location = candidate.get('title') if candidate.get('kind') == 'window' else candidate.get('path')
                item = QListWidgetItem(str(candidate.get('name') or self.query) + '\n' + str(location or ''))
                self.candidate_list.addItem(item)
            self.candidate_list.setCurrentRow(-1)
            self._show_candidate(None)
        else:
            self._candidates = []
            self._show_candidate(None)
            self.retry_button.show()
            self.cancel_button.setText('Schließen')
        self.cancel_button.setFocus()

    def _lookup_done(self):
        worker = self._lookup_worker
        self._lookup_worker = None
        if worker is not None:
            worker.deleteLater()
        if self._close_requested:
            self._finish_close()
        self.lookup_finished.emit()

    def _choose_row(self, row):
        candidate = self._candidates[row] if 0 <= row < len(self._candidates) else None
        self._show_candidate(candidate)

    def _show_candidate(self, candidate):
        self._selected = candidate
        self.target_name.setVisible(candidate is not None)
        self.target_detail.setVisible(candidate is not None)
        enabled = candidate is not None and not self._action_started and not self._close_requested
        self.confirm_button.setEnabled(enabled)
        if candidate is None:
            self.target_name.clear()
            self.target_detail.clear()
            return
        self.target_name.setText(str(candidate.get('name') or self.query))
        if candidate.get('kind') == 'window':
            self.confirm_button.setText('Nach vorne holen')
            self.confirm_button.setAccessibleName('Wechsel zum ausgewählten Fenster bestätigen')
            self.target_detail.setText('Bereits geöffnet · ' + str(candidate.get('title') or '') +
                                       '\n' + str(candidate.get('executable') or ''))
        else:
            self.confirm_button.setText('Starten')
            self.confirm_button.setAccessibleName('Ausgewählten Programmstart bestätigen')
            self.target_detail.setText(str(candidate.get('path') or ''))

    def confirm_selected(self):
        candidate = self._selected
        if candidate is None or self._closed or self._close_requested or self._action_started:
            return
        self._action_started = True
        self.confirm_button.setEnabled(False)
        self.candidate_list.setEnabled(False)
        self.retry_button.hide()
        try:
            if candidate.get('kind') == 'window':
                target = next((entry for entry in self.desktop.find_app_windows(self.query)
                               if entry.get('id') == candidate.get('window_id')
                               and str(entry.get('executable') or '').casefold() ==
                               str(candidate.get('executable') or '').casefold()), None)
                if target is None or not candidate.get('executable'):
                    raise LookupError('Das bestätigte Fenster ist nicht mehr verfügbar. Bitte erneut suchen.')
                self.desktop.activate(candidate['window_id'])
                self._set_status(str(candidate.get('name') or self.query) + ': Fenster aktiviert.')
            elif candidate.get('kind') == 'app':
                expected = candidate.get('_file_state')
                if expected is None or _shortcut_state(candidate.get('path', '')) != expected:
                    raise LookupError('Der Programmeintrag wurde verändert oder entfernt. Bitte erneut suchen.')
                self.desktop.open_app(Path(candidate['path']))
                self._set_status('Startbefehl für ' + str(candidate.get('name') or self.query) + ' an Windows übergeben.')
            else:
                raise ValueError('Der gewählte Eintrag kann nicht geöffnet werden.')
            self.cancel_button.setText('Schließen')
        except Exception as exc:
            self._set_status('Nicht geöffnet: ' + str(exc))
            self._selected = None
            self._candidates = []
            self.candidate_list.clear()
            self.candidate_list.hide()
            self._action_started = False
            self.candidate_list.setEnabled(True)
            self.retry_button.show()
            self.cancel_button.setText('Schließen')

    def _finish_close(self):
        if self._closed:
            return
        self._closed = True
        self._selected = None
        self._candidates = []
        self.confirm_button.setEnabled(False)
        super().reject()

    def prepare_close(self):
        self._close_requested = True
        self.confirm_button.setEnabled(False)
        if self.lookup_running:
            self._lookup_worker.requestInterruption()
            self.hide()
            return False
        self._finish_close()
        return True

    def reject(self):
        self.prepare_close()

    def closeEvent(self, event):
        if self.prepare_close():
            event.accept()
        else:
            event.ignore()
