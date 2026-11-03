"""Non-destructive native input check against an OWN Qt test window.

This file is only invoked on explicit request (-InteractiveDesktop) and never
sends inputs to other applications or reads user text/files.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    if os.name != 'nt':
        raise SystemExit('This test must run on a Windows desktop session.')
    from PySide6.QtWidgets import QApplication, QMainWindow, QTextEdit
    from sytox.pc_control import WindowsDesktop

    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowTitle('SYTOX SAFE INPUT TEST WINDOW')
    edit = QTextEdit()
    window.setCentralWidget(edit)
    window.resize(480, 220)
    window.show()
    app.processEvents()
    edit.setFocus()
    window.activateWindow()
    app.processEvents()
    time.sleep(.25)
    desktop = WindowsDesktop()
    hwnd = int(window.winId())
    try:
        current = desktop.window(hwnd)
        assert 'SYTOX SAFE INPUT TEST WINDOW' in current['title'], current
        desktop.activate(hwnd)
        if desktop.foreground_id() != hwnd:
            raise RuntimeError('Testfenster nicht im Vordergrund. Keine Eingabe gesendet.')
        text = 'SYTOX Windows äöüß 👋'
        desktop.type_unicode(text, lambda: (
            None if desktop.foreground_id() == hwnd else
            (_ for _ in ()).throw(RuntimeError('Fokus verloren'))))
        end = time.monotonic() + 3
        while time.monotonic() < end:
            app.processEvents()
            if edit.toPlainText() == text:
                print('Native Windows-Unicode-Eingabe OK')
                return 0
            time.sleep(.05)
        raise RuntimeError('Input unvollstaendig: ' + repr(edit.toPlainText()))
    finally:
        window.close()
        app.processEvents()


if __name__ == '__main__':
    raise SystemExit(main())
