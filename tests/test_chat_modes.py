"""Regression checks for old-chat migration and dual-model quick routing."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.agent import OllamaClient, Agent, QUICK_CODING_TOOLS
from sytox.chat_modes import (
    QUICK, PROJECT, FAST_MODEL, PROJECT_MODEL,
    is_small_project_request, model_for_chat, normalize_chat_mode,
)
from sytox.storage import Store


class ChatModeStorageTests(unittest.TestCase):
    def test_additive_migration_of_preexisting_sqlite_chats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'assistant.db'
            with sqlite3.connect(path) as db:
                db.execute("""CREATE TABLE chats(
                    id TEXT PRIMARY KEY, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                db.execute("INSERT INTO chats VALUES('old','Alter Qwen-Chat','a','b')")
            store = Store(path)
            self.assertEqual(store.chat_mode('old'), PROJECT)
            self.assertEqual(store.chats()[0]['title'], 'Alter Qwen-Chat')
            self.assertEqual(store.chats()[0]['mode'], PROJECT)
            fast = store.create_chat('Neuer Schnellchat', mode=QUICK)
            big = store.create_chat('Neues Projekt', mode=PROJECT)
            store.add_message(fast, 'user', 'Hallo')
            store.add_message(big, 'user', 'Programmiere ein Spiel')
            reopened = Store(path)
            self.assertEqual(reopened.chat_mode(fast), QUICK)
            self.assertEqual(reopened.chat_mode(big), PROJECT)
            self.assertEqual(reopened.chat_mode('old'), PROJECT)
            self.assertEqual(reopened.messages(fast)[0]['content'], 'Hallo')
            with self.assertRaises(ValueError):
                reopened.create_chat(mode='remote')
            reopened.delete_chat(fast)
            self.assertEqual(reopened.chat_mode(big), PROJECT)

    def test_model_is_selected_from_saved_chat_kind(self):
        settings = {'model': 'qwen3-coder:30b', 'fast_model': 'qwen3:4b'}
        self.assertEqual(model_for_chat(QUICK, settings), FAST_MODEL)
        self.assertEqual(model_for_chat(PROJECT, settings), PROJECT_MODEL)
        self.assertEqual(normalize_chat_mode(None), PROJECT)
        self.assertEqual(model_for_chat(QUICK, {}), FAST_MODEL)

    def test_only_clear_implementation_requests_trigger_file_agent(self):
        for request in ("Programmiere mir ein Python-Skript zum Sortieren",
                        "Erstelle eine kleine App mit drei Buttons",
                        "Schreib eine Python-Datei namens hello.py",
                        "Baue ein kleines Projekt zum Rechnen"):
            with self.subTest(request=request):
                self.assertTrue(is_small_project_request(request))
        for phrase in ("Hallo, wie geht es dir?",
                       "Was ist Python?",
                       "Erkläre mir eine Funktion",
                       "Wie erstelle ich eine App?",
                       "Kannst du bitte einfach mit mir reden?"):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_small_project_request(phrase))


class FakeStreamingResponse:
    ok = True
    status_code = 200
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def iter_lines(self):
        for frame in (
            {'message': {'content': 'Hallo '}, 'done': False},
            {'message': {'content': 'aus Qwen3'}, 'done': False},
            {'message': {}, 'done': True},
        ):
            yield json.dumps(frame).encode('utf-8')


class QuickModelProtocolTests(unittest.TestCase):
    def test_streamed_fast_model_text_without_tool_permissions_or_thinking(self):
        observed = []
        def post(url, **kwargs):
            self.assertEqual(url, 'http://localhost:11434/api/chat')
            self.assertEqual(kwargs['json']['model'], 'qwen3:4b')
            self.assertIs(kwargs['json']['think'], False)
            self.assertNotIn('tools', kwargs['json'])
            self.assertEqual(kwargs['json']['options']['num_ctx'], 4096)
            return FakeStreamingResponse()
        with patch('sytox.agent.requests.post', side_effect=post):
            result = OllamaClient(model='qwen3:4b', context_tokens=4096).chat(
                [{'role': 'user', 'content': 'Hallo'}], think=False,
                on_text=observed.append)
        self.assertEqual(result['content'], 'Hallo aus Qwen3')
        self.assertEqual(observed, ['Hallo ', 'aus Qwen3'])


class QuickCodingAgentTests(unittest.TestCase):
    def test_small_project_writes_and_tests_with_restricted_tool_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = Store(root / 'chats.db')
            chat = store.create_chat('Mini-Projekt', mode=QUICK)
            store.add_message(chat, 'user', 'Programmiere ein kurzes Python-Skript')
            agent = Agent(store, 'qwen3:4b', 'http://localhost:11434',
                          root / 'project', lambda *_: True, lambda *_: None,
                          threading.Event(), context_tokens=4096, quick_coding=True)
            def tool(name, **kwargs):
                return {'role': 'assistant', 'content': '', 'tool_calls': [
                    {'function': {'name': name, 'arguments': kwargs}}]}
            agent.client.chat = MagicMock(side_effect=[
                tool('write_file', path='hello.py', content='print(42)\n'),
                tool('run_command', command='python -m compileall hello.py'),
                {'role': 'assistant', 'content': 'Kleines Skript geschrieben und getestet.'},
            ])
            result = agent.run(chat, 'once')
            self.assertEqual(result['status'], 'done', result['content'])
            self.assertEqual((root / 'project' / 'hello.py').read_text(encoding='utf-8'),
                             'print(42)\n')
            self.assertEqual(agent.client.chat.call_count, 3)
            for call in agent.client.chat.call_args_list:
                self.assertIs(call.kwargs.get('think'), False)
                offered = {tool['function']['name'] for tool in call.kwargs['tools']}
                self.assertEqual(offered, QUICK_CODING_TOOLS)
                self.assertNotIn('pc_click', offered)
                self.assertNotIn('gmail_send', offered)
                self.assertNotIn('start_coding_team', offered)
                self.assertIn('kleinen lokalen Coding-Modus',
                              call.args[0][0]['content'])


if __name__ == '__main__':
    unittest.main()
