"""Real local write/test/repair flows; only the model replies are simulated."""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.actions import Toolkit
from sytox.agent import Agent
from sytox.storage import Store


def tool(name, **arguments):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': arguments}}]}


class AgentQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'APPDATA': str(self.root / 'profile')})
        environment.start()
        self.addCleanup(environment.stop)
        self.store = Store(self.root / 'assistant.db')
        self.chat = self.store.create_chat('Code')
        self.workspace = self.root / 'work'

    def agent(self, replies):
        self.store.add_message(self.chat, 'user', 'Programmiere eine Python-Funktion')
        agent = Agent(self.store, 'mock', 'http://unused', self.workspace,
                      lambda *_: True, lambda *_: None, threading.Event())
        agent.review_client.chat = MagicMock(return_value={'role': 'assistant', 'content': json.dumps({
            'status': 'passed', 'summary': 'Kontrollierter Prüfbefund', 'findings': []})})
        agent.client.chat = MagicMock(side_effect=replies)
        return agent

    def test_once_coding_continues_after_plain_finished_text_until_verified_completion(self):
        agent = self.agent([
            tool('write_file', path='app.py', content='VALUE = 1\n'),
            {'role': 'assistant', 'content': 'Fertig!'},
            tool('run_command', command='python -m compileall app.py'),
            tool('complete_task', summary='Datei geprüft', evidence='compileall app.py: Exit 0'),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(agent.client.chat.call_count, 4)
        schema = agent.client.chat.call_args.kwargs['tools']
        self.assertTrue({'complete_task', 'record_progress', 'report_blocker'} <=
                        {entry['function']['name'] for entry in schema})
        self.assertEqual((self.workspace / 'app.py').read_text(), 'VALUE = 1\n')

    def test_once_coding_without_actions_never_claims_done(self):
        agent = self.agent([{'role': 'assistant', 'content': 'Fertig!'}] * 3)
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(agent.client.chat.call_count, 3)
        self.assertEqual(self.store.tasks(self.chat)[0]['status'], 'paused')

    def test_ui_implementation_uses_same_validation_contract_as_programming(self):
        self.store.add_message(self.chat, 'user', 'Füge einen Button hinzu')
        agent = Agent(self.store, 'mock', 'http://unused', self.workspace,
                      lambda *_: True, lambda *_: None)
        agent.review_client.chat = MagicMock(return_value={'role': 'assistant', 'content': json.dumps({
            'status': 'passed', 'summary': 'Kontrollierter Prüfbefund', 'findings': []})})
        agent.client.chat = MagicMock(side_effect=[{'role': 'assistant', 'content': 'Fertig!'}] * 3)
        self.assertEqual(agent.run(self.chat, 'once')['status'], 'paused')
        self.assertEqual(agent.client.chat.call_count, 3)

    def test_failed_test_is_repaired_and_repeated_before_once_completion(self):
        test_source = ('import unittest\nfrom app import VALUE\n'
                       'class ValueTest(unittest.TestCase):\n'
                       '    def test_value(self): self.assertEqual(VALUE, 2)\n')
        agent = self.agent([
            tool('write_file', path='app.py', content='VALUE = 1\n'),
            tool('write_file', path='test_app.py', content=test_source),
            tool('run_command', command='python -m unittest test_app'),
            tool('complete_task', summary='Nicht fertig', evidence='Tests fehlgeschlagen'),
            tool('write_file', path='app.py', content='VALUE = 2\n'),
            tool('run_command', command='python -m unittest test_app'),
            tool('complete_task', summary='Repariert und geprüft', evidence='1 Test bestanden'),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(agent.client.chat.call_count, 7)
        checkpoint = json.loads(self.store.tasks(self.chat)[0]['checkpoint'])
        self.assertEqual(checkpoint['validation_failures'], [])
        self.assertEqual(checkpoint['unvalidated_paths'], [])

    def test_new_failed_tests_invalidate_earlier_green_syntax_check(self):
        agent = self.agent([
            tool('write_file', path='app.py', content='VALUE = 1\n'),
            tool('run_command', command='python -m compileall app.py'),
            tool('run_command', command='python -m unittest nonexistent_suite'),
            tool('run_command', command='python -m compileall app.py'),
            tool('complete_task', summary='Fertig', evidence='Syntax ist grün'),
            tool('report_blocker', reason='Testlauf muss korrigiert werden'),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        checkpoint = json.loads(self.store.tasks(self.chat)[0]['checkpoint'])
        self.assertEqual(checkpoint['validation_failures'], ['tests'])
        self.assertGreater(checkpoint['passed_checks'], 0)
        self.assertEqual(result['content'], 'Testlauf muss korrigiert werden')

    def test_resume_keeps_failed_test_requirement_until_a_passing_test(self):
        agent = self.agent([
            tool('write_file', path='app.py', content='VALUE = 1\n'),
            tool('run_command', command='python -m compileall app.py'),
            tool('run_command', command='python -m unittest nonexistent_suite'),
            tool('report_blocker', reason='Tests später reparieren'),
        ])
        first = agent.run(self.chat, 'once')
        agent.client.chat = MagicMock(side_effect=[
            tool('complete_task', summary='Fertig', evidence='Frühere Syntaxprüfung'),
            tool('report_blocker', reason='Fehlgeschlagene Tests bleiben offen'),
        ])
        resumed = agent.run(self.chat, task_id=first['task_id'])
        self.assertEqual(resumed['status'], 'paused')
        self.assertEqual(resumed['content'], 'Fehlgeschlagene Tests bleiben offen')

    def test_unrelated_passing_test_cannot_hide_the_failing_test(self):
        broken = ('import unittest\nclass Broken(unittest.TestCase):\n'
                  '    def test_broken(self): self.fail("still broken")\n')
        trivial = ('import unittest\nclass Trivial(unittest.TestCase):\n'
                   '    def test_passes(self): self.assertTrue(True)\n')
        agent = self.agent([
            tool('write_file', path='test_broken.py', content=broken),
            tool('write_file', path='test_trivial.py', content=trivial),
            tool('run_command', command='python -m compileall .'),
            tool('run_command', command='python -m unittest test_broken'),
            tool('run_command', command='python -m unittest test_trivial'),
            tool('complete_task', summary='Alles grün', evidence='Nur test_trivial bestanden'),
            tool('report_blocker', reason='test_broken muss repariert werden'),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(result['content'], 'test_broken muss repariert werden')
        checkpoint = json.loads(self.store.tasks(self.chat)[0]['checkpoint'])
        self.assertEqual(len(checkpoint['validation_requirements']), 1)
        self.assertIn('test_broken', next(iter(checkpoint['validation_requirements'])))

    def test_completion_before_another_announced_edit_is_deferred(self):
        calls = (tool('complete_task', summary='Zu früh fertig', evidence='Alte Syntaxprüfung')['tool_calls'] +
                 tool('write_file', path='app.py', content='VALUE = 2\n')['tool_calls'])
        agent = self.agent([
            tool('write_file', path='app.py', content='VALUE = 1\n'),
            tool('run_command', command='python -m compileall app.py'),
            {'role': 'assistant', 'content': '', 'tool_calls': calls},
            tool('complete_task', summary='Immer noch zu früh', evidence='Alte Syntaxprüfung'),
            tool('run_command', command='python -m compileall app.py'),
            tool('complete_task', summary='Letzte Änderung geprüft', evidence='Neue Syntaxprüfung'),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(agent.client.chat.call_count, 6)
        self.assertIn('Letzte Änderung geprüft', result['content'])
        self.assertEqual((self.workspace / 'app.py').read_text(), 'VALUE = 2\n')
        checkpoint = json.loads(self.store.tasks(self.chat)[0]['checkpoint'])
        self.assertEqual(checkpoint['validated_writes'], 2)

    def test_same_size_python_edit_does_not_execute_stale_bytecode(self):
        tools = Toolkit(self.store, self.workspace, lambda *_: True, chat_id=self.chat)
        self.addCleanup(tools.close)
        tools.call('write_file', {'path': 'app.py', 'content': 'VALUE = 1\n'})
        source = self.workspace / 'app.py'
        original_timestamp = source.stat().st_mtime
        imported = tools.call('run_command', {'command': 'python -c "import app; print(app.VALUE)"'})
        self.assertIn('\n1\n', imported)
        self.assertTrue(list((self.workspace / '__pycache__').glob('app.*.pyc')))
        tools.call('write_file', {'path': 'app.py', 'content': 'VALUE = 2\n'})
        os.utime(source, (original_timestamp, original_timestamp))
        repaired = tools.call('run_command', {'command': 'python -c "import app; print(app.VALUE)"'})
        self.assertIn('\n2\n', repaired)

    def test_symlinked_external_python_cache_is_untouched(self):
        tools = Toolkit(self.store, self.workspace, lambda *_: True, chat_id=self.chat)
        self.addCleanup(tools.close)
        tools.call('write_file', {'path': 'app.py', 'content': 'VALUE = 1\n'})
        outside = self.root / 'external-cache'
        outside.mkdir()
        cache = outside / 'app.cpython-test.pyc'
        cache.write_bytes(b'unrelated external data')
        try:
            (self.workspace / '__pycache__').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Creating directory symlinks is unavailable: ' + str(exc))
        result = tools.call('write_file', {'path': 'app.py', 'content': 'VALUE = 2\n'})
        self.assertTrue(result.startswith('FEHLER PermissionError:'))
        self.assertEqual(cache.read_bytes(), b'unrelated external data')
        self.assertEqual((self.workspace / 'app.py').read_text(), 'VALUE = 1\n')

    def test_preexisting_temp_symlink_cannot_overwrite_external_data(self):
        tools = Toolkit(self.store, self.workspace, lambda *_: True, chat_id=self.chat)
        self.addCleanup(tools.close)
        tools.call('write_file', {'path': 'app.py', 'content': 'VALUE = 1\n'})
        outside = self.root / 'external-private.txt'
        outside.write_text('External data stays intact', encoding='utf-8')
        legacy_temp = self.workspace / 'app.py.sytox_tmp'
        try:
            legacy_temp.symlink_to(outside)
        except OSError as exc:
            self.skipTest('Creating file symlinks is unavailable: ' + str(exc))
        result = tools.call('write_file', {'path': 'app.py', 'content': 'VALUE = 2\n'})
        self.assertTrue(result.startswith('Gespeichert:'))
        self.assertEqual(outside.read_text(), 'External data stays intact')
        self.assertTrue(legacy_temp.is_symlink())
        self.assertEqual((self.workspace / 'app.py').read_text(), 'VALUE = 2\n')
        self.assertEqual(list(self.workspace.glob('.sytox-*.tmp')), [])

    def test_more_than_eight_announced_tool_calls_are_all_answered(self):
        calls = [tool('write_file', path=f'app_{index}.py', content=f'VALUE = {index}\n')['tool_calls'][0]
                 for index in range(9)]
        agent = self.agent([
            {'role': 'assistant', 'content': '', 'tool_calls': calls},
            tool('run_command', command='python -m compileall .'),
            tool('complete_task', summary='Neun Dateien geprüft', evidence='compileall Exit 0'),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'done')
        self.assertEqual(len(list(self.workspace.glob('app_*.py'))), 9)
        next_messages = agent.client.chat.call_args_list[1].args[0]
        answered = [entry for entry in next_messages if entry['role'] == 'tool'
                    and entry.get('tool_name') == 'write_file']
        self.assertEqual(len(answered), 9)

    def test_python_cache_cleanup_matches_literal_source_name(self):
        tools = Toolkit(self.store, self.workspace, lambda *_: True, chat_id=self.chat)
        self.addCleanup(tools.close)
        cache_dir = self.workspace / '__pycache__'
        cache_dir.mkdir()
        matching = cache_dir / 'app[1].cpython-test.pyc'
        unrelated = cache_dir / 'app1.cpython-test.pyc'
        matching.write_bytes(b'old cache for bracketed file')
        unrelated.write_bytes(b'cache for another source')
        result = tools.call('write_file', {'path': 'app[1].py', 'content': 'VALUE = 1\n'})
        self.assertTrue(result.startswith('Gespeichert:'))
        self.assertFalse(matching.exists())
        self.assertEqual(unrelated.read_bytes(), b'cache for another source')


class TestEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = Store(root / 'assistant.db')
        self.tools = Toolkit(self.store, root / 'work', lambda *_: True)
        self.addCleanup(self.tools.close)

    def test_unittest_help_empty_and_all_skipped_are_not_executed_passing_tests(self):
        outputs = (
            ('python -m unittest --help', 'usage: unittest [options]\n'),
            ('python -m unittest', 'Ran 0 tests in 0.001s\n\nOK\n'),
            ('python -m unittest', 'Ran 2 tests in 0.001s\n\nOK (skipped=2)\n'),
            ('python -m unittest', 'Ran 1 test in 0.001s\n\nOK (expected failures=1)\n'),
        )
        for command, output in outputs:
            with self.subTest(command=command, output=output):
                self.assertFalse(self.tools._validates_pending_edits(command, 'Exit code: 0\n' + output))
        self.assertTrue(self.tools._validates_pending_edits(
            'python -m unittest', 'Exit code: 0\nRan 2 tests in 0.001s\n\nOK (skipped=1)\n'))

    def test_pytest_collection_or_all_skipped_cannot_validate_edits(self):
        for command, output in (
            ('python -m pytest --collect-only', '1 test collected\n'),
            ('python -m pytest --co', '1 test collected\n'),
            ('python -m pytest', '1 skipped in 0.1s\n'),
            ('python -m pytest --help', 'usage: pytest\n'),
        ):
            with self.subTest(command=command):
                self.assertFalse(self.tools._validates_pending_edits(command, 'Exit code: 0\n' + output))
        self.assertTrue(self.tools._validates_pending_edits(
            'python -m pytest', 'Exit code: 0\n======= 2 passed in 0.1s =======\n'))

    def test_self_development_tests_cannot_hide_a_failed_project_test(self):
        self.tools._record_validation('run_command', {'command': 'python -m unittest broken'}, False)
        self.tools._record_validation('selfdev_validate', {}, False)
        with patch.object(self.tools, 'action_selfdev_validate',
                          return_value='Syntaxprüfung bestanden; Unit-Tests bestanden.'):
            self.tools.call('selfdev_validate', {})
        self.assertEqual(self.tools.validation_failures, {'tests'})

    def test_successful_same_build_retry_clears_failure_without_new_edit_proof(self):
        self.tools.call('write_file', {'path': 'app.csproj', 'content': '<Project />'})
        self.tools.call('write_file', {'path': 'App.cs', 'content': 'class App {}'})
        with patch.object(self.tools, 'action_run_command', side_effect=[
                'Exit code: 0\nBuild succeeded.', 'Exit code: 1\nBuild failed.',
                'Exit code: 0\nBuild succeeded.']):
            self.tools.call('run_command', {'command': 'dotnet build'})
            self.assertEqual(self.tools.passed_checks, 1)
            self.assertEqual(self.tools.unvalidated_paths, set())
            self.tools.call('run_command', {'command': 'dotnet build'})
            self.assertEqual(self.tools.validation_failures, {'build'})
            self.tools.call('run_command', {'command': 'dotnet   build'})
        self.assertEqual(self.tools.passed_checks, 1)
        self.assertEqual(self.tools.validation_requirements, {})
        self.assertEqual(self.tools.validation_failures, set())

    def test_read_file_retains_actual_ending_at_both_existing_output_limits(self):
        start, end = 'BEGIN_OF_FILE\n', '\nACTUAL_END_OF_FILE'
        for length in (21900, 24000):
            with self.subTest(length=length):
                content = start + ('x' * (length - len(start) - len(end))) + end
                (self.tools.workspace / 'long.txt').write_text(content, encoding='utf-8')
                result = self.tools.call('read_file', {'path': 'long.txt'})
                self.assertTrue(result.startswith(start))
                self.assertTrue(result.endswith(end))
                self.assertIn('Werkzeugausgabe gekürzt', result)
                self.assertLessEqual(len(result), 20000)

    def test_long_failed_command_preserves_exit_status_and_terminal_error(self):
        result = self.tools.call('run_command', {'command':
            'python -c "print(\'BEGIN_OUTPUT\'); print(\'x\'*13000); '
            'print(\'TERMINAL_ERROR\'); raise SystemExit(1)"'})
        self.assertTrue(result.startswith('Exit code: 1\nBEGIN_OUTPUT\n'))
        self.assertTrue(result.endswith('TERMINAL_ERROR\n'))
        self.assertIn('Werkzeugausgabe gekürzt', result)
        self.assertLessEqual(len(result), 12020)


if __name__ == '__main__':
    unittest.main()
