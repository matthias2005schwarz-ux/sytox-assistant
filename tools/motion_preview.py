"""Record the actual native chat controls using disposable, offline example data.

The PNG is a real window grab. The video contains unchanged window-grab frames;
encoding is optional and never installs additional dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if sys.platform.startswith('linux'):
    os.environ.setdefault('QT_AUDIO_BACKEND', 'pulseaudio')

from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QPushButton

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sytox.ui import MainWindow


FPS = 24
FRAME_COUNT = 132
EXAMPLE = '''## Direktes Feedback, ruhigere Bewegungen

**So fühlt sich die Oberfläche jetzt an:**

- Buttons reagieren sanft auf Maus und Tastaturfokus.
- Neue Nachrichten blenden kurz ein.
- Die Punkte bewegen sich nur während einer laufenden Antwort.

```python
def begruessung(name):
    return f"Hallo, {name}!"
```

> Lokale Animationsvorschau mit Beispieltext. Es läuft keine Modellanfrage.
'''


def encode_video(frame_directory, destination):
    """Encode captured frames as local MP4, or report the available PNG only."""
    executable = shutil.which('ffmpeg')
    if executable is None:
        print('No ffmpeg available; PNG captured, video skipped.')
        return None
    video = destination / 'motion-preview.mp4'
    completed = subprocess.run(
        [executable, '-hide_banner', '-loglevel', 'error', '-y',
         '-framerate', str(FPS), '-i', str(frame_directory / 'frame-%04d.png'),
         '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '18',
         '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(video)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding='utf-8', errors='replace', timeout=60, check=False)
    if completed.returncode or not video.is_file() or video.stat().st_size < 10000:
        video.unlink(missing_ok=True)
        print('Video encoding unavailable; PNG captured. ' + completed.stdout[-800:])
        return None
    return video


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: python tools/motion_preview.py OUTPUT_DIRECTORY')
    destination = Path(sys.argv[1]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    screenshot = destination / 'motion-preview.png'
    with tempfile.TemporaryDirectory(prefix='sytox-motion-preview-') as temporary:
        temporary = Path(temporary)
        profile = temporary / 'profile'
        frames = temporary / 'frames'
        frames.mkdir()
        with patch.dict(os.environ, {'APPDATA': str(profile)}), \
             patch.object(MainWindow, 'check_model_status'), \
             patch.object(MainWindow, 'check_for_updates'):
            app = QApplication.instance() or QApplication(['sytox-motion-preview'])
            window = MainWindow()
            if not hasattr(window, '_set_response_activity'):
                raise RuntimeError('The native motion UI integration is required for this preview.')
            window.resize(1440, 960)
            window.chat_heading.setText('Weichere Übergänge und direktes Feedback')
            window.status_chip.setText('DARSTELLUNGS-VORSCHAU')
            window.model_status_label.setText('Lokale Animationsvorschau · keine Modellanfrage')
            window.state.setText('Animationsvorschau · lokale Beispieldaten')
            window.show()
            timer = QTimer(window)
            timer.setInterval(round(1000 / FPS))
            progress = {'frame': 0, 'error': None, 'copy_button': None}

            def stop():
                timer.stop()
                window._set_response_activity(False)
                window._is_exiting = True
                if window.tray:
                    window.tray.hide()
                window.close()
                app.quit()

            def capture():
                index = progress['frame']
                try:
                    if index == 12:
                        window.input.setFocus()
                        window.input.setPlainText('Zeig mir die ruhigere Oberfläche mit einem Codebeispiel.')
                    elif index == 24:
                        QCoreApplication.sendEvent(window.send_btn, QEvent(QEvent.Enter))
                    elif index == 35:
                        QCoreApplication.sendEvent(window.send_btn, QEvent(QEvent.Leave))
                        window.add_bubble('user', window.input.toPlainText())
                        window.input.clear()
                    elif index == 40:
                        window._set_response_activity(True)
                        window.state.setText('Animationsvorschau · Antwort wird dargestellt')
                    elif index == 60:
                        window.add_bubble('assistant', EXAMPLE)
                    elif index == 88:
                        window._set_response_activity(False)
                        window.state.setText('Animationsvorschau · Darstellung fertig')
                    elif index == 101:
                        progress['copy_button'] = window.findChild(QPushButton, 'copyCodeButton')
                        if progress['copy_button'] is not None:
                            QCoreApplication.sendEvent(progress['copy_button'], QEvent(QEvent.Enter))
                    elif index == 108 and progress['copy_button'] is not None:
                        progress['copy_button'].click()
                    elif index == 120 and progress['copy_button'] is not None:
                        QCoreApplication.sendEvent(progress['copy_button'], QEvent(QEvent.Leave))
                    image = window.grab()
                    if image.isNull() or not image.save(str(frames / f'frame-{index:04d}.png'), 'PNG'):
                        raise RuntimeError(f'Native frame {index} was not captured.')
                    if index == FRAME_COUNT - 1:
                        if not image.save(str(screenshot), 'PNG'):
                            raise RuntimeError('Native screenshot was not saved.')
                        stop()
                    progress['frame'] += 1
                except Exception as exc:
                    progress['error'] = exc
                    stop()

            timer.timeout.connect(capture)
            QTimer.singleShot(0, timer.start)
            app.exec()
            if progress['error'] is not None:
                raise progress['error']
            if progress['frame'] != FRAME_COUNT or not screenshot.is_file() or screenshot.stat().st_size < 10000:
                raise RuntimeError('Native animation capture did not complete.')
        video = encode_video(frames, destination)
    print(f'Native screenshot saved: {screenshot}')
    if video:
        print(f'Native animation saved: {video}')
    print('Recorded local example data; no model, microphone or network was used.')


if __name__ == '__main__':
    main()
