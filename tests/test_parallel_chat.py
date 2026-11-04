"""Separation tests: short questions never get PC tools or stop the long Agent."""
import unittest
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication
    from sytox.parallel_chat import ParallelReplyWorker, ParallelChatDialog
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, 'PySide6 unavailable')
class ParallelReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-parallel-chat-test'])

    def test_tool_free_answer_uses_independent_history(self):
        context = [{'role': 'user', 'content': 'Wie funktioniert das?'}]
        worker = ParallelReplyWorker(
            {'model': 'offline-model', 'ollama_url': 'http://localhost:11434'},
            context
        )
        answers = []
        worker.completed.connect(answers.append)
        with patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {
                'role': 'assistant', 'content': 'Ich erkläre es dir.'
            }
            worker.run()
            args, kwargs = client.return_value.chat.call_args
            self.assertEqual(kwargs['tools'], None)
            self.assertIs(kwargs['stop'], worker.stop_event)
            self.assertEqual(args[0][-1], context[0])
            self.assertEqual(args[0][0]['role'], 'system')
            self.assertIn('KEINE Werkzeuge', args[0][0]['content'])
        self.assertEqual(answers, ['Ich erkläre es dir.'])

    def test_public_question_searches_web_without_agent_tools(self):
        question = {'role': 'user', 'content': 'Wer ist Jenna Ortega?'}
        worker = ParallelReplyWorker(
            {'model': 'offline-model', 'ollama_url': 'http://localhost:11434'},
            [question]
        )
        answers = []
        worker.completed.connect(answers.append)
        result = [{'title': 'Profil', 'url': 'https://example.org/jenna',
                   'snippet': 'Schauspielerin'}]
        with patch('sytox.parallel_chat.search_web', return_value=result) as web, \
                patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {
                'role': 'assistant', 'content': 'Jenna Ortega ist eine Schauspielerin.'
            }
            worker.run()
            self.assertIsNone(client.return_value.chat.call_args.kwargs['tools'])
            sent = client.return_value.chat.call_args.args[0]
            self.assertIn('https://example.org/jenna', sent[-1]['content'])
            web.assert_called_once()
        self.assertIn('https://example.org/jenna', answers[0])

    def test_task_status_does_not_call_web_search(self):
        worker = ParallelReplyWorker(
            {'model': 'offline-model', 'ollama_url': 'http://localhost:11434'},
            [{'role': 'user', 'content': 'Wie weit bist du?'}]
        )
        with patch('sytox.parallel_chat.search_web') as web, \
                patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {
                'role': 'assistant', 'content': 'Der Auftrag läuft.'
            }
            worker.run()
            web.assert_not_called()

    def test_side_chat_routes_colloquial_pause_as_control_not_ollama_call(self):
        dialog = ParallelChatDialog(
            {'model': 'offline-model', 'ollama_url': 'http://localhost:11434'}
        )
        requests = []
        dialog.control_requested.connect(
            lambda kind, original, spoken: requests.append((kind, original, spoken))
        )
        try:
            with patch('sytox.parallel_chat.ParallelReplyWorker') as model:
                self.assertTrue(dialog.ask('Hör kurz auf zu programmieren', spoken=True))
                model.assert_not_called()
            self.assertEqual(
                requests, [('pause', 'Hör kurz auf zu programmieren', True)]
            )
            self.assertEqual(dialog.history, [])
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_dialog_keeps_own_unsaved_chat_context(self):
        dialog = ParallelChatDialog(
            {'model': 'offline-model', 'ollama_url': 'http://localhost:11434'}
        )
        try:
            with patch('sytox.parallel_chat.ParallelReplyWorker') as worker:
                self.assertTrue(dialog.ask('Erzähl mir etwas', spoken=True))
                self.assertEqual(dialog.history, [
                    {'role': 'user', 'content': 'Erzähl mir etwas'}
                ])
                worker.return_value.start.assert_called_once()
                worker.assert_called_once()
            self.assertIn('DU: Erzähl mir etwas', dialog.transcript.toPlainText())
        finally:
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
