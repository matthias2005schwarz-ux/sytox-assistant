"""RAM saver sends keep_alive per request, without terminating Ollama."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.agent import Agent, OllamaClient
from sytox.ram_saver import (
    DEFAULT_KEEP_ALIVE_SECONDS, keep_alive_for_config,
    normalized_keep_alive_seconds,
)
from sytox.storage import Store


class KeepAlivePolicyTests(unittest.TestCase):
    def test_enabled_by_default_and_configurable(self):
        self.assertEqual(DEFAULT_KEEP_ALIVE_SECONDS, 60)
        self.assertEqual(keep_alive_for_config({}), '60s')
        self.assertEqual(keep_alive_for_config({'ram_keep_alive_seconds': 300}), '300s')
        self.assertEqual(keep_alive_for_config({'ram_keep_alive_seconds': 0}), 0)
        self.assertIsNone(keep_alive_for_config({'ram_saver_enabled': False}))

    def test_invalid_settings_fall_back_to_one_minute(self):
        for candidate in (-1, 999999, 'invalid', None, True):
            with self.subTest(candidate=candidate):
                # True is int(1), so it is valid and finite.
                expected = 1 if candidate is True else 60
                self.assertEqual(normalized_keep_alive_seconds(candidate), expected)

    def test_chat_request_sets_keep_alive_not_global_ollama_process(self):
        response = MagicMock()
        response.ok = True
        response.iter_lines.return_value = [
            json.dumps({'message': {'content': 'Hallo'}, 'done': True}).encode()
        ]
        context = MagicMock()
        context.__enter__.return_value = response
        context.__exit__.return_value = False
        with patch('sytox.agent.requests.post', return_value=context) as send:
            reply = OllamaClient('http://localhost:11434', 'qwen3:4b',
                                 keep_alive='60s').chat([{'role': 'user', 'content': 'Hi'}])
        self.assertEqual(reply['content'], 'Hallo')
        payload = send.call_args.kwargs['json']
        self.assertEqual(payload['keep_alive'], '60s')
        self.assertEqual(payload['model'], 'qwen3:4b')
        self.assertTrue(payload['stream'])
        self.assertTrue(send.call_args.args[0].endswith('/api/chat'))

    def test_disable_uses_ollama_default(self):
        response = MagicMock()
        response.ok = True
        response.iter_lines.return_value = [b'{"done": true}']
        context = MagicMock()
        context.__enter__.return_value = response
        context.__exit__.return_value = False
        with patch('sytox.agent.requests.post', return_value=context) as send:
            OllamaClient(keep_alive=None).chat([{'role': 'user', 'content': 'Hi'}])
        self.assertNotIn('keep_alive', send.call_args.kwargs['json'])

    def test_agent_passes_ram_policy_to_chat_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / 'assistant.db')
            with patch('sytox.agent.OllamaClient') as client:
                Agent(store, 'qwen3-coder:30b', 'http://localhost:11434',
                      str(Path(tmp) / 'work'), lambda *_: False, lambda *_: None,
                      threading.Event(), ram_keep_alive='60s')
            client.assert_called_once_with('http://localhost:11434', 'qwen3-coder:30b',
                                           keep_alive='60s')


if __name__ == '__main__':
    unittest.main()
