"""Capture a real native example chat without contacting a model or any network."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
if sys.platform.startswith('linux'):
    os.environ.setdefault('QT_AUDIO_BACKEND', 'pulseaudio')

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sytox.ui import MainWindow

EXAMPLE = '''## So wird deine Liste übersichtlicher

**Die Änderung:** Aufgaben bekommen einen klaren Status. Erledigte Einträge bleiben erhalten.

1. Aufgaben hinzufügen und mit **einem Klick** abschließen.
2. Den Zustand lokal speichern.
3. Den Ablauf mit einem kleinen Test überprüfen.

### Python-Beispiel

```python
from dataclasses import dataclass

@dataclass
class Aufgabe:
    titel: str
    erledigt: bool = False

    def abschliessen(self):
        # Die Aufgabe bleibt in der Liste erhalten.
        self.erledigt = True
```

| Funktion | Verhalten |
| --- | --- |
| Hinzufügen | Neuer Eintrag in der Liste |
| Abschließen | Status wechselt auf erledigt |

> Der Code ist ein Darstellungsbeispiel. In dieser Vorschau läuft keine Modellanfrage.
'''


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: python tools/chat_render_preview.py OUTPUT.png')
    output = Path(sys.argv[1]).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sytox-chat-preview-') as profile, \
         patch.dict(os.environ, {'APPDATA': profile}), \
         patch.object(MainWindow, 'check_model_status'), \
         patch.object(MainWindow, 'check_for_updates'):
        app = QApplication.instance() or QApplication(['sytox-chat-preview'])
        window = MainWindow()
        window.resize(1440, 1040)
        window.chat_heading.setText('Lesbare Antworten und Code')
        window.status_chip.setText('DARSTELLUNGS-VORSCHAU')
        window.model_status_label.setText('Lokale Beispielantwort · keine Modellanfrage')
        window._rendering_history = True
        window.add_bubble('user', 'Zeig mir eine kleine Aufgabenliste mit Python-Beispiel.')
        window.add_bubble('assistant', EXAMPLE)
        window._rendering_history = False
        window.show()
        saved = []

        def capture():
            saved.append(window.grab().save(str(output), 'PNG'))
            window._is_exiting = True
            if window.tray:
                window.tray.hide()
            window.close()
            app.quit()

        QTimer.singleShot(700, capture)
        app.exec()
        if not saved or not saved[0] or output.stat().st_size < 10000:
            raise RuntimeError('Native chat preview was not captured')
    print(f'Native chat preview saved: {output}')


if __name__ == '__main__':
    main()
