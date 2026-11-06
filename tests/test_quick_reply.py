"""Quick and side conversations stream without constructing a task Agent."""
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from sytox.actions import Cancelled
from sytox.parallel_chat import (
    ParallelReplyWorker, ParallelChatDialog, bounded_history, MAX_CONTEXT_CHARS,
)


class QuickReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-quick-reply-test'])

    def worker(self, history=None, **kwargs):
        return ParallelReplyWorker(
            {'fast_model': 'qwen3:4b', 'ollama_url': 'http://localhost:11434'},
            history or [{'role': 'user', 'content': 'Hallo'}], standalone=True,
            **kwargs,
        )

    def test_greeting_streams_before_completion_without_search_or_tools(self):
        worker = self.worker()
        events = []
        worker.token.connect(lambda text: events.append(('token', text)))
        worker.completed.connect(lambda text: events.append(('done', text)))
        worker.metrics.connect(lambda values: events.append(('metrics', values)))
        selected = []
        worker.model_selected.connect(selected.append)

        def chat(messages, **kwargs):
            self.assertIsNone(kwargs['tools'])
            self.assertTrue(kwargs['interactive'])
            self.assertFalse(kwargs['think'])
            self.assertEqual(kwargs['priority'], 'interactive')
            self.assertIs(kwargs['stop'], worker.stop_event)
            self.assertLess(len(messages[0]['content']), 1000)
            self.assertNotIn('anderer Agent', messages[0]['content'])
            kwargs['on_token']('Hal')
            self.assertEqual(events, [('token', 'Hal')])
            kwargs['on_token']('lo!')
            kwargs['on_metrics']({'load_s': 1.25})
            return {'content': 'Hallo!'}

        with patch('sytox.parallel_chat.OllamaClient') as client, \
             patch('sytox.parallel_chat.search_web') as search, \
             patch('sytox.parallel_chat.describe_screen') as screen, \
             patch('sytox.agent.Agent') as agent:
            client.return_value.chat.side_effect = chat
            worker.run()
            search.assert_not_called()
            screen.assert_not_called()
            agent.assert_not_called()
        self.assertEqual(selected, ['qwen3:4b'])
        self.assertEqual(events[-1], ('done', 'Hallo!'))
        self.assertEqual(worker.outcome, 'done')

    def test_precancelled_reply_completes_without_model_or_side_effects(self):
        worker = self.worker()
        worker.stop_event.set()
        answers = []
        worker.completed.connect(answers.append)
        with patch('sytox.parallel_chat.OllamaClient') as client, \
             patch('sytox.parallel_chat.search_web') as search:
            worker.run()
            client.assert_not_called()
            search.assert_not_called()
        self.assertEqual(worker.outcome, 'cancelled')
        self.assertEqual(answers, ['Antwort abgebrochen.'])

    def test_simple_definitions_reach_local_model_without_search(self):
        for question in ('Was ist Python?', 'Was ist ein Algorithmus?',
                         'Was ist Photosynthese?'):
            with self.subTest(question=question):
                worker = self.worker([{'role': 'user', 'content': question}])
                with patch('sytox.parallel_chat.search_web') as search, \
                     patch('sytox.parallel_chat.OllamaClient') as client:
                    client.return_value.chat.return_value = {'content': 'Eine Erklärung.'}
                    worker.run()
                    search.assert_not_called()
                    client.return_value.chat.assert_called_once()
                self.assertEqual(worker.outcome, 'done')

    def test_explicit_research_keeps_web_sources_in_quick_answer(self):
        question = 'Was ist Python? Bitte recherchiere im Internet.'
        worker = self.worker([{'role': 'user', 'content': question}])
        sources = [{'title': 'Python', 'url': 'https://www.python.org/',
                    'snippet': 'Programmiersprache'}]
        answers = []
        worker.completed.connect(answers.append)
        with patch('sytox.parallel_chat.search_web', return_value=sources) as search, \
             patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {'content': 'Eine Programmiersprache.'}
            worker.run()
            search.assert_called_once_with(question, stop_event=worker.stop_event)
        self.assertIn('https://www.python.org/', answers[0])

    def test_partial_failure_is_explicitly_incomplete(self):
        worker = self.worker()
        answers = []
        worker.completed.connect(answers.append)

        def interrupted(messages, **kwargs):
            kwargs['on_token']('Eine halbe Antwort')
            raise RuntimeError('Verbindung unterbrochen')

        with patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.side_effect = interrupted
            worker.run()
        self.assertEqual(worker.outcome, 'failed')
        self.assertIn('Eine halbe Antwort', answers[0])
        self.assertIn('Unvollständige Antwort', answers[0])
        self.assertIn('Verbindung unterbrochen', answers[0])

    def test_cancelled_stream_stops_tokens_and_never_reports_success(self):
        worker = self.worker()
        tokens, answers = [], []
        worker.token.connect(tokens.append)
        worker.completed.connect(answers.append)

        def cancelled(messages, **kwargs):
            kwargs['on_token']('Anfang')
            worker.stop_event.set()
            kwargs['on_token']('darf nicht angezeigt werden')
            raise Cancelled('Abbruch')

        with patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.side_effect = cancelled
            worker.run()
        self.assertEqual(tokens, ['Anfang'])
        self.assertEqual(worker.outcome, 'cancelled')
        self.assertIn('Unvollständige Antwort', answers[0])

    def test_bounded_context_preserves_latest_turn_and_excludes_tools(self):
        history = [{'role': 'assistant', 'content': 'old' * 10000},
                   {'role': 'tool', 'content': 'run unsafe commands'},
                   {'role': 'user', 'content': 'Meine neueste Frage'}]
        result = bounded_history(history, max_chars=100)
        self.assertEqual(result, [history[-1]])
        self.assertEqual(len(history[0]['content']), 30000)

    def test_local_memory_is_bounded_and_labeled_untrusted(self):
        worker = self.worker(memory_context='Rot ist meine Lieblingsfarbe. ' * 500)
        with patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {'content': 'Hallo!'}
            worker.run()
            prompt = client.return_value.chat.call_args.args[0][0]['content']
        self.assertIn('unbestätigter Kontext', prompt)
        self.assertIn('Rot ist meine Lieblingsfarbe.', prompt)
        self.assertLess(len(prompt), 3000)

    def test_oversized_current_input_is_rejected_without_silent_truncation(self):
        question = 'Hallo ' * 2200 + 'Ändere keine Dateien!'
        worker = self.worker([{'role': 'user', 'content': question}])
        answers = []
        worker.completed.connect(answers.append)
        with patch('sytox.parallel_chat.OllamaClient') as client:
            worker.run()
            client.assert_not_called()
        self.assertEqual(worker.history[-1]['content'], question)
        self.assertEqual(worker.outcome, 'failed')
        self.assertIn('12.000 Zeichen', answers[0])

    def test_observations_memory_and_history_share_one_context_budget(self):
        question = 'Schau auf meinen Bildschirm und erkläre mir den Fehler'
        history = [{'role': 'assistant', 'content': 'Alter Verlauf. ' * 500},
                   {'role': 'user', 'content': question}]
        worker = self.worker(history, memory_context='Erinnerung. ' * 500)
        with patch('sytox.parallel_chat.describe_screen', return_value='x' * 6500), \
             patch('sytox.parallel_chat.diagnose_windows', return_value={'detail': 'y' * 6500}), \
             patch('sytox.parallel_chat.platform.system', return_value='Windows'), \
             patch('sytox.parallel_chat.OllamaClient') as client:
            client.return_value.chat.return_value = {'content': 'Ein Fehler.'}
            worker.run()
            sent = client.return_value.chat.call_args.args[0]
        self.assertLessEqual(sum(len(entry['content']) for entry in sent), MAX_CONTEXT_CHARS)
        self.assertIn({'role': 'user', 'content': question}, sent)
        self.assertTrue(any('[Kontextauszug gekürzt]' in entry['content'] for entry in sent))


class ParallelStreamingDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-parallel-stream-test'])

    def setUp(self):
        self.dialog = ParallelChatDialog({'ollama_url': 'http://localhost:11434'})

    def tearDown(self):
        if self.dialog.reply_worker is not None:
            self.dialog._reply_finished(self.dialog.reply_worker)
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def begin(self):
        with patch.object(ParallelReplyWorker, 'start'):
            self.assertTrue(self.dialog.ask('Hallo', spoken=True))
        return self.dialog.reply_worker

    def test_stream_updates_before_done_and_preserves_other_transcript_lines(self):
        worker = self.begin()
        self.dialog._reply_token('Hal')
        self.assertIn('SYTOX: Hal', self.dialog.transcript.toPlainText())
        self.assertFalse(self.dialog.send_btn.isEnabled())
        self.dialog.transcript.appendPlainText('\nSTATUS: Hauptauftrag läuft weiter')
        self.dialog._reply_token('lo')
        worker.outcome = 'done'
        self.dialog._reply_done('Hallo!')
        transcript = self.dialog.transcript.toPlainText()
        self.assertEqual(transcript.count('SYTOX:'), 1)
        self.assertIn('SYTOX: Hallo!', transcript)
        self.assertIn('STATUS: Hauptauftrag läuft weiter', transcript)
        self.assertEqual(self.dialog.history[-1], {'role': 'assistant', 'content': 'Hallo!'})
        # completed is emitted before the native thread finishes: stay busy.
        self.assertFalse(self.dialog.ask('Eine weitere Frage'))
        self.dialog._reply_finished(worker)
        self.assertTrue(self.dialog.send_btn.isEnabled())
        self.assertIsNone(self.dialog.reply_worker)

    def test_cancel_button_is_nonblocking_and_partial_is_not_conversation_history(self):
        worker = self.begin()
        responses = []
        self.dialog.answer_ready.connect(lambda answer, spoken: responses.append((answer, spoken)))
        self.dialog._reply_token('Unvollständig')
        self.dialog.cancel_reply()
        self.assertTrue(worker.stop_event.is_set())
        self.assertFalse(self.dialog.stop_btn.isEnabled())
        worker.outcome = 'cancelled'
        self.dialog._reply_done('Unvollständig\n[Antwort abgebrochen]')
        self.assertEqual(self.dialog.history, [{'role': 'user', 'content': 'Hallo'}])
        self.assertFalse(responses[0][1])


if __name__ == '__main__':
    unittest.main()
