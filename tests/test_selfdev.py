"""Integration tests for the review -> test -> stage workflow."""
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

from sytox.selfdev import SelfDevelopment
from sytox.actions import Toolkit
from sytox.storage import Store
from sytox.agent import Agent


def call_tool(name, **kwargs):
    return {'role': 'assistant', 'content': '',
            'tool_calls': [{'function': {'name': name, 'arguments': kwargs}}]}


class SelfDevTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'installed'
        (self.source / 'sytox').mkdir(parents=True)
        (self.source / 'tests').mkdir()
        (self.source / 'sytox' / '__init__.py').write_text('VALUE = 1\n')
        (self.source / 'tests' / 'test_smoke.py').write_text(
            'import unittest\nfrom sytox import VALUE\n'
            'class TestSmoke(unittest.TestCase):\n'
            '    def test_positive(self): self.assertGreater(VALUE, 0)\n')
        (self.source / 'main.py').write_text('from sytox import VALUE\n')
        self.approvals = []

        def approve(label, description):
            self.approvals.append(label)
            return True
        self.sd = SelfDevelopment(self.root / 'workspace', approve,
                                  source=self.source, data_dir=self.root/'appdata')

    def test_worktree_diff_validation_and_staging(self):
        self.assertIn('erstellt', self.sd.prepare())
        self.assertEqual(self.sd.review()['changed'], [])
        self.assertIn('unverändert', self.sd.prepare())
        (self.sd.worktree / 'sytox' / '__init__.py').write_text('VALUE = 7\n')
        review = self.sd.review()
        self.assertEqual(review['changed'], ['sytox/__init__.py'])
        self.assertIn('GEÄNDERT', review['report'])
        self.assertIn('1 Tests erfolgreich', self.sd.validate())
        staged = self.sd.stage()
        self.assertIn('Kandidat erstellt', staged)
        packages = list((self.sd.workspace / 'selfdev_releases').glob('*.zip'))
        self.assertEqual(len(packages), 1)
        with zipfile.ZipFile(packages[0]) as z:
            manifest = json.loads(z.read('SELFDEV_REVIEW.json'))
            self.assertEqual(manifest['tests'], 1)
            self.assertIn('sytox/__init__.py', manifest['changed_files'])
        self.assertEqual((self.source / 'sytox' / '__init__.py').read_text(), 'VALUE = 1\n')
        self.assertIn('Self-Development-Tests ausführen', self.approvals)
        self.assertIn('Geprüftes Update als ZIP bereitstellen', self.approvals)

    def test_source_change_after_tests_prevents_staging(self):
        self.sd.prepare()
        f = self.sd.worktree / 'sytox' / '__init__.py'
        f.write_text('VALUE = 4\n')
        self.sd.validate()
        f.write_text('VALUE = 5\n')
        with self.assertRaisesRegex(ValueError, 'erneut validieren'):
            self.sd.stage()

    def test_failed_tests_cannot_be_staged(self):
        self.sd.prepare()
        (self.sd.worktree / 'sytox' / '__init__.py').write_text('VALUE = -1\n')
        with self.assertRaisesRegex(RuntimeError, 'Tests fehlgeschlagen'):
            self.sd.validate()
        with self.assertRaisesRegex(ValueError, 'Erst selfdev_validate'):
            self.sd.stage()

    def test_approval_denial_prevents_test_execution(self):
        self.sd.prepare()
        (self.sd.worktree / 'sytox' / '__init__.py').write_text('VALUE = 2\n')
        self.sd.approve = lambda *_: (_ for _ in ()).throw(PermissionError('Denied'))
        with self.assertRaisesRegex(PermissionError, 'Denied'):
            self.sd.validate()
        self.assertFalse(self.sd.validation.exists())

    def test_toolkit_accepts_only_selfdev_validated_changes(self):
        store = Store(self.root / 'toolkit.db')
        cid = store.create_chat()
        tools = Toolkit(store, self.root / 'workspace', lambda *_: True, threading.Event(), cid)
        tools.selfdev = self.sd
        self.assertIn('erstellt', tools.call('selfdev_prepare', {}))
        self.assertIn('Gespeichert', tools.call('write_file', {
            'path': 'assistant_source/sytox/__init__.py', 'content': 'VALUE = 3\n'}))
        self.assertIn(str(Path('assistant_source') / 'sytox' / '__init__.py'), tools.unvalidated_paths)
        self.assertIn('1 Tests erfolgreich', tools.call('selfdev_validate', {}))
        self.assertEqual(tools.passed_checks, 1)
        self.assertEqual(tools.unvalidated_paths, set())
        self.assertIn('Kandidat erstellt', tools.call('selfdev_stage', {}))
        tools.close()

    def test_symlink_rejected(self):
        self.sd.prepare()
        try:
            (self.sd.worktree / 'link').symlink_to(self.source, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink unavailable')
        with self.assertRaisesRegex(ValueError, 'Symbolische Verknüpfung'):
            self.sd.review()


class ProgressCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'db.sqlite')
        self.cid = self.store.create_chat()
        self.store.add_message(self.cid, 'user', 'Programmiere mehrere Module')

    def _agent(self, replies):
        agent = Agent(self.store, 'mock', 'http://unused', str(self.root/'workspace'),
                      lambda *_: True, lambda *_: None, threading.Event())
        agent.client.chat = MagicMock(side_effect=replies)
        return agent

    def test_progress_note_persists_across_manual_resume(self):
        agent = self._agent([
            call_tool('write_file', path='module.py', content='print(5)\n'),
            call_tool('record_progress', completed='module.py geschrieben',
                      next_step='Compileall ausführen', evidence='write_file module.py'),
            call_tool('report_blocker', reason='Pause bis später'),
        ])
        first = agent.run(self.cid, 'until_done')
        self.assertEqual(first['status'], 'paused')
        cp = json.loads(self.store.tasks(self.cid)[0]['checkpoint'])
        self.assertEqual(cp['progress_notes'][0]['next_step'], 'Compileall ausführen')
        resumed = self._agent([
            call_tool('run_command', command='python -m compileall module.py'),
            call_tool('complete_task', summary='Geprüft', evidence='compileall 0'),
        ])
        result = resumed.run(self.cid, task_id=first['task_id'])
        self.assertEqual(result['status'], 'done')
        self.assertEqual(json.loads(self.store.tasks(self.cid)[0]['checkpoint'])['progress_notes'], cp['progress_notes'])
        # The model sees the saved note in the resume prompt.
        sent = resumed.client.chat.call_args_list[0].args[0]
        self.assertIn('Compileall ausführen', str(sent))

    def test_unverified_progress_notes_cannot_complete_job(self):
        agent = self._agent([
            call_tool('record_progress', completed='Behaupte fertig', next_step='Keine', evidence='unverified'),
            call_tool('complete_task', summary='done', evidence='none'),
            call_tool('report_blocker', reason='Noch keine Arbeit ausgeführt'),
        ])
        self.assertEqual(agent.run(self.cid,'until_done')['status'], 'paused')
