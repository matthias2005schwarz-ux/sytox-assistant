"""Project snapshots are checked before mutations and recoverable with consent."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.project_backup import (
    SnapshotError, create_snapshot, list_snapshots, restore_snapshot,
)


class ProjectBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.project = root / 'workspace'
        self.project.mkdir()
        self.backups = root / 'snapshots'

    def test_restores_previous_sources_only_after_approval(self):
        original = self.project / 'game.py'
        original.write_text('print("Version 1")\n', encoding='utf-8')
        result = create_snapshot(self.project, self.backups)
        self.assertTrue(result['verified_zip'])
        self.assertEqual(result['files'], 1)
        original.write_text('broken code', encoding='utf-8')
        denied = restore_snapshot(
            self.project, self.backups, result['filename'], lambda *args: False)
        self.assertEqual(denied['status'], 'denied')
        self.assertEqual(original.read_text(encoding='utf-8'), 'broken code')
        granted = []
        restored = restore_snapshot(
            self.project, self.backups, result['filename'],
            lambda *args: granted.append(args) or True,
        )
        self.assertEqual(restored['status'], 'restored')
        self.assertEqual(original.read_text(encoding='utf-8'), 'print("Version 1")\n')
        self.assertTrue(granted)
        self.assertIn('before_restore', restored['recovery_snapshot'])
        self.assertGreaterEqual(len(list_snapshots(self.backups)), 2)

    def test_rejects_backup_path_in_workspace_and_unsafe_name(self):
        with self.assertRaises(SnapshotError):
            create_snapshot(self.project, self.project / 'snapshots')
        snap = create_snapshot(self.project, self.backups)
        with self.assertRaises(SnapshotError):
            restore_snapshot(self.project, self.backups, '../wrong.zip',
                             lambda *_: True)
        self.assertTrue(snap['filename'].endswith('.zip'))

    def test_does_not_save_venv_and_git_in_source_backup(self):
        (self.project / 'game.py').write_text('ok', encoding='utf-8')
        (self.project / 'node_modules').mkdir()
        (self.project / 'node_modules' / 'index.js').write_text('dependency')
        snapshot = create_snapshot(self.project, self.backups)
        self.assertEqual(snapshot['files'], 1)

    def test_rejects_oversized_source_instead_of_partial_backup(self):
        (self.project / 'large.bin').write_bytes(b'x' * 300)
        with patch('sytox.project_backup.MAX_FILE_BYTES', 10):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.project, self.backups)
        self.assertEqual(list_snapshots(self.backups), [])


if __name__ == '__main__':
    unittest.main()
