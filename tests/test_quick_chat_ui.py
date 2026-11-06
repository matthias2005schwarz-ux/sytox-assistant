"""Exercise the real Qt send path with a controlled, slow model stream."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
from sytox.actions import Cancelled
from sytox.ui import MainWindow


class QuickChatUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-quick-chat-tests'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'APPDATA': self.temp.name})
        self.environment.start()
        self.probe = patch.object(MainWindow, 'check_model_status')
        self.updates = patch.object(MainWindow, 'check_for_updates')
        self.probe.start()
        self.updates.start()
        self.window = MainWindow()
        self.window.show()
        self.release = threading.Event()

    def tearDown(self):
        self.release.set()
        if self.window.quick_worker is not None:
            self.window.quick_worker.stop_event.set()
            self.wait_for(lambda: self.window.quick_worker is None)
        self.window._is_exiting = True
        if self.window.tray:
            self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.probe.stop()
        self.updates.stop()
        self.environment.stop()
        self.temp.cleanup()

    def wait_for(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(.005)
        self.fail('Qt operation did not finish in time')

    def slow_reply(self, messages, **kwargs):
        kwargs['on_token']('Hallo')
        while not self.release.wait(.01):
            if kwargs['stop'].is_set():
                raise Cancelled('Antwort abgebrochen')
        kwargs['on_token'](' zurück!')
        kwargs['on_metrics']({'queue_wait_s': .01, 'load_s': .02,
                              'time_to_first_token_s': .03, 'request_s': .2,
                              'tokens_per_second': 20.0})
        return {'role': 'assistant', 'content': 'Hallo zurück!'}

    def send_greeting(self):
        self.window.input.setPlainText('Hallo')
        self.window.send()
        self.wait_for(lambda: self.window._quick_turn is not None and
                      self.window._quick_turn['label'].text() == 'Hallo')

    def test_greeting_streams_before_completion_without_agent_or_task(self):
        with patch('sytox.parallel_chat.OllamaClient') as client, \
             patch('sytox.ui.Agent') as agent, \
             patch.object(self.window.store, 'create_task') as task, \
             patch.object(self.window.store, 'related_context') as recall:
            client.return_value.chat.side_effect = self.slow_reply
            self.send_greeting()
            self.assertIsNone(self.window.worker)
            self.assertEqual([m['role'] for m in self.window.store.messages(self.window.chat_id)], ['user'])
            self.assertFalse(self.window.send_btn.isEnabled())
            self.assertTrue(self.window.stopbtn.isEnabled())
            self.assertNotIn('once', self.window.task_state.text())
            self.assertEqual(client.call_args.args[1], 'qwen3:4b')
            args = client.return_value.chat.call_args.kwargs
            self.assertIsNone(args['tools'])
            self.assertFalse(args['think'])
            self.assertTrue(args['interactive'])
            self.release.set()
            self.wait_for(lambda: self.window.quick_worker is None)
            self.assertEqual(self.window.store.messages(self.window.chat_id)[-1]['content'], 'Hallo zurück!')
            self.assertEqual(len(self.window.store.messages(self.window.chat_id)), 2)
            self.assertTrue(self.window.send_btn.isEnabled())
            self.assertIn('Erstes Token: 0.03 s', self.window.model_name.toolTip())
            agent.assert_not_called()
            task.assert_not_called()
            recall.assert_not_called()

    def test_stop_marks_partial_answer_incomplete_and_does_not_speak(self):
        with patch('sytox.parallel_chat.OllamaClient') as client, \
             patch.object(self.window, 'start_speech') as speech:
            client.return_value.chat.side_effect = self.slow_reply
            self.send_greeting()
            self.window.config['voice_enabled'] = True
            self.window.stop_work()
            self.wait_for(lambda: self.window.quick_worker is None)
            answer = self.window.store.messages(self.window.chat_id)[-1]['content']
            self.assertIn('Hallo', answer)
            self.assertIn('abgebrochen', answer)
            self.assertIn('abgebrochen', self.window.state.text())
            speech.assert_not_called()
            self.assertFalse(self.window.stopbtn.isEnabled())

    def test_enter_during_stream_keeps_unsent_text_and_original_chat(self):
        with patch('sytox.parallel_chat.OllamaClient') as client, \
             patch('sytox.ui.QMessageBox.information'):
            client.return_value.chat.side_effect = self.slow_reply
            other = self.window.store.create_chat('Anderer Chat')
            original = self.window.chat_id
            self.send_greeting()
            self.window.input.setPlainText('Noch eine Frage')
            self.window.send()
            self.window.select_chat(other)
            self.assertEqual(self.window.chat_id, original)
            self.assertEqual(self.window.input.toPlainText(), 'Noch eine Frage')
            self.assertEqual(len(self.window.store.messages(original)), 1)
            client.return_value.chat.assert_called_once()
            self.release.set()
            self.wait_for(lambda: self.window.quick_worker is None)
            self.assertEqual(self.window.store.messages(other), [])

    def test_coding_request_keeps_agent_even_with_manual_fast_model(self):
        with patch.object(self.window, 'start_worker') as agent, \
             patch.object(self.window, 'start_quick_reply') as quick:
            self.window.input.setPlainText('Programmiere ein Python-Plugin')
            self.window.send()
            agent.assert_called_once_with('once', 1.0)
            quick.assert_not_called()

    def test_clicking_current_chat_does_not_delete_live_streaming_bubble(self):
        with patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.side_effect = self.slow_reply
            self.send_greeting()
            label = self.window._quick_turn['label']
            self.window.select_chat(self.window.chat_id)
            self.app.processEvents()
            self.assertEqual(label.text(), 'Hallo')
            self.release.set()
            self.wait_for(lambda: self.window.quick_worker is None)
            self.assertEqual(label.text(), 'Hallo zurück!')

    def test_project_greeting_keeps_permanent_project_model(self):
        project = self.window.store.create_chat('Qwen-Projekt', kind='project')
        self.window.select_chat(project)
        with patch.object(self.window, 'start_worker') as agent, \
             patch.object(self.window, 'start_quick_reply') as quick:
            self.window.input.setPlainText('Hallo')
            self.window.send()
            agent.assert_called_once()
            quick.assert_not_called()
            self.assertEqual(self.window.model_name.text(), 'qwen3-coder:30b')

    def test_ordinary_time_question_does_not_create_timed_task(self):
        with patch.object(self.window, 'start_worker') as agent, \
             patch.object(self.window, 'start_quick_reply') as quick:
            self.window.input.setPlainText('Wie viele Minuten haben 2 Stunden?')
            self.window.send()
            agent.assert_not_called()
            quick.assert_called_once()

    def test_relevant_memory_is_context_without_starting_a_project(self):
        self.window.store.add_memory('Meine Lieblingsfarbe ist Dunkelrot.')
        with patch('sytox.ui.ParallelReplyWorker') as worker:
            self.window.input.setPlainText('Welche Lieblingsfarbe habe ich?')
            self.window.send()
            self.assertIn('Dunkelrot', worker.call_args.kwargs['memory_context'])
            self.assertTrue(worker.call_args.kwargs['standalone'])
        # No real QThread was started by this test's fake worker.
        self.window.quick_worker = None
        self.window._quick_turn = None

    def test_old_explicit_ram_delay_is_preserved(self):
        self.window.config['ram_keep_alive_seconds'] = 60
        self.window.config_path.write_text('{"ram_keep_alive_seconds": 60}', encoding='utf-8')
        self.assertEqual(self.window.load_settings()['ram_keep_alive_seconds'], 60)

    def test_closed_window_does_not_receive_delayed_animation_or_scroll_callbacks(self):
        other = MainWindow()
        other.add_bubble('assistant', 'Kurzlebiges Fenster')
        other._is_exiting = True
        if other.tray:
            other.tray.hide()
        other.close()
        other.deleteLater()
        errors = []
        with patch('sys.excepthook', side_effect=lambda *args: errors.append(args)):
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            started = time.monotonic()
            self.wait_for(lambda: time.monotonic() - started >= .15)
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
