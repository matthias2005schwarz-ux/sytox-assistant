"""Local project retrieval keeps useful source evidence within a bounded view."""
import json
from pathlib import Path
import tempfile
import unittest

from sytox.project_context import collect_project_context, project_search


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        self.root.mkdir()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def pricing_project(self):
        self.write('shop/__init__.py', '')
        self.write('shop/prices.py',
                   'from .helper import normalize\n\n'
                   'def calc_total(values):\n'
                   '    return sum(normalize(value) for value in values)\n')
        self.write('shop/helper.py',
                   'def normalize(value):\n'
                   '    return round(value, 2)\n')
        self.write('tests/test_prices.py',
                   'import unittest\nfrom shop.prices import calc_total\n\n'
                   'class PriceTest(unittest.TestCase):\n'
                   '    def test_total(self):\n'
                   '        self.assertEqual(calc_total([1.25, 2.75]), 4)\n')
        self.write('shop/unrelated.py', 'def launch_video():\n    return "video"\n')
        self.write('README.md', '# Shop\nA small Python pricing package.\n')
        self.write('pyproject.toml', '[project]\nname="shop"\nversion="0.1"\n')

    def test_symbol_retrieval_includes_related_test_and_local_dependency(self):
        self.pricing_project()
        result = collect_project_context(self.root, 'Korrigiere calc_total für negative Werte.')
        self.assertTrue({'shop/prices.py', 'shop/helper.py', 'tests/test_prices.py'} <=
                        set(result['files']))
        self.assertIn('tests/test_prices.py', result['test_files'])
        self.assertIn('def calc_total(values):', result['summary'])
        self.assertIn('return round(value, 2)', result['summary'])
        self.assertIn('self.assertEqual(calc_total', result['summary'])
        self.assertRegex(result['summary'], r'(?:\b3\s*[:|]|\bL3\b|:3:)')
        self.assertIsInstance(result['truncated'], bool)
        json.dumps(result, ensure_ascii=False)

    def test_explicit_file_path_selects_source_even_without_symbol_match(self):
        self.write('src/render_widget.py',
                   'class FancyWidget:\n    caption = "good morning"\n')
        self.write('src/worker.py', 'def irrelevant():\n    pass\n')
        result = collect_project_context(self.root, 'Bitte src/render_widget.py überarbeiten.')
        self.assertIn('src/render_widget.py', result['files'])
        self.assertIn('class FancyWidget:', result['summary'])

    def test_search_returns_real_one_based_line_evidence_and_honors_limit(self):
        self.write('src/main.py', '# a header\ndef needle():\n    return "needle"\n')
        self.write('tests/test_main.py', '# needle regression\n')
        result = project_search(self.root, 'needle', max_results=2)
        self.assertEqual(len(result['matches']), 2)
        self.assertTrue(result['truncated'])
        for match in result['matches']:
            source_lines = (self.root / match['path']).read_text(encoding='utf-8').splitlines()
            self.assertEqual(match['text'], source_lines[match['line'] - 1])
            self.assertIn('needle', match['text'])
        self.assertEqual(result, project_search(self.root, 'needle', max_results=2))

    def test_search_finds_short_symbols_and_context_stopwords_literally(self):
        self.write('maths.py', 'def add(x, y):\n    return x + y\n')
        self.write('words.py', 'TEXT = "find the exact phrase"\n')
        for query in ('add', 'x', 'return', 'x + y', 'ADD'):
            with self.subTest(query=query):
                result = project_search(self.root, query)
                self.assertTrue(result['matches'])
                self.assertTrue(all(query.casefold() in match['text'].casefold()
                                    for match in result['matches']))
        self.assertEqual(len(project_search(self.root, 'the exact phrase')['matches']), 1)
        self.assertEqual(project_search(self.root, 'the missing phrase')['matches'], [])

    def test_context_is_bounded_and_does_not_dump_unrelated_sources(self):
        self.pricing_project()
        for index in range(30):
            self.write(f'extras/noise_{index}.py', 'UNRELATED_SENTINEL = "noise"\n' * 100)
        result = collect_project_context(self.root, 'Korrigiere calc_total', max_chars=350)
        self.assertLessEqual(len(result['summary']), 350)
        self.assertTrue(result['truncated'])
        self.assertIn('calc_total', result['summary'])
        self.assertNotIn('UNRELATED_SENTINEL', result['summary'])
        self.assertNotIn('extras/noise_0.py', result['files'])
        for relative in result['files']:
            self.assertIn(relative, result['summary'])

    def test_late_symbol_is_quoted_before_long_unrelated_file_header(self):
        self.write('src/pricing.py', ('# unrelated header ' + 'x' * 450 + '\n') * 200 +
                   'def calc_total(values):\n    return sum(values)\n')
        result = collect_project_context(self.root, 'Korrigiere calc_total', max_chars=700)
        self.assertLessEqual(len(result['summary']), 700)
        self.assertIn('def calc_total(values):', result['summary'])
        self.assertIn('201:', result['summary'])
        self.assertTrue(result['truncated'])

    def test_many_tests_cannot_hide_the_relevant_implementation(self):
        self.write('src/pricing.py', 'def calc_total(values):\n    return sum(values)\n')
        for index in range(8):
            self.write(f'tests/test_calc_total_{index}.py',
                       'from src.pricing import calc_total\n')
        result = collect_project_context(self.root, 'Korrigiere calc_total')
        self.assertIn('src/pricing.py', result['files'])
        self.assertIn('def calc_total(values):', result['summary'])

    def test_tiny_budget_remains_json_serializable_and_within_bound(self):
        self.pricing_project()
        for budget in (0, 25, 100):
            with self.subTest(budget=budget):
                result = collect_project_context(self.root, 'calc_total', max_chars=budget)
                self.assertLessEqual(len(result['summary']), budget)
                self.assertIsInstance(result['files'], list)
                self.assertIsInstance(result['test_files'], list)
                json.dumps(result)

    def test_secret_binary_and_oversize_files_are_never_returned(self):
        self.write('src/safe.py', 'def needle():\n    return 1\n')
        for relative in ('.env', '.env.local', 'credentials.json', 'id_rsa', 'private.pem'):
            self.write(relative, 'NEEDLE_PRIVATE_MATERIAL_DO_NOT_READ\n')
        self.write('large.py', 'needle = "OVERSIZE_DO_NOT_READ"\n' * 12000)
        self.write('src/key_material.py',
                   '# needle\n-----BEGIN PRIVATE KEY-----\n'
                   'PEM_CONTENT_DO_NOT_READ\n-----END PRIVATE KEY-----\n')
        binary = self.root / 'binary.py'
        binary.write_bytes(b'needle = "BINARY_DO_NOT_READ"\x00\xff')
        search = project_search(self.root, 'needle')
        self.assertEqual({item['path'] for item in search['matches']}, {'src/safe.py'})
        context = collect_project_context(self.root, 'needle')
        self.assertIn('src/safe.py', context['files'])
        for sentinel in ('PRIVATE_MATERIAL', 'OVERSIZE_DO_NOT_READ',
                         'BINARY_DO_NOT_READ', 'PEM_CONTENT_DO_NOT_READ'):
            self.assertNotIn(sentinel, context['summary'])

    def test_generated_dependency_and_backup_directories_are_ignored(self):
        self.write('src/needle.py', 'needle = 1\n')
        for directory in ('.git', '.venv', 'node_modules', 'build', 'dist', 'backups', '__pycache__'):
            self.write(directory + '/hidden.py', 'needle = "IGNORED_DATA"\n')
        search = project_search(self.root, 'needle')
        self.assertEqual({item['path'] for item in search['matches']}, {'src/needle.py'})
        context = collect_project_context(self.root, 'needle')
        self.assertNotIn('IGNORED_DATA', context['summary'])

    def test_symlinked_files_and_directories_are_not_followed(self):
        outside = Path(self.tmp.name) / 'external'
        outside.mkdir()
        secret = outside / 'private.py'
        secret.write_text('needle = "OUTSIDE_SECRET"\n', encoding='utf-8')
        self.write('safe.py', 'needle = "inside"\n')
        try:
            (self.root / 'linked.py').symlink_to(secret)
            (self.root / 'linked_dir').symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest('Symlink creation unavailable: ' + str(exc))
        search = project_search(self.root, 'needle')
        self.assertEqual({item['path'] for item in search['matches']}, {'safe.py'})
        context = collect_project_context(self.root, 'needle linked.py linked_dir/private.py')
        self.assertNotIn('OUTSIDE_SECRET', context['summary'])
        self.assertNotIn('linked.py', context['files'])
        self.assertNotIn('linked_dir/private.py', context['files'])

    def test_empty_or_missing_workspaces_and_unmatched_search_are_structured(self):
        for workspace in (self.root, self.root / 'does-not-exist'):
            with self.subTest(workspace=workspace):
                self.assertEqual(project_search(workspace, 'not_present')['matches'], [])
                result = collect_project_context(workspace, 'not_present')
                self.assertEqual(result['files'], [])
                self.assertEqual(result['test_files'], [])
                self.assertIsInstance(result['summary'], str)
        self.write('main.py', 'VALUE = 1\n')
        self.assertEqual(project_search(self.root, 'nonexistent_symbol')['matches'], [])

    def test_selection_is_deterministic_without_modifying_the_project(self):
        self.pricing_project()
        before = {path.relative_to(self.root): path.read_bytes()
                  for path in self.root.rglob('*') if path.is_file()}
        first = collect_project_context(self.root, 'calc_total')
        self.assertEqual(first, collect_project_context(self.root, 'calc_total'))
        after = {path.relative_to(self.root): path.read_bytes()
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
