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

    def test_screen_vision_is_internal_to_fast_chat(self):
        question = {'role': 'user', 'content': 'Schau auf meinen Bildschirm. Was siehst du?'}
        worker = ParallelReplyWorker(
            {'model': 'fallback', 'fast_model': 'qwen3:4b',
             'vision_model': 'qwen3-vl:4b',
             'ollama_url': 'http://localhost:11434'}, [question]
        )
        answers = []
        worker.completed.connect(answers.append)
        with patch('sytox.parallel_chat.describe_screen', return_value='Editor offen') as vision, \
             patch('sytox.parallel_chat.OllamaClient') as client, \
             patch('sytox.parallel_chat.search_web') as web:
            client.return_value.chat.return_value = {
                'role': 'assistant', 'content': 'Du hast einen Editor offen.'
            }
            worker.run()
            vision.assert_called_once()
            self.assertEqual(client.call_args.args[1], 'qwen3:4b')
            sent = client.return_value.chat.call_args.args[0]
            self.assertIn('Editor offen', sent[-1]['content'])
            web.assert_not_called()
        self.assertEqual(answers, ['Du hast einen Editor offen.'])


    def test_small_model_diagnoses_windows_code_without_switching_or_installing(self):
        question = {'role': 'user', 'content': 'Was bedeutet Fehler 0xc000007b bei Windows?'}
        worker = ParallelReplyWorker(
            {'model': 'fallback', 'fast_model': 'qwen3:4b',
             'project_model': 'qwen3-coder:30b',
             'ollama_url': 'http://localhost:11434'}, [question]
        )
        received = []
        worker.completed.connect(received.append)
        with patch('sytox.parallel_chat.platform.system', return_value='Windows'), \
             patch('sytox.parallel_chat.diagnose_windows',
                   return_value={'codes':['0xc000007b'], 'interpretation':['Prüfen']}) as diagnose, \
             patch('sytox.parallel_chat.repair_windows') as repair, \
             patch('sytox.parallel_chat.search_web') as web, \
             patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {
                'role':'assistant', 'content':'Das kann eine beschädigte Laufzeit sein.'
            }
            worker.run()
            self.assertEqual(client.call_args.args[1], 'qwen3:4b')
            diagnose.assert_called_once()
            repair.assert_not_called()
            web.assert_not_called()
            messages = client.return_value.chat.call_args.args[0]
            self.assertIn('0xc000007b', messages[-1]['content'])
        self.assertEqual(len(received), 1)

    def test_small_model_can_request_a_safe_repair_after_user_asks(self):
        question = {'role':'user', 'content':
                    'Bitte behebe den Fehler VCRUNTIME140.dll fehlt beim x64-Programm.'}
        worker = ParallelReplyWorker(
            {'model':'fallback', 'fast_model':'qwen3:4b',
             'ollama_url':'http://localhost:11434'}, [question]
        )
        received = []
        worker.completed.connect(received.append)
        with patch('sytox.parallel_chat.platform.system', return_value='Windows'), \
             patch('sytox.parallel_chat.diagnose_windows',
                   return_value={'codes':[], 'interpretation':['Laufzeit fehlt']}), \
             patch('sytox.parallel_chat.repair_windows',
                   return_value={'fix_id':'vc_redist_x64', 'status':'package_verified'}) as repair, \
             patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {
                'role':'assistant',
                'content':'Das Laufzeitpaket ist installiert. Bitte Programm prüfen.'
            }
            worker.run()
            repair.assert_called_once()
            self.assertEqual(repair.call_args.args[0], 'vc_redist_x64')
            self.assertIs(repair.call_args.args[1].__self__, worker)
            self.assertEqual(client.call_args.args[1], 'qwen3:4b')
            messages = client.return_value.chat.call_args.args[0]
            self.assertIn('package_verified', messages[-1]['content'])
        self.assertEqual(len(received), 1)

    def test_ambiguous_error_never_downloads_on_small_model(self):
        worker = ParallelReplyWorker(
            {'model':'fallback', 'fast_model':'qwen3:4b',
             'ollama_url':'http://localhost:11434'},
            [{'role':'user', 'content':'Bitte repariere den Fehler 0xc000007b'}]
        )
        with patch('sytox.parallel_chat.platform.system', return_value='Windows'), \
             patch('sytox.parallel_chat.diagnose_windows',
                   return_value={'codes':['0xc000007b']}), \
             patch('sytox.parallel_chat.repair_windows') as repair, \
             patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {'content':'Erst prüfen.'}
            worker.run()
            repair.assert_not_called()
            sent = client.return_value.chat.call_args.args[0]
            self.assertIn('not_selected', sent[-1]['content'])

    def test_small_model_can_interpret_screen_error_in_same_chat(self):
        worker = ParallelReplyWorker(
            {'model':'fallback', 'fast_model':'qwen3:4b',
             'ollama_url':'http://localhost:11434'},
            [{'role':'user', 'content':
                'Schau auf meinen Bildschirm und behebe den Fehler'}]
        )
        with patch('sytox.parallel_chat.describe_screen',
                   return_value='Fehler: VCRUNTIME140.dll fehlt, x86-Anwendung') as vision, \
             patch('sytox.parallel_chat.platform.system', return_value='Windows'), \
             patch('sytox.parallel_chat.diagnose_windows',
                   return_value={'interpretation':['Laufzeitdatei fehlt']}), \
             patch('sytox.parallel_chat.repair_windows',
                   return_value={'status':'denied'}) as repair, \
             patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {'content':'Die Freigabe wurde abgelehnt.'}
            worker.run()
            vision.assert_called_once()
            repair.assert_called_once()
            self.assertEqual(repair.call_args.args[0], 'vc_redist_x86')
            self.assertEqual(client.call_args.args[1], 'qwen3:4b')

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

    def test_side_chat_eta_request_does_not_send_new_llm_job(self):
        dialog = ParallelChatDialog(
            {'model': 'offline-model', 'ollama_url': 'http://localhost:11434'}
        )
        requests = []
        dialog.status_requested.connect(lambda question, spoken:
                                        requests.append((question, spoken)))
        try:
            with patch('sytox.parallel_chat.ParallelReplyWorker') as worker:
                self.assertTrue(dialog.ask('Wie lange brauchst du noch?', spoken=True))
                worker.assert_not_called()
            self.assertEqual(requests, [('Wie lange brauchst du noch?', True)])
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
