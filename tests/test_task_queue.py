"""Durable coding amendments are applied before the original task is delivered."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.storage import Store
from sytox.agent import Agent
from sytox.task_queue import is_change_request


def tool(name, **arguments):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': arguments}}]}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.store = Store(self.home / 'assistant.db')
        self.cid = self.store.create_chat()

    def test_only_explicit_program_changes_queued(self):
        positives = (
            'Füge noch ein Einstellungsmenü hinzu',
            'Baue noch einen Button in das Spiel ein',
            'Bitte ändere die Animation',
            'Sytox, ergänze ein neues Modul',
            'Verbessere das bestehende Programm',
        )
        for utterance in positives:
            with self.subTest(utterance=utterance):
                self.assertTrue(is_change_request(utterance))
        negatives = (
            'Was hältst du von Animationen?',
            'Wie kann ich ein Menü programmieren?',
            'Wenn ich sage ändere die App, was passiert?',
            'Erzähl mir etwas über meine Anwendung',
            'Bitte nicht das Programm ändern',
            'Wie lange brauchst du noch?',
        )
        for utterance in negatives:
            with self.subTest(utterance=utterance):
                self.assertFalse(is_change_request(utterance))

    def test_queued_items_persist_and_block_final_completion(self):
        tid = self.store.create_task(self.cid, 'Programmiere ein Spiel', 'until_done')
        first = self.store.add_task_change(self.cid, 'Baue ein Menü ein')
        second = self.store.add_task_change(self.cid, 'Füge Soundeffekte hinzu')
        self.assertLess(first, second)
        self.assertFalse(self.store.complete_task_if_queue_empty(tid, {}))
        claimed = self.store.claim_next_change(tid)
        self.assertEqual(claimed['id'], first)
        self.assertEqual(self.store.claim_next_change(tid)['id'], first)
        self.store.finish_change(tid, first)
        self.assertEqual(self.store.claim_next_change(tid)['id'], second)
        self.store.finish_change(tid, second)
        self.assertTrue(self.store.complete_task_if_queue_empty(tid, {'steps': 3}))
        self.assertEqual(self.store.tasks(self.cid)[0]['status'], 'done')
        self.assertEqual([t['status'] for t in self.store.task_changes(tid, include_applied=True)],
                         ['applied', 'applied'])

    def test_worker_startup_cannot_lose_early_instructions(self):
        first = self.store.add_task_change(self.cid, 'Bitte ändere das Programm')
        tid = self.store.create_task(self.cid, 'Programmiere die App', 'until_done')
        self.assertEqual(self.store.task_changes(tid)[0]['id'], first)

    def test_actual_agent_applies_amendment_and_validates_before_done(self):
        self.store.add_message(self.cid, 'user', 'Programmiere ein Python-Programm')
        work = self.home / 'project'
        changes = []
        agent = Agent(self.store, 'mock', 'http://offline', str(work),
                      lambda *args: True, lambda *args: None, threading.Event())
        agent.review_client.chat = MagicMock(return_value={'role': 'assistant', 'content': json.dumps({
            'status': 'passed', 'summary': 'Kontrollierter Prüfbefund', 'findings': []})})
        responses = [
            tool('write_file', path='app.py', content='print("Original")\n'),
            tool('run_command', command='python -m compileall app.py'),
            tool('complete_task', summary='Original gebaut', evidence='Python Test'),
            tool('write_file', path='app.py', content='print("Original")\nprint("Menü")\n'),
            tool('run_command', command='python -m compileall app.py'),
            tool('complete_task', summary='Original und Menü fertig', evidence='2 Tests'),
        ]
        def respond(*args, **kwargs):
            index = len(changes)
            changes.append(index)
            if index == 1:
                change_id = self.store.add_task_change(
                    self.cid, 'Füge dem Programm ein Menü hinzu')
                self.assertGreater(change_id, 0)
            return responses[index]
        agent.client.chat = MagicMock(side_effect=respond)
        result = agent.run(self.cid, 'until_done')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(agent.client.chat.call_count, 6)
        self.assertIn('Original und Menü fertig', result['content'])
        self.assertNotIn('Original gebaut', result['content'])
        self.assertIn('Menü', (work / 'app.py').read_text(encoding='utf-8'))
        records = self.store.task_changes(result['task_id'], include_applied=True)
        self.assertEqual([record['status'] for record in records], ['applied'])
        history = self.store.messages(self.cid)
        self.assertEqual(len([m for m in history if m['role'] == 'assistant']), 1)
        archive = list((self.home / 'project_backups' / self.cid).glob('*.zip'))
        self.assertGreaterEqual(len(archive), 2)


if __name__ == '__main__':
    unittest.main()
