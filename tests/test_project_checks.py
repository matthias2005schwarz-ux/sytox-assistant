"""Real temporary project fixtures for bounded, read-only verification plans."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.project_checks import plan_project_checks


class ProjectCheckPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'project'
        self.root.mkdir()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def commands(self, plan):
        return [item['command'] for item in plan['checks']]

    def package(self, scripts, dependencies=None):
        self.write('package.json', json.dumps({'scripts': scripts,
                    'devDependencies': dependencies or {'jest': '*', 'vitest': '*',
                                                        'eslint': '*', 'typescript': '*', 'vite': '*'}}))

    def test_unittest_plan_executes_real_existing_test(self):
        self.write('app.py', 'VALUE = 2\n')
        self.write('tests/test_value.py', 'import unittest\nfrom app import VALUE\n'
                   'class Value(unittest.TestCase):\n'
                   '    def test_value(self): self.assertEqual(VALUE, 2)\n')
        plan = plan_project_checks(self.root, ['app.py'])
        self.assertEqual(self.commands(plan), ['python -m unittest discover -s tests'])
        self.assertTrue(plan['behavior_tests'])
        self.assertEqual(plan['test_files'], ['tests/test_value.py'])
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Ran 1 test', result.stderr)

    def test_root_test_files_are_discovered_from_dot(self):
        self.write('test_root.py', 'import unittest\nclass Root(unittest.TestCase): pass\n')
        plan = plan_project_checks(self.root)
        self.assertEqual(self.commands(plan), ['python -m unittest discover -s .'])

    def test_plain_test_functions_use_pytest_instead_of_empty_unittest(self):
        self.write('tests/test_app.py', 'def test_answer():\n    assert 2 + 2 == 4\n')
        plan = plan_project_checks(self.root)
        self.assertEqual(self.commands(plan), ['python -m pytest'])
        self.assertTrue(plan['behavior_tests'])
        self.assertTrue(any('nicht automatisch installiert' in note for note in plan['notes']))

    def test_pytest_class_and_alias_import_are_recognized(self):
        for source in ('class TestApp:\n    def test_answer(self): assert True\n',
                       'import pytest as pt\n', 'from pytest import fixture\n'):
            with self.subTest(source=source):
                self.write('tests/test_app.py', source)
                self.assertEqual(self.commands(plan_project_checks(self.root)), ['python -m pytest'])

    def test_pytest_config_is_evidence_even_without_standard_filename(self):
        self.write('pyproject.toml', '[tool.pytest.ini_options]\npython_files = ["spec_*.py"]\n')
        self.write('spec_value.py', 'def test_answer(): assert True\n')
        self.assertEqual(self.commands(plan_project_checks(self.root)), ['python -m pytest'])

    def test_setup_cfg_selects_pytest_and_docstring_does_not(self):
        self.write('tests/test_app.py', '"""import pytest\ndef test_fake(): pass\n"""\n'
                   'import unittest\nclass App(unittest.TestCase): pass\n')
        self.assertEqual(self.commands(plan_project_checks(self.root)), ['python -m unittest discover -s tests'])
        self.write('setup.cfg', '[tool:pytest]\naddopts = -q\n')
        self.assertEqual(self.commands(plan_project_checks(self.root)), ['python -m pytest'])

    def test_nested_nonpackage_tests_are_not_silently_left_unrun(self):
        self.write('tests/test_root.py', 'import unittest\n')
        self.write('tests/unit/test_value.py', 'import unittest\n')
        plan = plan_project_checks(self.root)
        self.assertEqual(self.commands(plan), ['python -m unittest discover -s tests',
                                               'python -m unittest discover -s tests/unit'])

    def test_changed_python_sources_receive_syntax_only_fallback(self):
        self.write('app.py', 'VALUE = 1\n')
        self.write('unchanged.py', 'VALUE = 3\n')
        plan = plan_project_checks(self.root, ['app.py'])
        self.assertEqual(self.commands(plan), ['python -m compileall -q app.py'])
        self.assertEqual(plan['checks'][0]['kind'], 'syntax')
        self.assertFalse(plan['behavior_tests'])
        self.assertTrue(any('keine korrekte Funktion' in note for note in plan['notes']))

    def test_paths_with_spaces_are_quoted_for_both_platforms(self):
        self.write('source folder/app.py', 'VALUE = 1\n')
        self.assertEqual(self.commands(plan_project_checks(self.root)),
                         ['python -m compileall -q "source folder/app.py"'])

    def test_unknown_or_shell_sensitive_filenames_are_not_interpolated(self):
        self.write('bad;echo.py', 'VALUE = 1\n')
        plan = plan_project_checks(self.root, ['../outside.py', 'bad;echo.py'])
        self.assertEqual(plan['checks'], [])
        self.assertFalse(plan['behavior_tests'])

    def test_local_single_run_javascript_checks_are_planned_in_order(self):
        self.package({'test': 'vitest run', 'lint': 'eslint .',
                      'typecheck': 'tsc --noEmit', 'build': 'vite build'})
        self.write('src/value.spec.ts', 'export const value = 1;\n')
        plan = plan_project_checks(self.root)
        self.assertEqual(self.commands(plan), ['npm run test', 'npm run lint',
                                               'npm run typecheck', 'npm run build'])
        self.assertEqual([item['runner'] for item in plan['checks']], ['vitest', 'eslint', 'tsc', 'vite'])
        self.assertTrue(plan['behavior_tests'])
        self.assertEqual(plan['test_files'], ['src/value.spec.ts'])

    def test_jest_and_builtin_node_tests_are_recognized(self):
        for script in ('jest --runInBand', 'node --test'):
            with self.subTest(script=script):
                self.package({'test': script})
                self.assertEqual(self.commands(plan_project_checks(self.root)), ['npm run test'])

    def test_placeholder_watch_and_arbitrary_npm_scripts_are_not_automatic(self):
        for script in ('echo Error: no test specified && exit 1', 'vitest', 'vitest --watch',
                       'jest --watchAll', 'jest --passWithNoTests', 'node test.js',
                       'npx jest', 'npm install && jest', 'jest; npm publish',
                       'jest $(echo publish)', 'cross-env CI=true jest'):
            with self.subTest(script=script):
                self.package({'test': script})
                plan = plan_project_checks(self.root)
                self.assertEqual(plan['checks'], [])
                self.assertFalse(plan['behavior_tests'])

    def test_lifecycle_hooks_exclude_only_affected_script(self):
        self.package({'test': 'jest', 'pretest': 'npm publish', 'lint': 'eslint .',
                      'build': 'vite build', 'postbuild': 'node deploy.js'})
        plan = plan_project_checks(self.root)
        self.assertEqual(self.commands(plan), ['npm run lint'])
        self.assertFalse(plan['behavior_tests'])
        self.assertTrue(any('Lifecycle-Hooks' in note for note in plan['notes']))

    def test_release_install_and_mutating_lint_are_never_planned(self):
        self.package({'release': 'npm publish', 'install': 'node download.js',
                      'lint': 'eslint . --fix', 'typecheck': 'tsc --noEmit false',
                      'build': 'vite build && npm publish'})
        self.assertEqual(plan_project_checks(self.root)['checks'], [])

    def test_runner_must_be_declared_as_project_dependency(self):
        self.write('package.json', '{"scripts":{"test":"jest"},"devDependencies":{}}')
        self.assertFalse(plan_project_checks(self.root)['behavior_tests'])

    def test_nested_package_gets_an_honest_cwd_note(self):
        self.write('frontend/package.json', '{"scripts":{"test":"node --test"}}')
        plan = plan_project_checks(self.root)
        self.assertEqual(plan['checks'], [])
        self.assertTrue(any('Arbeitsordner' in note for note in plan['notes']))

    def test_ignored_dirs_secrets_and_external_symlinks_are_not_read(self):
        for path in ('.venv/test_fake.py', 'node_modules/test_fake.py', 'dist/test_fake.py',
                     'backups/test_fake.py', '.private/test_fake.py'):
            self.write(path, 'import pytest\n')
        self.write('.env', 'SECRET=should-not-be-present')
        self.write('app.py', 'VALUE = 1\n')
        outside = Path(self.temp.name) / 'private'
        outside.mkdir()
        (outside / 'test_private.py').write_text('import pytest\n', encoding='utf-8')
        try:
            (self.root / 'external').symlink_to(outside, target_is_directory=True)
            (self.root / 'test_link.py').symlink_to(outside / 'test_private.py')
        except OSError:
            self.skipTest('Symlinks unavailable')
        plan = plan_project_checks(self.root)
        self.assertEqual(self.commands(plan), ['python -m compileall -q app.py'])
        self.assertEqual(plan['test_files'], [])
        self.assertNotIn('should-not-be-present', json.dumps(plan))

    def test_oversized_or_invalid_manifest_is_not_dumped_or_executed(self):
        self.write('package.json', 'SENSITIVE' * 9000)
        plan = plan_project_checks(self.root)
        self.assertEqual(plan['checks'], [])
        self.assertNotIn('SENSITIVE', json.dumps(plan))

    def test_scan_and_check_counts_are_bounded_with_explicit_limit_notes(self):
        for index in range(9):
            self.write(f'suite_{index}/test_value.py', 'import unittest\n')
        plan = plan_project_checks(self.root)
        self.assertEqual(len(plan['checks']), 6)
        self.assertTrue(plan['truncated'])
        with patch('sytox.project_checks._MAX_FILES', 3):
            bounded = plan_project_checks(self.root)
        self.assertTrue(bounded['truncated'])
        self.assertLessEqual(len(bounded['test_files']), 3)

    def test_plan_is_deterministic_and_does_not_mutate_project(self):
        self.write('app.py', 'VALUE = 1\n')
        self.package({'test': 'node --test'})
        before = {str(path.relative_to(self.root)): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        first = plan_project_checks(self.root, ['app.py'])
        second = plan_project_checks(self.root, ['app.py'])
        after = {str(path.relative_to(self.root)): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(first, second)
        self.assertEqual(before, after)

    def test_missing_and_unknown_project_have_no_invented_success(self):
        missing = plan_project_checks(self.root / 'missing')
        self.assertEqual(missing['checks'], [])
        self.assertFalse(missing['behavior_tests'])
        self.write('README.md', 'No known runner')
        unknown = plan_project_checks(self.root)
        self.assertEqual(unknown['checks'], [])
        self.assertFalse(unknown['behavior_tests'])
        self.assertTrue(unknown['notes'])


if __name__ == '__main__':
    unittest.main()
