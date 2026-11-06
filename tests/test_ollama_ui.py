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

    def test_model_picker_does_not_create_a_separate_vision_chat(self):
        from sytox.ui import SettingsDialog
        self.assertEqual([self.window.model_mode.itemData(i) for i in range(3)],
                         ['auto', 'fast', 'project'])
        self.assertEqual(self.window.config['fast_model'], 'qwen3:4b')
        self.assertEqual(self.window.config['project_model'], 'qwen3-coder:30b')
        settings = SettingsDialog(self.window.config, self.window)
        self.assertEqual(settings.vision_model.text(), 'qwen3-vl:4b')
        settings.close()
        self.window.model_mode.setCurrentIndex(2)
        self.assertEqual(self.window.config['model_mode'], 'project')

    def test_screen_request_reaches_agent_without_a_visible_vision_tab(self):
        from sytox.ui import Worker
        self.window.store.add_message(
            self.window.chat_id, 'user', 'Schau auf meinen Bildschirm')
        settings = self.window.config.copy()
        settings['model_mode'] = 'fast'
        worker = Worker(self.window.store, self.window.chat_id, settings)
        received = []
        worker.completed.connect(received.append)
        with patch('sytox.ui.describe_screen', return_value='Datei-Explorer geöffnet') as vision, \
             patch('sytox.ui.Agent') as agent:
            agent.return_value.run.return_value = {'status': 'done', 'content': 'Explorer'}
            worker.run()
            self.assertEqual(agent.call_args.kwargs['screen_context'], 'Datei-Explorer geöffnet')
            self.assertEqual(agent.call_args.args[1], 'qwen3:4b')
            vision.assert_called_once()
        self.assertEqual(received[0]['status'], 'done')

    def test_ram_saver_defaults_and_settings_are_persistable(self):
        from sytox.ui import SettingsDialog
        self.assertTrue(self.window.config['ram_saver_enabled'])
        self.assertEqual(self.window.config['ram_keep_alive_seconds'], 60)
        dialog = SettingsDialog(self.window.config, self.window)
        self.assertTrue(dialog.ram_saver.isChecked())
        self.assertEqual(dialog.ram_delay.value(), 60)
        dialog.ram_delay.setValue(300)
        self.assertEqual(dialog.values()['ram_keep_alive_seconds'], 300)
        dialog.ram_saver.setChecked(False)
        self.assertFalse(dialog.ram_delay.isEnabled())
        self.assertFalse(dialog.values()['ram_saver_enabled'])
        dialog.close()

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
