"""Capture the actual PySide6 main window, headlessly, on the Windows CI runner.

Uses a disposable APPDATA profile. No user documents, microphone, browser,
external AI, or PC actions are opened by this screenshot check.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sytox.ui import MainWindow


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: python tools/windows_ui_preview.py OUTPUT.png')
    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sytox_visual_') as folder:
        os.environ['APPDATA'] = folder
        app = QApplication.instance() or QApplication(['sytox-ui-preview'])
        # Windows's offscreen Qt platform can fail to discover OS fonts itself.
        # Load font *from the runner's own Windows installation*; no font bytes
        # are bundled or redistributed with SYTOX.
        windows_fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for candidate in ('segoeui.ttf', 'arial.ttf'):
            path = windows_fonts / candidate
            if path.is_file():
                fid = QFontDatabase.addApplicationFont(str(path))
                print(f'[PREVIEW] Font {candidate}: id={fid}; families={QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []}', flush=True)
        window = MainWindow()
        window.resize(1440, 900)
        window.show()
        result = {'saved': False}

        def capture():
            app.processEvents()
            pixmap = window.grab()
            if pixmap.isNull() or pixmap.width() < 900:
                raise RuntimeError('Qt did not render the real workspace')
            result['saved'] = pixmap.save(str(output), 'PNG')
            window._is_exiting = True
            window.close()
            app.quit()

        QTimer.singleShot(650, capture)
        QTimer.singleShot(18000, app.quit)
        app.exec()
        if not result['saved'] or not output.exists() or output.stat().st_size < 10000:
            raise RuntimeError('Real Windows UI preview was not saved')
        print(f'[OK] Native window screenshot: {output} ({output.stat().st_size:,} bytes)')


if __name__ == '__main__':
    main()
