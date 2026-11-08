"""Exercise project discovery and repair against real local source and tests.

Only model decisions are scripted; reads, writes, approvals and unittest runs
use the application's actual tool path.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from sytox.actions import Toolkit
from sytox.agent import Agent
from sytox.storage import Store


BROKEN = 'def add(left, right):\n    return left - right\n'
FIXED = 'def add(left, right):\n    return left + right\n'
TEST_SOURCE = (
    'import unittest\nfrom app import add\n\n'
    'class AdditionTest(unittest.TestCase):\n'
    '    def test_addition(self):\n'
    '        self.assertEqual(add(2, 3), 5)\n'
)


def tool(name, **arguments):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': arguments}}]}


def complete():
    return tool('complete_task', summary='Addition korrigiert', evidence='Projektprüfung')


class ProjectWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'APPDATA': str(self.root / 'profile')})
        environment.start()
        self.addCleanup(environment.stop)
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        (self.workspace / 'app.py').write_text(BROKEN, encoding='utf-8')
        (self.workspace / 'test_app.py').write_text(TEST_SOURCE, encoding='utf-8')
        self.store = Store(self.root / 'assistant.db')
        self.chat = self.store.create_chat('Programmierauftrag')
        self.model_inputs = []
        self.approvals = []

    def approve(self, label, description):
        self.approvals.append((label, description))
        return True

    def agent(self, replies, *, approval=None, before_reply=None):
        self.store.add_message(self.chat, 'user', 'Behebe die Python-Funktion add in app.py')
        agent = Agent(self.store, 'mock', 'http://unused', self.workspace,
                      approval or self.approve, lambda *_: None, threading.Event())
        agent.review_client.chat = MagicMock(return_value={'role': 'assistant', 'content': json.dumps({
            'status': 'passed', 'summary': 'Kontrollierter Prüfbefund', 'findings': []})})
        self.set_replies(agent, replies, before_reply=before_reply)
        return agent

    def set_replies(self, agent, replies, *, before_reply=None):
        sequence = iter(replies)
        index = 0

        def respond(messages, **_kwargs):
            nonlocal index
            self.model_inputs.append(copy.deepcopy(messages))
            if before_reply:
                before_reply(index)
            index += 1
            return next(sequence)

        agent.client.chat = MagicMock(side_effect=respond)

    def tools(self):
        tools = Toolkit(self.store, self.workspace, self.approve, chat_id=self.chat)
        self.addCleanup(tools.close)
        tools.project_checks = json.loads(tools.call('project_check_plan', {}))['checks']
        return tools

    def checkpoint(self):
        return json.loads(self.store.tasks(self.chat)[0]['checkpoint'])

    def tool_outputs(self, name):
        # Inspect a snapshot taken before the last model reply, not a mutable
        # message list that the agent may subsequently append to.
        return [message['content'] for message in self.model_inputs[-1]
                if message.get('role') == 'tool' and message.get('tool_name') == name]

    def test_relevant_source_and_test_are_read_before_first_model_decision(self):
        agent = self.agent([tool('report_blocker', reason='Nur Projektkontext kontrollieren')])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        context = '\n'.join(message.get('content', '') for message in self.model_inputs[0]
                            if message.get('_sytox_context_data'))
        self.assertIn('[SYTOX-PROJEKTKONTEXT]', context)
        self.assertIn('app.py', context)
        self.assertIn('test_app.py', context)
        self.assertIn('return left - right', context)
        self.assertIn('self.assertEqual(add(2, 3), 5)', context)
        self.assertIn('app.py', self.checkpoint()['project_context_files'])
        self.assertEqual(self.checkpoint()['writes'], 0)

    def test_automatic_test_failure_is_returned_then_repaired_and_repeated(self):
        agent = self.agent([
            tool('write_file', path='app.py', content=BROKEN), complete(),
            tool('write_file', path='app.py', content=FIXED), complete(), complete(),
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'done')
        outputs = self.tool_outputs('complete_task')
        self.assertEqual(len(outputs), 2)
        self.assertIn('AssertionError', outputs[0])
        self.assertIn('-1 != 5', outputs[0])
        self.assertIn('Ran 1 test', outputs[1])
        self.assertIn('OK', outputs[1])
        self.assertIn('Tatsächlich bestandene Projektprüfungen', result['content'])
        self.assertEqual((self.workspace / 'app.py').read_text(), FIXED)
        self.assertEqual(self.checkpoint()['validation_failures'], [])
        self.assertEqual(self.checkpoint()['unvalidated_paths'], [])
        self.assertEqual(len(self.approvals), 1)  # The actual task-scoped test permission is reused.

    def test_green_syntax_does_not_replace_the_existing_failing_tests(self):
        agent = self.agent([
            tool('write_file', path='app.py', content=BROKEN),
            tool('run_command', command='python -m compileall app.py'), complete(),
            tool('report_blocker', reason='Additionstest noch fehlgeschlagen'),
        ])
        self.assertEqual(agent.run(self.chat, 'once')['status'], 'paused')
        self.assertIn('tests', self.checkpoint()['validation_failures'])
        self.assertIn('AssertionError', self.tool_outputs('complete_task')[0])
        self.assertGreater(self.checkpoint()['passed_checks'], 0)

    def test_deleting_existing_test_file_does_not_make_zero_tests_a_success(self):
        def remove_test(index):
            if index == 1:
                (self.workspace / 'test_app.py').unlink()

        agent = self.agent([
            tool('write_file', path='app.py', content=FIXED), complete(),
            tool('report_blocker', reason='Vorhandene Tests fehlen'),
        ], before_reply=remove_test)
        self.assertEqual(agent.run(self.chat, 'once')['status'], 'paused')
        self.assertIn('Ran 0 tests', self.tool_outputs('complete_task')[0])
        self.assertTrue(any(check['kind'] == 'tests' for check in self.checkpoint()['project_checks']))
        self.assertIn('tests', self.checkpoint()['validation_failures'])

    def test_saved_edit_invalidates_a_previously_passing_project_check(self):
        tools = self.tools()
        tools.call('write_file', {'path': 'app.py', 'content': FIXED})
        passing = json.loads(tools.call('project_validate', {}))
        self.assertTrue(passing['passed'])
        self.assertEqual(tools.missing_project_checks(), [])
        tools.call('write_file', {'path': 'app.py', 'content': BROKEN})
        self.assertTrue(tools.missing_project_checks())
        failing = json.loads(tools.call('project_validate', {}))
        self.assertFalse(failing['passed'])
        self.assertIn('AssertionError', failing['results'][0]['output'])

    def test_resume_requires_fresh_tests_and_detects_external_source_changes(self):
        agent = self.agent([
            tool('write_file', path='app.py', content=FIXED), tool('project_validate'),
            tool('report_blocker', reason='Später fortsetzen'),
        ])
        first = agent.run(self.chat, 'once')
        self.assertEqual(first['status'], 'paused')
        (self.workspace / 'app.py').write_text('def add(left, right):\n    return 100\n', encoding='utf-8')
        self.set_replies(agent, [complete(), tool('report_blocker', reason='Neue Änderung erkannt')])
        resumed = agent.run(self.chat, task_id=first['task_id'])
        self.assertEqual(resumed['status'], 'paused')
        self.assertIn('100 != 5', self.tool_outputs('complete_task')[0])
        self.assertIn('tests', self.checkpoint()['validation_failures'])

    def test_denied_test_permission_pauses_without_executing_project_code(self):
        agent = self.agent([
            tool('write_file', path='app.py', content=FIXED), complete(),
        ], approval=lambda *_: False)
        with patch('sytox.actions.subprocess.Popen') as execute:
            result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        self.assertIn('Freigabe', result['content'])
        execute.assert_not_called()

    def test_failed_auto_checks_are_not_repeated_for_an_unchanged_revision(self):
        agent = self.agent([
            tool('write_file', path='app.py', content=BROKEN), complete(), complete(),
            tool('report_blocker', reason='Quellcode muss korrigiert werden'),
        ])
        self.assertEqual(agent.run(self.chat, 'once')['status'], 'paused')
        outputs = self.tool_outputs('complete_task')
        self.assertEqual(len(outputs), 2)
        self.assertIn('AssertionError', outputs[0])
        self.assertNotIn('Ran 1 test', outputs[1])
        runs = [entry for entry in self.store.logs(self.chat)
                if entry['event'] == 'tool_request' and entry['details'].startswith('run_command:')]
        self.assertEqual(len(runs), 1)

    def test_repeated_unverified_completion_pauses_without_repeating_tests(self):
        agent = self.agent([tool('write_file', path='app.py', content=BROKEN),
                            complete(), complete(), complete()])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        self.assertIn('dreimal', result['content'])
        self.assertEqual(agent.client.chat.call_count, 4)
        runs = [entry for entry in self.store.logs(self.chat)
                if entry['event'] == 'tool_request' and entry['details'].startswith('run_command:')]
        self.assertEqual(len(runs), 1)

    def test_numbered_read_range_keeps_default_read_compatibility(self):
        tools = self.tools()
        self.assertEqual(tools.call('read_file', {'path': 'app.py'}), BROKEN)
        self.assertEqual(tools.call('read_file', {'path': 'app.py', 'start_line': 2, 'end_line': 2}),
                         '2:     return left - right')
        for arguments in ({'start_line': 0}, {'start_line': True},
                          {'start_line': 2, 'end_line': 1}, {'start_line': 1, 'end_line': 401}):
            with self.subTest(arguments=arguments):
                self.assertTrue(tools.call('read_file', {'path': 'app.py', **arguments}).startswith('FEHLER'))


if __name__ == '__main__':
    unittest.main()
