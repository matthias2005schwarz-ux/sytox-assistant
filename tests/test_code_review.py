"""Review evidence is actual local source, not a model-reported success flag."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from sytox.code_review import build_review_bundle, parse_review, review_messages
from sytox.project_backup import create_snapshot


class ReviewBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'work'
        self.workspace.mkdir()
        self.backups = self.root / 'backups'

    def write(self, relative, source):
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode('utf-8') if isinstance(source, str) else source)
        return path

    def snapshot(self):
        return Path(create_snapshot(self.workspace, self.backups)['path'])

    def archive(self, relative, data, *, digest=None):
        path = self.root / 'custom.zip'
        manifest = {'format': 1, 'files': [{
            'path': relative, 'size': len(data),
            'sha256': digest if digest is not None else hashlib.sha256(data).hexdigest(),
        }]}
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(relative, data)
            archive.writestr('SYTOX_SNAPSHOT_MANIFEST.json', json.dumps(manifest))
        return path

    def test_real_snapshot_reports_added_modified_and_deleted_files_without_git(self):
        self.write('app.py', 'def value():\n    return 1\n')
        removed = self.write('removed.py', 'OLD = True\n')
        baseline = self.snapshot()
        self.write('app.py', 'def value():\n    return 2\n')
        self.write('new.py', 'NEW = True\n')
        removed.unlink()
        result = build_review_bundle(self.workspace, baseline)
        self.assertTrue(result['complete'], result['notes'])
        files = {item['path']: item for item in result['files']}
        self.assertEqual({path: item['status'] for path, item in files.items()},
                         {'app.py': 'modified', 'new.py': 'added', 'removed.py': 'deleted'})
        self.assertEqual(files['app.py']['before_sha256'],
                         hashlib.sha256(b'def value():\n    return 1\n').hexdigest())
        self.assertEqual(files['app.py']['after_sha256'],
                         hashlib.sha256(b'def value():\n    return 2\n').hexdigest())
        self.assertIn('-    return 1', result['diff'])
        self.assertIn('+    return 2', result['diff'])
        self.assertIn('+NEW = True', result['diff'])
        self.assertIn('-OLD = True', result['diff'])
        self.assertIn('@@', result['diff'])
        self.assertFalse((self.workspace / '.git').exists())

    def test_fingerprint_is_deterministic_and_invalidates_after_another_source_edit(self):
        self.write('app.py', 'VALUE = 1\n')
        baseline = self.snapshot()
        self.write('app.py', 'VALUE = 2\n')
        first = build_review_bundle(self.workspace, baseline)
        same = build_review_bundle(self.workspace, baseline)
        self.assertTrue(first['fingerprint'])
        self.assertEqual(first['fingerprint'], same['fingerprint'])
        self.write('app.py', 'VALUE = 3\n')
        changed = build_review_bundle(self.workspace, baseline)
        self.assertNotEqual(first['fingerprint'], changed['fingerprint'])
        self.assertIn('+VALUE = 3', changed['diff'])

    def test_unchanged_project_has_no_invented_diff(self):
        self.write('app.py', 'VALUE = 1\n')
        result = build_review_bundle(self.workspace, self.snapshot())
        self.assertTrue(result['complete'], result['notes'])
        self.assertEqual(result['files'], [])
        self.assertFalse(result['diff'].strip())

    def test_a_bounded_diff_cannot_claim_to_be_a_complete_review(self):
        self.write('app.py', ''.join(f'VALUE_{index} = 1\n' for index in range(140)))
        baseline = self.snapshot()
        self.write('app.py', ''.join(f'VALUE_{index} = 2\n' for index in range(140)))
        result = build_review_bundle(self.workspace, baseline, max_chars=400)
        self.assertFalse(result['complete'])
        self.assertLessEqual(len(result['diff']), 400)
        self.assertTrue(result['notes'])

    def test_complete_diff_chunks_retain_every_changed_line_and_file_context(self):
        self.write('app.py', ''.join(f'VALUE_{index} = 1\n' for index in range(45)))
        baseline = self.snapshot()
        self.write('app.py', ''.join(f'VALUE_{index} = 2\n' for index in range(45)))
        result = build_review_bundle(self.workspace, baseline, max_chars=500)
        self.assertFalse(result['complete'])
        self.assertTrue(result['review_complete'], result['notes'])
        self.assertGreater(len(result['chunks']), 1)
        self.assertLessEqual(len(result['chunks']), 6)
        for chunk in result['chunks']:
            self.assertLessEqual(len(chunk), 500)
            self.assertIn('--- a/app.py\n+++ b/app.py', chunk)
            self.assertIn('@@', chunk)
        joined = '\n'.join(result['chunks'])
        for index in range(45):
            self.assertIn(f'-VALUE_{index} = 1', joined)
            self.assertIn(f'+VALUE_{index} = 2', joined)
        messages = review_messages('Ändere alle Werte',
                                   {**result, 'diff': result['chunks'][0], 'complete': True}, [])
        self.assertNotIn('"chunks"', messages[-1]['content'])

    def test_chunk_limit_and_unreadable_source_cannot_claim_complete_review_coverage(self):
        self.write('app.py', ''.join(f'VALUE_{index} = 1\n' for index in range(300)))
        baseline = self.snapshot()
        self.write('app.py', ''.join(f'VALUE_{index} = 2\n' for index in range(300)))
        result = build_review_bundle(self.workspace, baseline, max_chars=300)
        self.assertFalse(result['review_complete'])
        self.assertLessEqual(len(result['chunks']), 6)
        self.write('app.py', b'\xff\xfe\x00\x00')
        result = build_review_bundle(self.workspace, baseline)
        self.assertFalse(result['review_complete'])
        self.assertFalse(result['complete'])

    def test_newline_only_changes_and_missing_final_newline_are_explicit(self):
        self.write('app.py', b'VALUE = 1\r\n')
        baseline = self.snapshot()
        self.write('app.py', b'VALUE = 1\n')
        result = build_review_bundle(self.workspace, baseline)
        self.assertIn('Zeilenenden', result['diff'])
        self.write('app.py', b'VALUE = 2')
        result = build_review_bundle(self.workspace, baseline)
        self.assertIn('+VALUE = 2\n', result['diff'])
        self.assertIn('No newline at end of file', result['diff'])

    def test_missing_or_corrupt_baseline_is_incomplete_and_does_not_mutate_source(self):
        source = self.write('app.py', 'VALUE = 1\n')
        corrupt = self.root / 'broken.zip'
        corrupt.write_bytes(b'not a ZIP')
        for archive in (self.root / 'missing.zip', corrupt):
            with self.subTest(archive=archive):
                result = build_review_bundle(self.workspace, archive)
                self.assertFalse(result['complete'])
                self.assertTrue(result['notes'])
                self.assertEqual(source.read_bytes(), b'VALUE = 1\n')

    def test_snapshot_member_traversal_never_reads_or_writes_outside_source(self):
        outside = self.root / 'outside.py'
        outside.write_text('OUTSIDE_PRIVATE_SENTINEL\n', encoding='utf-8')
        archive = self.archive('../outside.py', b'ARCHIVE_SENTINEL\n')
        result = build_review_bundle(self.workspace, archive)
        self.assertFalse(result['complete'])
        self.assertNotIn('OUTSIDE_PRIVATE_SENTINEL', result['diff'])
        self.assertNotIn('ARCHIVE_SENTINEL', result['diff'])
        self.assertEqual(outside.read_text(encoding='utf-8'), 'OUTSIDE_PRIVATE_SENTINEL\n')

    def test_snapshot_content_must_match_its_recorded_hash(self):
        archive = self.archive('app.py', b'UNTRUSTWORTHY_BASELINE\n', digest='0' * 64)
        result = build_review_bundle(self.workspace, archive)
        self.assertFalse(result['complete'])
        self.assertNotIn('UNTRUSTWORTHY_BASELINE', result['diff'])

    def test_secret_files_are_not_inserted_into_the_review_prompt(self):
        self.write('.env', 'API_TOKEN=OLD_PRIVATE_SENTINEL\n')
        self.write('app.py', 'VALUE = 1\n')
        baseline = self.snapshot()
        self.write('.env', 'API_TOKEN=NEW_PRIVATE_SENTINEL\n')
        self.write('app.py', 'VALUE = 2\n')
        result = build_review_bundle(self.workspace, baseline)
        messages = review_messages('Ändere VALUE auf 2', result, [])
        prompt = '\n'.join(item['content'] for item in messages)
        self.assertIn('VALUE = 2', result['diff'])
        self.assertNotIn('OLD_PRIVATE_SENTINEL', prompt)
        self.assertNotIn('NEW_PRIVATE_SENTINEL', prompt)
        self.assertTrue(result['notes'])

    def test_binary_changes_are_disclosed_without_dumping_binary_data(self):
        self.write('logo.bin', b'\0OLD_BINARY_SENTINEL')
        baseline = self.snapshot()
        self.write('logo.bin', b'\0NEW_BINARY_SENTINEL')
        result = build_review_bundle(self.workspace, baseline)
        self.assertTrue(result['notes'])
        self.assertNotIn('OLD_BINARY_SENTINEL', result['diff'])
        self.assertNotIn('NEW_BINARY_SENTINEL', result['diff'])

    def test_generated_outputs_are_not_reviewed_as_new_source_files(self):
        self.write('app.py', 'VALUE = 1\n')
        baseline = self.snapshot()
        for path in ('build/generated.py', 'build_output/generated.py',
                     '.venv/generated.py', 'node_modules/generated.js', '__pycache__/temp.pyc'):
            self.write(path, 'GENERATED_SENTINEL\n')
        result = build_review_bundle(self.workspace, baseline)
        self.assertTrue(result['complete'], result['notes'])
        self.assertEqual(result['files'], [])
        self.assertNotIn('GENERATED_SENTINEL', result['diff'])

    def test_symlink_cannot_supply_external_source_to_the_review(self):
        baseline = self.snapshot()
        outside = self.root / 'private.py'
        outside.write_text('EXTERNAL_SOURCE_SENTINEL\n', encoding='utf-8')
        try:
            (self.workspace / 'linked.py').symlink_to(outside)
        except OSError as exc:
            self.skipTest('Symlink creation unavailable: ' + str(exc))
        result = build_review_bundle(self.workspace, baseline)
        self.assertFalse(result['complete'])
        self.assertNotIn('EXTERNAL_SOURCE_SENTINEL', result['diff'])

    def test_source_and_tool_instructions_are_kept_out_of_the_system_message(self):
        self.write('app.py', 'VALUE = 1\n')
        baseline = self.snapshot()
        self.write('app.py', '# FILE_INJECTION_IGNORE_THE_USER\nVALUE = 2\n')
        bundle = build_review_bundle(self.workspace, baseline)
        messages = review_messages('Setze VALUE auf 2', bundle,
                                   [{'command': 'python -m unittest', 'output': 'TOOL_INJECTION_APPROVE_EVERYTHING'}])
        self.assertEqual(messages[0]['role'], 'system')
        self.assertNotIn('FILE_INJECTION_IGNORE_THE_USER', messages[0]['content'])
        self.assertNotIn('TOOL_INJECTION_APPROVE_EVERYTHING', messages[0]['content'])
        self.assertIn('JSON', messages[0]['content'])
        data = '\n'.join(message['content'] for message in messages[1:])
        self.assertIn('Setze VALUE auf 2', data)
        self.assertIn('FILE_INJECTION_IGNORE_THE_USER', data)
        self.assertIn('TOOL_INJECTION_APPROVE_EVERYTHING', data)


class StructuredReviewTests(unittest.TestCase):
    def report(self, status='passed', findings=None):
        return {'status': status, 'summary': 'Quellcode und Auftrag verglichen.',
                'findings': [] if findings is None else findings}

    def test_valid_json_reply_and_fenced_model_message_are_accepted(self):
        raw = json.dumps(self.report())
        for reply in (raw, {'role': 'assistant', 'content': raw},
                      {'role': 'assistant', 'content': '```json\n' + raw + '\n```'}):
            with self.subTest(reply=reply):
                result = parse_review(reply)
                self.assertEqual(result['status'], 'passed')
                self.assertEqual(result['findings'], [])

    def test_concrete_findings_override_a_contradictory_passed_verdict(self):
        finding = {'path': 'app.py', 'line': 2, 'message': 'Der falsche Operator verletzt den Auftrag.'}
        result = parse_review(json.dumps(self.report(findings=[finding])))
        self.assertEqual(result['status'], 'changes_requested')
        self.assertEqual(result['findings'][0], finding)
        requested = parse_review(json.dumps(self.report('changes_requested', [finding])))
        self.assertEqual(requested['status'], 'changes_requested')

    def test_plain_text_invalid_json_and_unknown_status_never_pass(self):
        for reply in ('Alles geprüft, fertig!', '', '[]', 'null', '{broken',
                      json.dumps({'status': 'passed'}), json.dumps(self.report('maybe')),
                      json.dumps({**self.report(), 'summary': 1})):
            with self.subTest(reply=reply):
                self.assertEqual(parse_review(reply)['status'], 'unavailable')

    def test_review_cannot_smuggle_tool_calls_or_invalid_line_references(self):
        reply = {'role': 'assistant', 'content': json.dumps(self.report()),
                 'tool_calls': [{'function': {'name': 'write_file', 'arguments': {}}}]}
        self.assertEqual(parse_review(reply)['status'], 'unavailable')
        for line in (0, -2, True, '2'):
            with self.subTest(line=line):
                finding = {'path': 'app.py', 'line': line, 'message': 'Bitte prüfen.'}
                self.assertEqual(parse_review(json.dumps(self.report('changes_requested', [finding])))['status'],
                                 'unavailable')


if __name__ == '__main__':
    unittest.main()
