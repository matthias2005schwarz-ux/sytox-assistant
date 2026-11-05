"""Regression tests for local project indexing and stale source detection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sytox.project_memory import (
    update_project_memory, lookup_project_memory, _index_path,
)
from sytox.actions import tool_schema


class ProjectMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.data = self.root / "local_data"
        self.workspace.mkdir()
        (self.workspace / "main.py").write_text(
            "import sys\nclass MyApp:\n    pass\ndef repair_project():\n    return True\n",
            encoding="utf-8"
        )
        (self.workspace / ".env").write_text("SUPER_SECRET=never_index", encoding="utf-8")
        (self.workspace / "node_modules").mkdir()
        (self.workspace / "node_modules" / "secret.js").write_text(
            "function neverIndexMe(){}", encoding="utf-8"
        )

    def test_symbols_indexed_without_full_source(self):
        message = update_project_memory(self.workspace, data_dir=self.data)
        self.assertIn("Projektgedächtnis aktualisiert", message)
        payload = json.loads(_index_path(self.workspace, self.data).read_text())
        self.assertIn("MyApp", payload["files"]["main.py"]["symbols"])
        self.assertIn("repair_project", payload["files"]["main.py"]["symbols"])
        self.assertNotIn(".env", payload["files"])
        self.assertFalse(any("node_modules" in p for p in payload["files"]))
        raw_index = _index_path(self.workspace, self.data).read_text()
        self.assertNotIn("SUPER_SECRET", raw_index)
        self.assertNotIn("return True", raw_index)
        self.assertFalse((self.workspace / "project_memory.json").exists())

    def test_lookup_and_stale_detection_and_refresh(self):
        update_project_memory(self.workspace, data_dir=self.data)
        result = lookup_project_memory(self.workspace, "repair_project", data_dir=self.data)
        self.assertIn("main.py", result)
        self.assertIn("repair_project", result)
        self.assertNotIn("VERALTET", result)
        (self.workspace / "main.py").write_text("def changed_name(): pass\n", encoding="utf-8")
        stale = lookup_project_memory(self.workspace, "repair_project", data_dir=self.data)
        self.assertIn("VERALTET", stale)
        update_project_memory(self.workspace, data_dir=self.data)
        fresh = lookup_project_memory(self.workspace, "changed_name", data_dir=self.data)
        self.assertIn("changed_name", fresh)
        self.assertNotIn("VERALTET", fresh)

    def test_tools_are_declared(self):
        names = {tool["function"]["name"] for tool in tool_schema()}
        self.assertIn("project_memory_lookup", names)
        self.assertIn("project_memory_update", names)


if __name__ == "__main__":
    unittest.main()
