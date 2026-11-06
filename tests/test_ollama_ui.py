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

    def test_screen_sharing_requires_consent_and_can_be_revoked_by_voice(self):
        from PySide6.QtWidgets import QMessageBox
        with patch('sytox.ui.QMessageBox.question', return_value=QMessageBox.No):
            self.window.enable_screen()
        self.assertFalse(self.window.screen_enabled)
        self.assertFalse(self.window.screen_analyze_btn.isEnabled())
        with patch('sytox.ui.QMessageBox.question', return_value=QMessageBox.Yes):
            self.window.enable_screen()
        self.assertTrue(self.window.screen_enabled)
        self.assertTrue(self.window.screen_stop_btn.isEnabled())
        self.assertIn('Bildschirmfreigabe aktiv', self.window.screen_active_chip.text())
        self.window.received_voice_command('Okay, kannst wieder aus meinem Bildschirm rausgehen')
        self.assertFalse(self.window.screen_enabled)
        self.assertFalse(self.window.screen_stop_btn.isEnabled())
        self.assertIn('kein Bildschirmzugriff', self.window.screen_state.text())
        self.assertIn('Bildschirm aus', self.window.screen_active_chip.text())

    def test_switching_chat_automatically_ends_screen_session(self):
        from PySide6.QtWidgets import QMessageBox
        with patch('sytox.ui.QMessageBox.question', return_value=QMessageBox.Yes):
            self.window.enable_screen()
        self.assertTrue(self.window.screen_enabled)
        next_chat = self.window.store.create_chat()
        self.window.select_chat(next_chat)
        self.assertFalse(self.window.screen_enabled)
        self.assertIn('Bildschirm aus', self.window.screen_active_chip.text())

    def test_revoked_share_discards_late_screen_answer(self):
        from PySide6.QtWidgets import QMessageBox, QFrame
        with patch('sytox.ui.QMessageBox.question', return_value=QMessageBox.Yes):
            self.window.enable_screen()
        generation = self.window.screen_generation
        self.window.disable_screen()
        before = len(self.window.findChildren(QFrame, 'bubbleAssistant'))
        self.window._screen_analysis_completed(generation, True, 'PRIVATE SCREEN TEXT')
        after = len(self.window.findChildren(QFrame, 'bubbleAssistant'))
        self.assertEqual(before, after)

    def test_auto_tune_settings_show_live_ram_suggestion_and_manual_override(self):
        from sytox.ui import SettingsDialog
        from unittest.mock import patch
        with patch("sytox.ui.probe_hardware", return_value={
            "ram_total_gb": 16, "ram_available_gb": 8, "vram_total_gb": None
        }):
            dialog = SettingsDialog(self.window.config, self.window)
        try:
            self.assertEqual(dialog.model_context.currentData(), 0)
            self.assertIn("4,096", dialog.hardware_preview.text())
            self.assertIn("WARNUNG", dialog.hardware_preview.text())
            pos = dialog.model_context.findData(32768)
            self.assertGreaterEqual(pos, 0)
            dialog.model_context.setCurrentIndex(pos)
            self.assertIn("Manuell", dialog.hardware_preview.text())
            self.assertEqual(dialog.values()["model_context_tokens"], 32768)
            dialog.model_context.setCurrentIndex(dialog.model_context.findData(0))
            self.assertEqual(dialog.values()["model_context_tokens"], 0)
        finally:
            dialog.close()

    def test_performance_panel_reports_auto_model_recommendation(self):
        # RAM warning specifically concerns the large Qwen-Coder 30B project.
        self.window.create_chat('project')
        self.window.config["model_context_tokens"] = 0
        self.window._performance_measured({
            "ram_total_gb": 16, "ram_used_gb": 8,
            "ram_available_gb": 8, "model_size_gb": None,
            "cpu_percent": 42, "gpu_name": None, "loaded_models": [],
        })
        self.assertIn("Automatisch empfohlen", self.window.performance_info.text())
        self.assertIn("WARNUNG", self.window.performance_info.text())

    def test_offline_does_not_claim_ki_ready(self):
        self.window._model_status_checked(OllamaStatus('offline', 'Ollama nicht erreichbar',
                                                      'Bitte Ollama starten'))
        self.assertIn('Ollama nicht erreichbar', self.window.status_chip.text())
        self.assertIn('Ollama starten', self.window.model_status_label.text())

    def test_new_install_uses_30b_default_and_keeps_custom_settings(self):
        self.assertEqual(self.window.config['model'], 'qwen3-coder:30b')
        self.assertIn('qwen3-coder:30b', [value for _, value in __import__('sytox.ollama_installer', fromlist=['MODEL_CHOICES']).MODEL_CHOICES])

    def test_ready_status_is_clear(self):
        self.window._model_status_checked(OllamaStatus('ready', 'KI bereit',
                                                      'Ollama verbunden · qwen2.5-coder:7b'))
        self.assertIn('KI bereit', self.window.status_chip.text())

    def test_custom_sytox_branding_and_model_status_action(self):
        """Supplied app icon and wide in-app artwork must really render in Qt."""
        from pathlib import Path
        from PySide6.QtWidgets import QLabel
        from PySide6.QtGui import QIcon
        from sytox.ui import bundled_asset, app_icon
        self.assertTrue(bundled_asset('sytox.ico').is_file())
        self.assertTrue(bundled_asset('sytox_wordmark.jpg').is_file())
        self.assertFalse(app_icon().isNull())
        self.assertTrue(app_icon().availableSizes())
        self.assertIn('Modell', self.window.brand_status_btn.text())
        self.assertIn('LOKALER WORKSPACE', [
            l.text() for l in self.window.findChildren(QLabel)])
        self.assertNotIn('DESKTOP AI', [
            l.text() for l in self.window.findChildren(QLabel)])
        self.assertFalse(self.window.topbar_wordmark.pixmap().isNull())
        self.assertFalse(self.window.hero_wordmark.pixmap().isNull())
        self.window._model_status_checked(OllamaStatus(
            'ready', 'KI bereit', 'Ollama verbunden · qwen3:4b'))
        self.assertEqual(self.window.brand_status_btn.text(), '●  KI bereit')
        self.window._model_status_checked(OllamaStatus(
            'offline', 'Ollama nicht erreichbar', 'Bitte Ollama starten'))
        self.assertEqual(self.window.brand_status_btn.text(), '●  Modell prüfen')

    def test_dark_red_workspace_controls_and_suggestion(self):
        from PySide6.QtWidgets import QFrame
        cards = self.window.findChildren(QFrame, 'utilityCard')
        self.assertEqual(len(cards), 7)  # Street View + screen help + existing utility cards
        self.assertIsNotNone(self.window.empty_widget)
        self.window._use_suggestion('Erstelle eine Funktion')
        self.assertEqual(self.window.input.toPlainText(), 'Erstelle eine Funktion')
        self.assertEqual(self.window.chatlist.count(), 1)

    def test_focus_mode_hides_and_restores_tools_without_destroying_controls(self):
        from PySide6.QtWidgets import QFrame
        panel = self.window.utility_panel
        cards_before = self.window.findChildren(QFrame, 'utilityCard')
        self.assertEqual(len(cards_before), 7)
        self.assertFalse(panel.isHidden())

        self.window.toggle_focus_mode()
        self.assertTrue(panel.isHidden())
        self.assertTrue(self.window.focus_btn.isChecked())
        self.assertEqual(self.window.focus_btn.text(), '☰')

        self.window.toggle_focus_mode()
        self.assertFalse(panel.isHidden())
        self.assertFalse(self.window.focus_btn.isChecked())
        self.assertEqual(self.window.focus_btn.text(), '☰')
        self.assertEqual(len(self.window.findChildren(QFrame, 'utilityCard')), 7)

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

    def test_typing_while_agent_runs_routes_to_parallel_chat(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        try:
            self.window.input.setPlainText('Was ist Python?')
            with patch.object(self.window, 'ask_parallel') as side:
                self.window.send()
            side.assert_called_once_with('Was ist Python?', spoken=False)
            self.assertEqual(self.window.input.toPlainText(), '')
            self.assertFalse(running.stop_event.is_set())
        finally:
            self.window.worker = None

    def test_speaking_while_agent_runs_does_not_interrupt_job(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        try:
            with patch.object(self.window, 'ask_parallel') as side:
                self.window.received_voice_command('Erzähl mir etwas über Python')
            side.assert_called_once_with('Erzähl mir etwas über Python', spoken=True)
            self.assertFalse(running.stop_event.is_set())
        finally:
            self.window.worker = None

    def test_spoken_progress_question_reports_without_pausing(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        try:
            with patch.object(self.window, 'report_agent_status') as status, \
                 patch.object(self.window, 'ask_parallel') as side:
                self.window.received_voice_command('Wie weit bist du?')
            status.assert_called_once_with('Wie weit bist du?', spoken=True)
            side.assert_not_called()
            self.assertFalse(running.stop_event.is_set())
        finally:
            self.window.worker = None

    def test_silence_command_never_cancels_programming(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        try:
            with patch.object(self.window, 'stop_speech'), \
                 patch.object(self.window, '_conversation_ready'):
                self.window.received_voice_command('Sei still')
            self.assertFalse(running.stop_event.is_set())
        finally:
            self.window.worker = None

    def test_starting_agent_keeps_voice_listener_available(self):
        from unittest.mock import MagicMock
        listener = MagicMock()
        listener.isRunning.return_value = True
        self.window.listener = listener
        self.window.voice_muted.set()
        try:
            with patch('sytox.ui.Worker') as make_worker:
                self.window.start_worker()
                make_worker.return_value.start.assert_called_once()
            self.assertFalse(self.window.voice_muted.is_set())
            self.assertTrue(self.window.send_btn.isEnabled())
        finally:
            self.window.worker = None
            self.window.listener = None

    def test_colloquial_pause_does_not_erase_worker_or_chat(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        existing_chat = self.window.chat_id
        try:
            with patch.object(self.window, '_conversation_ready'):
                self.window.received_voice_command('Hör kurz auf zu programmieren')
            self.assertTrue(running.stop_event.is_set())
            self.assertIs(self.window.worker, running)
            self.assertEqual(self.window.chat_id, existing_chat)
        finally:
            self.window.worker = None

    def test_spoken_resume_when_worker_stopping_waits_for_checkpoint(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        running.stop_event.set()
        self.window.worker = running
        try:
            with patch.object(self.window, '_conversation_ready'):
                self.window.received_voice_command('Mach wieder weiter')
            self.assertTrue(self.window._resume_after_pause)
            self.assertTrue(running.stop_event.is_set())
            task_id = self.window.store.create_task(self.window.chat_id, 'Code schreiben', 'until_done')
            self.window.store.update_task(task_id, 'paused')
            self.window.worker = None
            with patch.object(self.window, 'resume_task') as resume:
                self.window._agent_thread_finished()
            resume.assert_called_once_with()
            self.assertFalse(self.window._resume_after_pause)
        finally:
            self.window.worker = None

    def test_negated_pause_is_ordinary_side_chat_not_a_control(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        try:
            with patch.object(self.window, 'ask_parallel') as side:
                self.window.received_voice_command('Hör nicht auf zu programmieren')
            side.assert_called_once_with('Hör nicht auf zu programmieren', spoken=True)
            self.assertFalse(running.stop_event.is_set())
        finally:
            self.window.worker = None

    def test_only_explicit_stop_cancels_running_job(self):
        import threading
        from unittest.mock import MagicMock
        running = MagicMock()
        running.isRunning.return_value = True
        running.stop_event = threading.Event()
        self.window.worker = running
        try:
            with patch.object(self.window, 'stop_speech'), \
                 patch.object(self.window, '_conversation_ready'):
                self.window.received_voice_command('Stopp')
            self.assertTrue(running.stop_event.is_set())
        finally:
            self.window.worker = None

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
