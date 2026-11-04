import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.storage import Store
from sytox.actions import Toolkit
from sytox.agent import Agent, OllamaError


def call_tool(name, **kwargs):
    return {'role': 'assistant', 'content': '',
            'tool_calls': [{'function': {'name': name, 'arguments': kwargs}}]}


class TestStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.store = Store(self.path / 'assistant.db')
        self.cid = self.store.create_chat('Testchat')

    def tearDown(self):
        self.temp.cleanup()

    def agent(self, user_prompt, responses):
        self.store.add_message(self.cid, 'user', user_prompt)
        instance = Agent(self.store, 'mock', 'http://unused', str(self.path / 'work'),
                         lambda *args: True, lambda *args: None, threading.Event())
        instance.client.chat = MagicMock(side_effect=list(responses))
        return instance

    def test_public_question_automatically_includes_sourced_search(self):
        from unittest.mock import patch
        sources = [{'title': 'Profil', 'url': 'https://example.org/jenna',
                    'snippet': 'Schauspielerin'}]
        with patch('sytox.agent.search_web', return_value=sources) as search:
            agent = self.agent('Wer ist Jenna Ortega?', [
                {'role': 'assistant', 'content': 'Jenna Ortega ist Schauspielerin.'}
            ])
            result = agent.run(self.cid, 'once')
        self.assertEqual(result['status'], 'done')
        self.assertIn('https://example.org/jenna', result['content'])
        search.assert_called_once()
        call_messages = agent.client.chat.call_args.args[0]
        self.assertTrue(any('https://example.org/jenna' in message.get('content', '')\n                            for message in call_messages if message.get('role') == 'user'))

    def test_coding_task_does_not_auto_search_or_expose_project(self):
        from unittest.mock import patch
        with patch('sytox.agent.search_web') as search:
            agent = self.agent('Programmiere ein privates Python-Projekt', [
                {'role': 'assistant', 'content': 'Ich beginne.'}
            ])
            self.assertEqual(agent.run(self.cid, 'once')['status'], 'done')
            search.assert_not_called()

    def test_chat_crud(self):
        self.assertEqual(self.store.chats()[0]['id'], self.cid)
        self.store.add_message(self.cid, 'user', 'Das ist ein Minecraft Projekt')
        self.store.add_message(self.cid, 'assistant', 'Einverstanden')
        self.assertEqual(len(self.store.messages(self.cid)), 2)
        other = self.store.create_chat()
        related = self.store.related_context('Minecraft', exclude_chat=other)
        self.assertTrue(any('Minecraft' in entry['content'] for entry in related))
        self.store.rename_chat(self.cid, 'Neuer Titel')
        self.assertEqual(next(c for c in self.store.chats() if c['id'] == self.cid)['title'],
                         'Neuer Titel')
        self.store.delete_chat(self.cid)
        self.assertFalse(self.store.messages(self.cid))

    def test_memories_and_tasks(self):
        self.store.add_memory('Der Benutzer mag dunkles Rot')
        self.assertEqual(len(self.store.list_memories()), 1)
        tid = self.store.create_task(self.cid, 'Test', 'until_done')
        self.store.update_task(tid, 'paused', {'steps': 3})
        self.assertEqual(json.loads(self.store.tasks(self.cid)[0]['checkpoint'])['steps'], 3)
        self.store.delete_memory(self.store.list_memories()[0]['id'])
        self.assertEqual(self.store.list_memories(), [])

    def test_tools_and_file_backups(self):
        tools = Toolkit(self.store, self.path / 'workspace', lambda *x: False,
                        threading.Event(), self.cid)
        self.assertIn('Gespeichert', tools.call('write_file',
                      {'path': 'plugins/hello.php', 'content': 'abc'}))
        self.assertEqual(tools.call('read_file', {'path': 'plugins/hello.php'}), 'abc')
        self.assertIn('gesichert', tools.call('write_file',
                      {'path': 'plugins/hello.php', 'content': 'def'}))
        self.assertIn('FEHLER', tools.call('write_file',
                      {'path': '../escape.txt', 'content': 'oops'}))
        self.assertIn('FEHLER', tools.call('run_command', {'command': 'not-allowed'}))
        tools.close()

    def test_agent_does_not_accept_plain_finished_text(self):
        instance = self.agent('Schreib test.txt', [
            call_tool('write_file', path='test.txt', content='hello'),
            {'role': 'assistant', 'content': 'Fertig: test.txt angelegt.'},
            call_tool('complete_task', summary='test.txt geschrieben', evidence='write_file'),
        ])
        result = instance.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'done')
        self.assertEqual((self.path / 'work' / 'test.txt').read_text(), 'hello')
        self.assertEqual(instance.client.chat.call_count, 3)

    def test_coding_requires_successful_postwrite_check(self):
        instance = self.agent('Programmiere ein Plugin', [
            call_tool('write_file', path='main.py', content='print("hello")\n'),
            call_tool('complete_task', summary='Fertig', evidence='Keine Tests'),
            call_tool('run_command', command='python -m compileall main.py'),
            call_tool('complete_task', summary='Code geschrieben, Syntax geprüft',
                      evidence='compileall Exit 0'),
        ])
        result = instance.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'done')
        checkpoint = json.loads(self.store.tasks(self.cid)[0]['checkpoint'])
        self.assertGreater(checkpoint['validated_writes'], 0)
        self.assertEqual(instance.client.chat.call_count, 4)

    def test_coding_validation_before_last_edit_is_not_sufficient(self):
        instance = self.agent('Programmiere ein Plugin', [
            call_tool('write_file', path='main.py', content='print(1)\n'),
            call_tool('run_command', command='python -m compileall main.py'),
            call_tool('write_file', path='main.py', content='print((\n'),
            call_tool('complete_task', summary='Fertig', evidence='test vor Änderung'),
            call_tool('report_blocker', reason='Syntaxprüfung nach letzter Änderung fehlt'),
        ])
        result = instance.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'paused')

    def test_read_only_file_discovery_not_completion(self):
        instance = self.agent('Erledige die Aufgabe', [
            call_tool('list_files', path='.'),
            call_tool('complete_task', summary='Fertig', evidence='Verzeichnis gelistet'),
            call_tool('report_blocker', reason='Weitere Informationen nötig'),
        ])
        result = instance.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'paused')

    def test_temporary_model_failure_retries_and_finishes(self):
        agent = self.agent('Programmiere eine Datei', [
            OllamaError('Ollama temporär weg'),
            call_tool('write_file', path='a.py', content='print(1)\n'),
            call_tool('run_command', command='python -m compileall a.py'),
            call_tool('complete_task', summary='a.py geprüft', evidence='compileall'),
        ])
        agent.RETRY_DELAYS = (0, 0, 0)
        result = agent.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(agent.client.chat.call_count, 4)
        self.assertEqual((self.path/'work'/'a.py').read_text(), 'print(1)\n')

    def test_model_outage_pauses_and_saves_checkpoint(self):
        agent = self.agent('Programmiere einen Test', [
            OllamaError('Verbindung 1'), OllamaError('Verbindung 2'), OllamaError('Verbindung 3'),
        ])
        agent.RETRY_DELAYS = (0, 0, 0)
        result = agent.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'paused')
        checkpoint = json.loads(self.store.tasks(self.cid)[0]['checkpoint'])
        self.assertGreaterEqual(checkpoint['steps'], 3)
        self.assertIn('Fortschritt gespeichert', result['content'])

    def test_duplicate_call_loop_is_paused_after_two_executions(self):
        agent = self.agent('Schreibe hello', [
            call_tool('write_file', path='hello.txt', content='hi'),
            call_tool('write_file', path='hello.txt', content='hi'),
            call_tool('write_file', path='hello.txt', content='hi'),
        ])
        result = agent.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'paused')
        self.assertIn('Werkzeugschleife', result['content'])
        self.assertEqual(json.loads(self.store.tasks(self.cid)[0]['checkpoint'])['writes'], 2)

    def test_unrelated_compileall_does_not_validate_code(self):
        agent = self.agent('Programmiere zwei Dateien', [
            call_tool('write_file', path='one.py', content='print(1)\n'),
            call_tool('write_file', path='two.py', content='print(2)\n'),
            call_tool('run_command', command='python -m compileall one.py'),
            call_tool('complete_task', summary='alles fertig', evidence='nur one.py geprüft'),
            call_tool('report_blocker', reason='two.py noch nicht geprüft'),
        ])
        self.assertEqual(agent.run(self.cid, 'until_done')['status'], 'paused')
        self.assertEqual(json.loads(self.store.tasks(self.cid)[0]['checkpoint'])['passed_checks'], 0)

    def test_nonexistent_compileall_target_is_not_evidence(self):
        tools = Toolkit(self.store, self.path/'work', lambda *a: True, threading.Event(), self.cid)
        tools.call('write_file', {'path': 'hello.py', 'content': 'print(1)\n'})
        result = tools.call('run_command', {'command': 'python -m compileall missing.py'})
        self.assertIn('Exit code: 0', result)  # CPython itself returns zero.
        self.assertEqual(tools.passed_checks, 0)
        tools.close()

    def test_resume_after_interruption_preserves_pending_code_check(self):
        agent = self.agent('Programmiere einen Python-Test', [
            call_tool('write_file', path='app.py', content='print(1)\n'),
            call_tool('report_blocker', reason='später testen'),
        ])
        result = agent.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'paused')
        task_id = result['task_id']
        self.assertIn('app.py', json.loads(self.store.tasks(self.cid)[0]['checkpoint'])['unvalidated_paths'])
        agent.client.chat = MagicMock(side_effect=[
            call_tool('run_command', command='python -m compileall app.py'),
            call_tool('complete_task', summary='Prüfung fertig', evidence='compileall app.py exit 0'),
        ])
        self.assertEqual(agent.run(self.cid, task_id=task_id)['status'], 'done')

    def test_sensitive_text_not_saved_in_tool_request(self):
        tools = Toolkit(self.store, self.path/'work', lambda *a: False, threading.Event(), self.cid)
        secret = 'Very confidential private email text'
        tools.call('gmail_send', {'to':'alice@example.test','subject':'Hello','body':secret})
        requests = [x['details'] for x in self.store.logs(self.cid) if x['event']=='tool_request']
        self.assertFalse(any(secret in entry for entry in requests))
        tools.close()

    def test_denied_permission_pauses_unattended_job(self):
        self.store.add_message(self.cid, 'user', 'Bitte sende eine E-Mail')
        agent = Agent(self.store, 'mock', 'http://unused', str(self.path / 'work'),
                      lambda *_: False, lambda *_: None, threading.Event())
        agent.client.chat = MagicMock(side_effect=[
            call_tool('gmail_send', to='bob@example.com', subject='Hallo', body='Hi'),
        ])
        result = agent.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'paused')
        self.assertIn('Freigabe', result['content'])
        agent.client.chat.assert_called_once()

    def test_gmail_send_always_requires_approval(self):
        tools = Toolkit(self.store, self.path / 'work', lambda *a: False,
                        threading.Event(), self.cid)
        tools.gmail.send = MagicMock(return_value={'status': 'sent'})
        self.assertIn('FEHLER', tools.call('gmail_send',
                      {'to': 'someone@example.com', 'subject': 'Hallo', 'body': 'Text'}))
        tools.gmail.send.assert_not_called()
        tools.close()


if __name__ == '__main__':
    unittest.main()
