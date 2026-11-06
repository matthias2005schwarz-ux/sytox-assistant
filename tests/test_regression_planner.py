"""Regression planner checks that suggest paths without executing code."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.actions import Toolkit, tool_schema
from sytox.regression_planner import plan_regression_tests
from sytox.storage import Store


class RegressionPlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / "repo"
        self.project.mkdir()
        (self.project / "src").mkdir()
        (self.project / "tests").mkdir()
        (self.project / "src" / "payments.py").write_text(
            "def refund(): return 1\n", encoding="utf-8")
        (self.project / "tests" / "test_payments.py").write_text(
            "def test_refund(): assert True\n", encoding="utf-8")

    def test_existing_python_tests_and_syntax_command_suggested(self):
        with patch("subprocess.run", side_effect=AssertionError(
                "test discovery must not execute anything")):
            report = plan_regression_tests(self.project, ["src/payments.py"])
        self.assertIn("tests/test_payments.py", report)
        self.assertIn("python -m pytest tests/test_payments.py", report)
        self.assertIn("python -m compileall src/payments.py", report)
        self.assertIn("keine Tests ausgeführt", report)

    def test_nonexistent_and_outside_files_cannot_be_used(self):
        outside = self.root / "secret.py"
        outside.write_text("def private(): pass\n")
        report = plan_regression_tests(
            self.project, ["../secret.py", "/tmp/secret.py", "src/missing.py"])
        self.assertIn("Keine existierenden", report)
        self.assertNotIn("private", report)

    def test_skips_symlink_even_when_it_looks_like_code(self):
        outside = self.root / "secret.py"
        outside.write_text("secret = 1\n")
        link = self.project / "src" / "other.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            return  # unprivileged Windows runner may prohibit symlinks
        report = plan_regression_tests(self.project, ["src/other.py"])
        self.assertIn("Keine existierenden", report)

    def test_js_ts_go_rust_and_csharp_detection(self):
        files = {
            "ui.ts": "export const value = 1;",
            "ui.test.ts": "test('ok', () => {});",
            "main.go": "package main\n",
            "lib.rs": "pub fn demo() {}",
            "app.cs": "class App {}",
        }
        for name, source in files.items():
            (self.project / name).write_text(source)
        for project_file in ("go.mod", "Cargo.toml", "App.csproj"):
            (self.project / project_file).write_text("project metadata")
        result = plan_regression_tests(self.project, [
            "ui.ts", "main.go", "lib.rs", "app.cs"])
        self.assertIn("ui.test.ts", result)
        self.assertIn("go test ./...", result)
        self.assertIn("cargo test", result)
        self.assertIn("dotnet test", result)
        self.assertNotIn("Tests bestanden", result)

    def test_agent_tool_returns_suggestion_without_executing_tests(self):
        store = Store(self.root / "store.sqlite")
        chat = store.create_chat()
        tk = Toolkit(store, self.project, lambda *_: True,
                     threading.Event(), chat)
        self.addCleanup(tk.close)
        tk.modified_paths.add("src/payments.py")
        schema = {item["function"]["name"] for item in tool_schema()}
        self.assertIn("suggest_regression_tests", schema)
        with patch("subprocess.run", side_effect=AssertionError(
                "read-only tool must never run tests")):
            result = tk.call("suggest_regression_tests", {})
        self.assertIn("tests/test_payments.py", result)


if __name__ == "__main__":
    unittest.main()
