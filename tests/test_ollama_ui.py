"""Qt rendering checks; exercised on the real Windows CI runner with PySide6."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication
    from sytox.ui import MainWindow, OllamaHelpDialog
    from sytox.ollama_setup import OllamaStatus
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, 'PySide6 is unavailable on this platform')
class OllamaQtOnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-unit-test'])

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.environ = patch.dict(os.environ, {'APPDATA': self.home.name})
        self.environ.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window._is_exiting = True
        if self.window.tray:
            self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        self.environ.stop()
        self.home.cleanup()

    def test_offline_does_not_claim_ki_ready(self):
        self.window._model_status_checked(OllamaStatus('offline', 'Ollama nicht erreichbar',
                                                      'Bitte Ollama starten'))
        self.assertIn('Ollama nicht erreichbar', self.window.status_chip.text())
        self.assertIn('Ollama starten', self.window.model_status_label.text())

    def test_ready_status_is_clear(self):
        self.window._model_status_checked(OllamaStatus('ready', 'KI bereit',
                                                      'Ollama verbunden · qwen2.5-coder:7b'))
        self.assertIn('KI bereit', self.window.status_chip.text())

    def test_setup_dialog_contains_copyable_command(self):
        dialog = OllamaHelpDialog('qwen2.5-coder:7b', None, self.window)
        from PySide6.QtWidgets import QLineEdit
        line_edits = dialog.findChildren(QLineEdit)
        self.assertTrue(any(x.text() == 'ollama pull qwen2.5-coder:7b' for x in line_edits))
        dialog.close()


if __name__ == '__main__':
    unittest.main()
