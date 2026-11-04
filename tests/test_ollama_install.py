"""Safe, cancellable, user-initiated Ollama setup contracts."""
from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from sytox.ollama_installer import (
    SetupFailure, SetupCancelled, valid_local_endpoint, validate_model,
    MODEL_CHOICES, find_ollama_exe, setup_local_ollama, pull_model,
    install_with_winget, start_ollama,
)


class OllamaInstallTests(unittest.TestCase):
    def setUp(self):
        self.cancel = threading.Event()
        self.messages = []
        self.report = lambda message, pct: self.messages.append((message, pct))

    def test_only_explicit_local_api_may_receive_model_download(self):
        for url in ('https://localhost:11434', 'http://example.com:11434',
                    'http://localhost:1234', 'http://localhost:11434/evil',
                    'http://bob@localhost:11434', 'http://localhost:11434?x=1',
                    'http://localhost:11434#fragment', 'file:///C:/temp'):
            with self.subTest(url=url), self.assertRaises(SetupFailure):
                valid_local_endpoint(url)
        self.assertEqual(valid_local_endpoint('http://localhost:11434/'),
                         'http://localhost:11434')
        self.assertEqual(valid_local_endpoint('http://127.0.0.1:11434'),
                         'http://127.0.0.1:11434')

    def test_model_names_cannot_inject_commands(self):
        for value in ('evil; calc.exe', '-evil', 'x\nthing', '', 'x&&whoami'):
            with self.assertRaises(SetupFailure):
                validate_model(value)

    def test_small_model_available_for_low_ram(self):
        self.assertIn('qwen2.5-coder:3b', [value for _, value in MODEL_CHOICES])

    def test_ready_does_not_reinstall_or_redownload(self):
        status = Mock(state='ready', ready=True)
        install = Mock(side_effect=AssertionError('No install'))
        pull = Mock(side_effect=AssertionError('No pull'))
        self.assertEqual(setup_local_ollama('http://localhost:11434', 'qwen2.5-coder:3b',
                         self.cancel, self.report, status_checker=lambda *_: status,
                         installer=install, puller=pull), 'qwen2.5-coder:3b')
        install.assert_not_called()
        pull.assert_not_called()

    def test_missing_model_downloads_and_verifies(self):
        status = [SimpleNamespace(state='missing_model', ready=False, details='missing'),
                  SimpleNamespace(state='ready', ready=True, details='done')]
        puller = Mock()
        value = setup_local_ollama('http://localhost:11434', 'qwen2.5-coder:7b',
                    self.cancel, self.report, status_checker=lambda *_: status.pop(0),
                    installer=Mock(side_effect=AssertionError('Should not install')),
                    puller=puller)
        self.assertEqual(value, 'qwen2.5-coder:7b')
        puller.assert_called_once()

    def test_offline_existing_binary_starts_without_reinstallation(self):
        status = [SimpleNamespace(state='offline', ready=False, details='offline'),
                  SimpleNamespace(state='missing_model', ready=False, details='missing'),
                  SimpleNamespace(state='ready', ready=True, details='ready')]
        installer = Mock(side_effect=AssertionError('Should not reinstall'))
        starter = Mock()
        result = setup_local_ollama('http://localhost:11434', 'testmodel',
                         self.cancel, self.report, status_checker=lambda *_: status.pop(0),
                         installer=installer, starter=starter, puller=Mock(),
                         locate=lambda: r'C:\Users\test\ollama.exe')
        self.assertEqual(result, 'testmodel')
        starter.assert_called_once()
        self.assertEqual(starter.call_args.kwargs['exe'], r'C:\Users\test\ollama.exe')

    def test_cancellation_never_starts_install(self):
        self.cancel.set()
        with self.assertRaises(SetupCancelled):
            setup_local_ollama('http://localhost:11434', 'testmodel',
                 self.cancel, self.report, status_checker=Mock(side_effect=AssertionError()))

    def test_model_pull_requires_explicit_success_event(self):
        class Stream:
            def __init__(self, data): self.data = data
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_lines(self): return iter(json.dumps(d).encode() for d in self.data)
        def api(url, **kwargs):
            self.assertEqual(url, 'http://localhost:11434/api/pull')
            self.assertEqual(kwargs['json'], {'model': 'qwen2.5-coder:3b', 'stream': True})
            self.assertTrue(kwargs['stream'])
            return Stream([{'status': 'downloading', 'total': 100, 'completed': 50},
                           {'status': 'success'}])
        pull_model('http://localhost:11434', 'qwen2.5-coder:3b', self.cancel,
                   self.report, post=api)
        self.assertTrue(any(p == 50 for _, p in self.messages))
        self.assertEqual(self.messages[-1][1], 100)
        with self.assertRaises(SetupFailure):
            pull_model('http://localhost:11434', 'test', self.cancel, self.report,
                       post=lambda *_a, **_k: Stream([{'status':'download'}]))

    def test_model_pull_aborts_while_streaming(self):
        class Stream:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
            def iter_lines(self):
                yield b'{"status":"download"}'
                self_event.set()
                yield b'{"status":"success"}'
        self_event = self.cancel
        with self.assertRaises(SetupCancelled):
            pull_model('http://localhost:11434', 'test', self.cancel, self.report,
                       post=lambda *_a, **_kw: Stream())

    def test_winget_command_fixed_args_no_shell(self):
        fake = Mock();fake.poll.return_value=0;fake.returncode=0
        def create(args, **kwargs):
            self.assertEqual(args[:4], ['C:/winget.exe', 'install', '--id', 'Ollama.Ollama'])
            self.assertIn('--accept-package-agreements', args)
            self.assertNotIn('shell', kwargs)
            return fake
        with patch('sytox.ollama_installer.sys.platform', 'win32'):
            install_with_winget(self.cancel,self.report,which=lambda *_:'C:/winget.exe',popen=create)
        fake.kill.assert_not_called()

    def test_no_winget_returns_official_fallback(self):
        with patch('sytox.ollama_installer.sys.platform', 'win32'):
            with self.assertRaisesRegex(SetupFailure, 'ollama.com/download'):
                install_with_winget(self.cancel,self.report,which=lambda *_:None)

    def test_start_ollama_doesnt_spawn_if_server_running(self):
        response = Mock(ok=True)
        popen = Mock(side_effect=AssertionError('Should not start'))
        start_ollama('http://localhost:11434', self.cancel, self.report,
                     get=lambda *_a, **_k: response, popen=popen)
        popen.assert_not_called()

    def test_not_ready_after_pull_is_error(self):
        status = [SimpleNamespace(state='missing_model', ready=False, details='Missing'),
                  SimpleNamespace(state='missing_model', ready=False, details='Still missing')]
        with self.assertRaisesRegex(SetupFailure, 'Still missing'):
            setup_local_ollama('http://localhost:11434','model',self.cancel,self.report,
                status_checker=lambda *_:status.pop(0),puller=Mock())


if __name__ == '__main__':
    unittest.main()
