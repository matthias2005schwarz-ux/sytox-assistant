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

    def test_dark_red_workspace_controls_and_suggestion(self):
        from PySide6.QtWidgets import QFrame
        cards = self.window.findChildren(QFrame, 'utilityCard')
        self.assertEqual(len(cards), 4)
        self.assertIsNotNone(self.window.empty_widget)
        self.window._use_suggestion('Erstelle eine Funktion')
        self.assertEqual(self.window.input.toPlainText(), 'Erstelle eine Funktion')
        self.assertEqual(self.window.chatlist.count(), 1)

    def test_focus_mode_hides_and_restores_tools_without_destroying_controls(self):
        from PySide6.QtWidgets import QFrame
        panel = self.window.utility_panel
        cards_before = self.window.findChildren(QFrame, 'utilityCard')
        self.assertEqual(len(cards_before), 4)
        self.assertFalse(panel.isHidden())

        self.window.toggle_focus_mode()
        self.assertTrue(panel.isHidden())
        self.assertTrue(self.window.focus_btn.isChecked())
        self.assertEqual(self.window.focus_btn.text(), 'Steuerzentrale')

        self.window.toggle_focus_mode()
        self.assertFalse(panel.isHidden())
        self.assertFalse(self.window.focus_btn.isChecked())
        self.assertEqual(self.window.focus_btn.text(), 'Fokusmodus')
        self.assertEqual(len(self.window.findChildren(QFrame, 'utilityCard')), 4)

    def test_spoken_desktop_command_opens_panel_without_issuing_agent_task(self):
        with patch.object(self.window, 'show_desktop_tools') as show_tools, \
             patch.object(self.window, 'send') as send:
            self.window.received_voice_command('Zeig mir die offenen Fenster')
        show_tools.assert_called_once_with(query='', list_windows=True)
        send.assert_not_called()

    def test_spoken_app_search_still_needs_click_and_approval(self):
        with patch.object(self.window, 'show_desktop_tools') as show_tools, \
             patch.object(self.window, 'send') as send:
            self.window.received_voice_command('Suche Programm Firefox')
        show_tools.assert_called_once_with(query='Firefox', list_windows=False)
        send.assert_not_called()

    def test_first_message_replaces_empty_state_without_losing_text(self):
        from PySide6.QtWidgets import QFrame, QLabel
        self.assertIsNotNone(self.window.empty_widget)
        self.window.add_bubble('user', '<script>not executable</script>')
        self.assertIsNone(self.window.empty_widget)
        messages = self.window.findChildren(QFrame, 'bubbleUser')
        self.assertEqual(len(messages), 1)
        self.assertTrue(any(label.text() == '<script>not executable</script>'
                            for label in messages[0].findChildren(QLabel)))

    def test_setup_dialog_contains_copyable_command(self):
        dialog = OllamaHelpDialog('qwen2.5-coder:7b', None, self.window)
        from PySide6.QtWidgets import QLineEdit
        line_edits = dialog.findChildren(QLineEdit)
        self.assertTrue(any(x.text() == 'ollama pull qwen2.5-coder:7b' for x in line_edits))
        dialog.close()


if __name__ == '__main__':
    unittest.main()

# Integration checks for the guided one-click model onboarding (no real downloads).
@unittest.skipUnless(QT_AVAILABLE, 'PySide6 is unavailable on this platform')
class OllamaAutoSetupQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-unit-test'])

    def test_model_selector_exposes_low_ram_option(self):
        dialog = OllamaHelpDialog('qwen2.5-coder:7b', None)
        self.assertEqual(dialog.chosen_model(), 'qwen2.5-coder:7b')
        dialog.model_choice.setCurrentIndex(dialog.model_choice.findData('qwen2.5-coder:3b'))
        self.assertEqual(dialog.chosen_model(), 'qwen2.5-coder:3b')
        self.assertIn('qwen2.5-coder:3b', dialog.command_box.text())
        dialog.close()

    def test_cancelled_consent_never_starts_download(self):
        from PySide6.QtWidgets import QMessageBox
        dialog = OllamaHelpDialog('qwen2.5-coder:7b', None)
        with patch('sytox.ui.QMessageBox.question', return_value=QMessageBox.No), \
             patch('sytox.ui.OllamaSetupWorker') as worker:
            dialog.begin_install()
            worker.assert_not_called()
        dialog.close()

    def test_accepted_consent_runs_real_qthread_without_network(self):
        from PySide6.QtWidgets import QMessageBox
        dialog = OllamaHelpDialog('qwen2.5-coder:7b', None)
        dialog.model_choice.setCurrentIndex(dialog.model_choice.findData('qwen2.5-coder:3b'))
        with patch('sytox.ui.QMessageBox.question', return_value=QMessageBox.Yes), \
             patch('sytox.ui.setup_local_ollama', return_value='qwen2.5-coder:3b') as setup:
            dialog.begin_install()
            self.assertTrue(dialog.worker.wait(4000), 'setup worker should finish')
            for _ in range(10):
                self.app.processEvents()
            setup.assert_called_once()
            self.assertEqual(setup.call_args.args[1], 'qwen2.5-coder:3b')
        self.assertEqual(dialog.installed_model, 'qwen2.5-coder:3b')
        self.assertFalse(dialog.worker.isRunning())
        dialog.close()
        dialog.deleteLater()
        self.app.processEvents()
