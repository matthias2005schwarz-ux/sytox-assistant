"""Unit tests for clear, non-destructive offline-model onboarding."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

import requests

from sytox.ollama_setup import OllamaStatus, check_ollama_status, model_pull_command
from sytox.agent import OllamaClient, OllamaError
from unittest.mock import patch


class OllamaOnboardingTests(unittest.TestCase):
    def test_ready_when_selected_model_is_installed(self):
        response = Mock()
        response.json.return_value = {'models': [{'name': 'qwen2.5-coder:7b'}]}
        result = check_ollama_status('http://localhost:11434/', 'qwen2.5-coder:7b',
                                     get=lambda url, timeout: response)
        self.assertTrue(result.ready)
        self.assertEqual(result.state, 'ready')
        self.assertEqual(result.available_models, ('qwen2.5-coder:7b',))

    def test_running_server_without_model_is_not_ready(self):
        response = Mock()
        response.json.return_value = {'models': [{'name': 'gemma3:4b'}]}
        result = check_ollama_status('http://localhost:11434', 'qwen2.5-coder:7b',
                                     get=lambda url, timeout: response)
        self.assertEqual(result.state, 'missing_model')
        self.assertFalse(result.ready)
        self.assertIn('nicht installiert', result.details)

    def test_unavailable_server_distinguished_from_missing_model(self):
        def broken(url, timeout):
            raise requests.exceptions.ConnectionError('Connection refused')
        result = check_ollama_status('http://localhost:11434', 'model:latest', get=broken)
        self.assertEqual(result.state, 'offline')
        self.assertIn('starten', result.details)

    def test_timeout_does_not_hang_forever(self):
        def timed_out(url, timeout):
            self.assertLessEqual(timeout, 5)
            raise requests.exceptions.Timeout()
        self.assertEqual(check_ollama_status('http://localhost:11434', 'some:latest', get=timed_out).state,
                         'offline')

    def test_empty_model_list_is_clear(self):
        response = Mock()
        response.json.return_value = {'models': []}
        result = check_ollama_status('http://localhost:11434', 'qwen2.5-coder:7b',
                                     get=lambda url, timeout: response)
        self.assertEqual(result.state, 'missing_model')

    def test_invalid_url_or_model_rejected_without_network(self):
        def never_call(*args, **kwargs):
            self.fail('invalid settings must not trigger a network request')
        for address, model in [('', 'name'), ('not a URL', 'name'),
                               ('http://example.com/prefix', 'name'),
                               ('http://user:password@127.0.0.1:11434', 'name'),
                               ('http://localhost:11434', 'name; echo hacked')]:
            with self.subTest(address=address, model=model):
                self.assertEqual(check_ollama_status(address, model, get=never_call).state,
                                 'invalid_config')

    def test_malformed_response_has_specific_error(self):
        response = Mock()
        response.json.return_value = {'unexpected': []}
        self.assertEqual(check_ollama_status('http://localhost:11434', 'name',
                         get=lambda url, timeout: response).state, 'error')

    def test_explicit_latest_tag_is_recognized(self):
        response = Mock()
        response.json.return_value = {'models': [{'name': 'mymodel:latest'}]}
        self.assertTrue(check_ollama_status('http://localhost:11434', 'mymodel',
                        get=lambda url, timeout: response).ready)

    def test_missing_model_at_chat_time_is_actionable(self):
        response = Mock()
        response.ok = False
        response.status_code = 404
        response.text = '{"error":"model missing"}'
        transport = Mock()
        transport.__enter__ = Mock(return_value=response)
        transport.__exit__ = Mock(return_value=None)
        with patch('sytox.agent.requests.post', return_value=transport):
            with self.assertRaises(OllamaError) as error:
                OllamaClient('http://localhost:11434', 'qwen2.5-coder:7b').chat(
                    [{'role': 'user', 'content': 'Hallo'}])
        self.assertIn('Einrichten', str(error.exception))

    def test_setup_command_is_not_executed_and_rejects_metacharacters(self):
        self.assertEqual(model_pull_command('qwen2.5-coder:7b'), 'ollama pull qwen2.5-coder:7b')
        for bad in ('', 'm; rm -rf /', 'm&&evil', 'm\nother', '-bad'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    model_pull_command(bad)


if __name__ == '__main__':
    unittest.main()
