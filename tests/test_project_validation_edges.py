"""Integration checks for multi-batch syntax coverage and changed npm manifests."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from sytox.actions import Toolkit
from sytox.project_checks import plan_project_checks
from sytox.storage import Store


class ProjectValidationEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        environment = patch.dict(os.environ, {'APPDATA': str(self.root / 'profile')})
        environment.start()
        self.addCleanup(environment.stop)
        self.workspace = self.root / 'project'
        self.workspace.mkdir()
        self.store = Store(self.root / 'assistant.db')
        self.chat = self.store.create_chat('Prüfgrenzen')

    def write(self, relative, content):
        target = self.workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def tools(self):
        tools = Toolkit(self.store, self.workspace, lambda *_: True, chat_id=self.chat)
        self.addCleanup(tools.close)
        tools.project_checks = plan_project_checks(self.workspace)['checks']
        return tools

    def python_batches(self):
        for index in range(90):
            self.write(f'extremely_long_source_module_name_{index:03}.py', 'VALUE = 1\n')
        tools = self.tools()
        self.assertGreater(len(tools.project_checks), 1)
        return tools

    def edit(self, tools, relative, content):
        result = tools.call('write_file', {'path': relative, 'content': content})
        self.assertTrue(result.startswith('Gespeichert:'), result)

    def validate(self, tools):
        output = tools.call('project_validate', {})
        self.assertFalse(output.startswith('FEHLER'), output)
        return json.loads(output)

    def test_edit_in_late_syntax_batch_does_not_fail_an_earlier_green_batch(self):
        tools = self.python_batches()
        self.edit(tools, 'extremely_long_source_module_name_089.py', 'VALUE = 2\n')
        result = self.validate(tools)
        self.assertTrue(result['passed'], result)
        self.assertGreaterEqual(len(result['results']), len(tools.project_checks))
        self.assertTrue(all(item['passed'] for item in result['results']))
        self.assertFalse(result['behavior_tests'])
        self.assertEqual(tools.unvalidated_paths, set())
        self.assertEqual(tools.missing_project_checks(), [])

    def test_syntax_batches_collectively_cover_edits_in_different_batches(self):
        tools = self.python_batches()
        self.edit(tools, 'extremely_long_source_module_name_000.py', 'VALUE = 3\n')
        self.edit(tools, 'extremely_long_source_module_name_089.py', 'VALUE = 4\n')
        self.assertEqual(len(tools.unvalidated_paths), 2)
        result = self.validate(tools)
        self.assertTrue(result['passed'], result)
        self.assertEqual(tools.unvalidated_paths, set())
        self.assertEqual(tools.missing_project_checks(), [])

    def test_failure_in_later_batch_keeps_that_source_pending_until_repaired(self):
        tools = self.python_batches()
        broken = 'extremely_long_source_module_name_089.py'
        self.edit(tools, 'extremely_long_source_module_name_000.py', 'VALUE = 3\n')
        self.edit(tools, broken, 'VALUE = (\n')
        failure = self.validate(tools)
        self.assertFalse(failure['passed'])
        self.assertTrue(failure['results'][0]['passed'])
        self.assertFalse(failure['results'][-1]['passed'])
        self.assertIn('SyntaxError', failure['results'][-1]['output'])
        self.assertEqual(tools.unvalidated_paths, {broken})
        self.assertTrue(tools.validation_failures)
        self.edit(tools, broken, 'VALUE = 4\n')
        repaired = self.validate(tools)
        self.assertTrue(repaired['passed'], repaired)
        self.assertEqual(tools.unvalidated_paths, set())
        self.assertEqual(tools.validation_failures, set())

    def test_syntax_check_does_not_clear_an_unrelated_pending_javascript_edit(self):
        self.write('app.py', 'VALUE = 1\n')
        self.write('view.js', 'export const value = 1;\n')
        tools = self.tools()
        self.edit(tools, 'app.py', 'VALUE = 2\n')
        self.edit(tools, 'view.js', 'export const value = 2;\n')
        result = self.validate(tools)
        self.assertTrue(result['results'][0]['passed'])
        self.assertEqual(tools.unvalidated_paths, {'view.js'})

    def test_npm_baseline_cannot_execute_a_new_hook_or_unknown_script(self):
        original = {'scripts': {'test': 'jest --runInBand'}, 'devDependencies': {'jest': '*'}}
        for scripts in ({'test': 'jest --runInBand', 'pretest': 'npm publish'},
                        {'test': 'node arbitrary-script.js'}):
            with self.subTest(scripts=scripts):
                self.write('package.json', json.dumps(original))
                tools = self.tools()
                self.assertEqual([item['command'] for item in tools.project_checks], ['npm run test'])
                self.edit(tools, 'package.json', json.dumps({**original, 'scripts': scripts}))
                # The command layer must never be entered; no npm installation
                # or script execution is necessary to prove this boundary.
                tools.action_run_command = MagicMock(return_value='Exit code: 0\nTests: 1 passed, 1 total\n')
                result = self.validate(tools)
                self.assertFalse(result['passed'])
                tools.action_run_command.assert_not_called()
                self.assertFalse(result['results'][0]['passed'])
                self.assertIn('nicht ausgeführt', result['results'][0]['output'])
                self.assertEqual(len(tools.missing_project_checks()), 1)
                self.assertIn('tests', tools.validation_failures)

    def test_npm_output_requires_passing_tests_rather_than_only_suites_or_skips(self):
        self.write('package.json', json.dumps({'scripts': {'test': 'jest --runInBand'},
                                               'devDependencies': {'jest': '*'}}))
        tools = self.tools()
        for output, expected in (
                ('Test Suites: 1 passed, 1 total\nTests: 1 skipped, 1 total\n', False),
                ('Tests: 0 passed, 2 skipped, 2 total\n', False),
                ('Tests: 1 passed, 1 total\n', True),
                (' Tests  2 passed (2)\n', True),
                ('# tests 1\n# pass 1\n# skipped 0\n', True),
                ('# tests 1\n# pass 0\n# skipped 1\n', False)):
            with self.subTest(output=output):
                self.assertEqual(tools._validates_pending_edits(
                    'npm run test', 'Exit code: 0\n' + output, allow_clean=True), expected)

    def test_windows_npm_uses_resolved_cmd_path_without_enabling_shell(self):
        tools = self.tools()
        process = MagicMock(returncode=0)
        process.communicate.return_value = ('# pass 1\n', None)
        process.poll.return_value = 0
        executable = r'C:\Program Files\nodejs\npm.cmd'
        with patch('sytox.actions.os.name', 'nt'), \
             patch('sytox.actions.shutil.which', return_value=executable) as which, \
             patch('sytox.actions.subprocess.Popen', return_value=process) as execute:
            output = tools.action_run_command('npm run test')
        which.assert_called_once_with('npm.cmd')
        self.assertEqual(execute.call_args.args[0], [executable, 'run', 'test'])
        self.assertFalse(execute.call_args.kwargs.get('shell', False))
        self.assertIn('Exit code: 0', output)


if __name__ == '__main__':
    unittest.main()
