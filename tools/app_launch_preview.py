"""Capture real app-opening dialogs from explicitly labelled, inert demo data.

Uses no model, microphone, network or Windows action. Every launch/activation
entry point on the fake adapter raises if accidentally called.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if sys.platform.startswith('linux'):
    os.environ.setdefault('QT_AUDIO_BACKEND', 'pulseaudio')

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLabel

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sytox.app_launch_ui import AppLaunchDialog
from sytox.theme import STYLE


class DemoDesktop:
    """Read-only metadata for the preview, never an actual desktop adapter."""

    def __init__(self, apps=(), windows=()):
        self.apps = list(apps)
        self.app_windows = list(windows)
        self.action_attempts = 0

    def find_apps(self, query):
        return [dict(entry) for entry in self.apps]

    def find_app_windows(self, query):
        return [dict(entry) for entry in self.app_windows]

    def open_app(self, path):
        self.action_attempts += 1
        raise AssertionError('The preview must never request a program launch.')

    def activate(self, window_id):
        self.action_attempts += 1
        raise AssertionError('The preview must never request a window activation.')


def capture(app, desktop, destination, scenario):
    dialog = AppLaunchDialog('Spotify', desktop=desktop)
    banner = QLabel('Lokale Ablaufvorschau · keine Windows-Aktion')
    banner.setObjectName('panelDescription')
    banner.setTextFormat(Qt.PlainText)
    banner.setWordWrap(True)
    dialog.layout().insertWidget(0, banner)
    dialog.show()
    loop = QEventLoop()
    timeout = QTimer(dialog)
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    dialog.lookup_finished.connect(loop.quit)
    timeout.start(10000)
    if dialog._lookup_worker is not None:
        loop.exec()
    timeout.stop()
    app.processEvents()
    settle = QEventLoop()
    QTimer.singleShot(80, settle.quit)
    settle.exec()
    try:
        if dialog._lookup_worker is not None:
            raise RuntimeError('Demo metadata lookup did not finish.')
        if scenario == 'choose-app':
            if (dialog.candidate_list.count() != 2 or dialog.candidate_list.currentRow() != -1
                    or dialog.confirm_button.isEnabled()):
                raise RuntimeError('The multiple-match preview is not awaiting an explicit choice.')
        elif scenario == 'running-window':
            if dialog.confirm_button.text() != 'Nach vorne holen' or not dialog.confirm_button.isEnabled():
                raise RuntimeError('The running-window preview did not resolve its inert process metadata.')
        elif not dialog.confirm_button.isEnabled() or dialog.confirm_button.text() != 'Starten':
            raise RuntimeError('The single-match preview did not resolve its inert shortcut.')
        output = destination / (scenario + '.png')
        image = dialog.grab()
        if image.isNull() or not image.save(str(output), 'PNG') or output.stat().st_size < 10000:
            raise RuntimeError('The native dialog screenshot was not saved.')
        if desktop.action_attempts:
            raise RuntimeError('An action was incorrectly attempted during the preview.')
        print(f'Native dialog preview saved: {output}')
    finally:
        dialog.prepare_close()
        worker = dialog._lookup_worker
        if worker is not None:
            worker.wait(3000)
            app.processEvents()
            if worker.isRunning():
                raise RuntimeError('The inert demo lookup did not stop cleanly.')
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: python tools/app_launch_preview.py OUTPUT_DIRECTORY')
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(['sytox-app-launch-preview'])
    app.setStyleSheet(STYLE)
    with tempfile.TemporaryDirectory(prefix='sytox-app-launch-preview-') as temporary:
        demo = Path(temporary)
        user_shortcut = demo / 'Nutzer-Startmenü' / 'Spotify.lnk'
        common_shortcut = demo / 'Gemeinsames-Startmenü' / 'Spotify.lnk'
        for path in (user_shortcut, common_shortcut):
            path.parent.mkdir()
            path.write_bytes(b'INERT SYTOX PREVIEW DATA - NOT A WINDOWS SHORTCUT')
        first = {'name': 'Spotify', 'path': str(user_shortcut)}
        second = {'name': 'Spotify', 'path': str(common_shortcut)}
        capture(app, DemoDesktop(apps=[first]), destination, 'single-shortcut')
        capture(app, DemoDesktop(windows=[{
            'id': 42, 'app_name': 'Spotify', 'title': 'Spotify · Beispielwiedergabe',
            'executable': r'C:\Demo\Spotify\Spotify.exe', 'active': False,
        }]), destination, 'running-window')
        capture(app, DemoDesktop(apps=[first, second]), destination, 'choose-app')
    print('Captured local example metadata only; no Windows action, model, microphone or network was used.')


if __name__ == '__main__':
    main()
