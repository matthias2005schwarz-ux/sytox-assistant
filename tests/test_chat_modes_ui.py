"""Windows Qt checks for visible dual-model conversations and voice routing."""
import os
import tempfile
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication
    from sytox.ui import MainWindow, QuickReplyWorker, SettingsDialog
    from sytox.chat_modes import QUICK, PROJECT
    AVAILABLE = True
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(AVAILABLE, 'PySide6 is required')
class ChatModesQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-dual-model-tests'])

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'APPDATA': self.home.name})
        self.environment.start()
        self.no_model_probe = patch.object(MainWindow, 'check_model_status')
        self.no_model_probe.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window._is_exiting = True
        if self.window.tray:
            self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        self.no_model_probe.stop()
        self.environment.stop()
        self.home.cleanup()

    def test_sidebar_has_both_modes_and_preserves_per_chat_models(self):
        window = self.window
        self.assertIn('Schnellchat', window.btn_quick.text())
        self.assertIn('Qwen-Projekt', window.btn_project.text())
        self.assertEqual(window.current_chat_mode(), QUICK)
        fast_id = window.chat_id
        self.assertEqual(window.current_chat_model(), 'qwen3:4b')
        self.assertEqual(window.model_name.text(), 'qwen3:4b')
        self.assertFalse(window.mode.isEnabled())
        window.create_chat(PROJECT)
        project_id = window.chat_id
        self.assertNotEqual(fast_id, project_id)
        self.assertEqual(window.current_chat_mode(), PROJECT)
        self.assertEqual(window.model_name.text(), 'qwen3-coder:30b')
        self.assertTrue(window.mode.isEnabled())
        window.select_chat(fast_id)
        self.assertEqual(window.current_chat_mode(), QUICK)
        self.assertEqual(window.current_chat_model(), 'qwen3:4b')
        texts = [window.chatlist.item(i).text() for i in range(window.chatlist.count())]
        self.assertTrue(any(name.startswith('⚡') for name in texts))
        self.assertTrue(any(name.startswith('◆') for name in texts))

    def test_send_routes_casual_fast_and_explicit_small_project_to_agent(self):
        window = self.window
        with patch.object(window, 'start_quick_reply') as quick, \
             patch.object(window, 'start_worker') as project, \
             patch.object(window, 'stop_speech'), \
             patch.object(window, 'offer_place_if_relevant'):
            window.input.setPlainText('Hallo, wie geht es dir?')
            window.send()
            quick.assert_called_once()
            project.assert_not_called()
            quick.reset_mock()
            window.input.setPlainText('Programmiere mir ein Python-Skript zum Sortieren')
            window.send()
            project.assert_called_once_with('once', 1.0)
            quick.assert_not_called()
            window.create_chat(PROJECT)
            project.reset_mock()
            window.input.setPlainText('Hallo aus dem großen Qwen-Projekt')
            window.send()
            project.assert_called_once()

    def test_settings_show_fast_big_and_screen_models_independently(self):
        dialog = SettingsDialog(self.window.config, self.window)
        self.assertEqual(dialog.fast_model.text(), 'qwen3:4b')
        self.assertEqual(dialog.model.text(), 'qwen3-coder:30b')
        self.assertEqual(dialog.vision_model.text(), 'qwen3-vl:4b')
        values = dialog.values()
        self.assertEqual(values['fast_model'], 'qwen3:4b')
        self.assertEqual(values['model'], 'qwen3-coder:30b')
        dialog.close()

    def test_quick_reply_worker_saves_text_without_touching_project_agent(self):
        window = self.window
        chat = window.chat_id
        window.store.add_message(chat, 'user', 'Hallo')
        settings = window.config.copy()
        worker = QuickReplyWorker(window.store, chat, settings)
        chunks, completed = [], []
        worker.partial.connect(chunks.append)
        worker.completed.connect(completed.append)
        def fake_chat(messages, *, stop, on_text, think):
            self.assertIs(think, False)
            self.assertEqual(messages[-1]['content'], 'Hallo')
            on_text('Hallo ')
            on_text('zusammen')
            return {'content': 'Hallo zusammen', 'role': 'assistant'}
        with patch('sytox.ui.OllamaClient.chat', side_effect=fake_chat):
            worker.run()
        self.assertEqual(chunks, ['Hallo ', 'zusammen'])
        self.assertEqual(completed[0]['status'], 'done')
        self.assertEqual(window.store.messages(chat)[-1]['content'], 'Hallo zusammen')


if __name__ == '__main__':
    unittest.main()
