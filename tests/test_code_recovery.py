"""Snapshot rollback tests; never use a real user's project."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from sytox.code_recovery import (
    create_snapshot, snapshot_paths, restore_snapshot,
)
from sytox.actions import tool_schema


class CodeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.cache = self.root / "appdata"
        self.file = self.workspace / "source.py"
        self.file.write_text("value = 1\n", encoding="utf-8")

    def test_snapshot_recovers_known_file_and_preserves_project(self):
        sid, paths = create_snapshot(self.workspace, ["source.py"], data_dir=self.cache)
        self.assertEqual(paths, ["source.py"])
        self.assertEqual(snapshot_paths(self.workspace, sid, data_dir=self.cache),
                         ["source.py"])
        self.file.write_text("value = 900\n", encoding="utf-8")
        restored = restore_snapshot(self.workspace, sid, data_dir=self.cache)
        self.assertEqual(restored, ["source.py"])
        self.assertEqual(self.file.read_text(), "value = 1\n")
        self.assertFalse((self.workspace / "recovery").exists())

    def test_no_path_escape_or_symlink_is_accepted(self):
        with self.assertRaises(PermissionError):
            create_snapshot(self.workspace, ["../outside.py"], data_dir=self.cache)
        with self.assertRaises(ValueError):
            create_snapshot(self.workspace, [], data_dir=self.cache)

    def test_rollback_keeps_unrelated_files(self):
        sid, _ = create_snapshot(self.workspace, ["source.py"], data_dir=self.cache)
        extra = self.workspace / "other.py"
        extra.write_text("important", encoding="utf-8")
        self.file.write_text("modified", encoding="utf-8")
        restore_snapshot(self.workspace, sid, data_dir=self.cache)
        self.assertEqual(extra.read_text(), "important")

    def test_tools_exposed_with_paths_array(self):
        schema = {x["function"]["name"]: x["function"] for x in tool_schema()}
        self.assertEqual(schema["snapshot_project_files"]["parameters"]
                         ["properties"]["paths"]["items"]["type"], "string")
        self.assertIn("rollback_project_snapshot", schema)


if __name__ == "__main__":
    unittest.main()
