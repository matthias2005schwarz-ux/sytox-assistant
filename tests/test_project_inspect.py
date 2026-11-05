"""Regression tests for read-only large-repository navigation."""
import tempfile
import threading
import unittest
from pathlib import Path

from sytox.project_inspect import project_overview, search_project, read_project_lines
from sytox.actions import Toolkit, tool_schema
from sytox.storage import Store


class ProjectInspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "work"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "main.py").write_text(
            "def important_handler():\n    return 42\n", encoding="utf-8")
        (self.root / "tests" / "test_main.py").write_text(
            "def test_handler():\n    assert important_handler()\n", encoding="utf-8")
        (self.root / "package.json").write_text('{"name":"example"}', encoding="utf-8")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "should_not_find.py").write_text(
            "important_handler", encoding="utf-8")
        (self.root / ".env").write_text("important_handler=secret", encoding="utf-8")
        (self.root / "id_rsa").write_text("important_handler private key", encoding="utf-8")

    def test_project_map_detects_source_and_tests_but_skips_dependencies(self):
        result = project_overview(self.root)
        self.assertIn("Python", result)
        self.assertIn("src/main.py", result)
        self.assertIn("tests/test_main.py", result)
        self.assertIn("package.json", result)
        self.assertNotIn("should_not_find.py", result)
        self.assertNotIn("id_rsa", result)

    def test_search_returns_accurate_relative_line_numbers(self):
        result = search_project(self.root, "important_handler")
        self.assertIn("src/main.py:1:", result)
        self.assertIn("tests/test_main.py:2:", result)
        self.assertNotIn("should_not_find.py", result)
        self.assertNotIn("secret", result)
        self.assertNotIn("id_rsa", result)

    def test_search_is_literal_not_a_regular_expression(self):
        (self.root / "src" / "regex.py").write_text("a.*b\n", encoding="utf-8")
        self.assertIn("src/regex.py:1:", search_project(self.root, "a.*b"))
        self.assertIn("keine Treffer", search_project(self.root, "a.+b"))

    def test_search_rejects_invalid_queries(self):
        for query in ("", "x", "z" * 121, None):
            with self.subTest(query=query):
                with self.assertRaises(ValueError):
                    search_project(self.root, query)

    def test_read_specific_lines_and_bounds(self):
        result = read_project_lines(self.root, "src/main.py", 2, 2)
        self.assertIn("2:     return 42", result)
        self.assertNotIn("def important_handler", result)
        with self.assertRaises(ValueError):
            read_project_lines(self.root, "src/main.py", 1, 181)
        with self.assertRaises(ValueError):
            read_project_lines(self.root, "src/main.py", 0, 1)

    def test_cannot_escape_workspace(self):
        for fn, args in (
            (project_overview, ("../",)),
            (search_project, ("some query", "../")),
            (read_project_lines, ("../private.txt",)),
        ):
            with self.subTest(fn=fn.__name__):
                with self.assertRaises(PermissionError):
                    fn(self.root, *args)

    def test_symlink_outside_is_not_scanned(self):
        outside = Path(self.temp.name) / "private.py"
        outside.write_text("important_handler=private", encoding="utf-8")
        link = self.root / "src" / "outside.py"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("Symlink creation unavailable on this Windows runner")
        self.assertNotIn("outside.py", project_overview(self.root))
        self.assertNotIn("outside.py", search_project(self.root, "important_handler"))

    def test_toolkit_exposes_read_only_tools(self):
        store = Store(Path(self.temp.name) / "assistant.db")
        tools = Toolkit(store, self.root, lambda *args: True,
                        threading.Event(), logger=lambda *args: None)
        schema = {tool["function"]["name"] for tool in tool_schema()}
        self.assertTrue({"project_overview", "search_project",
                         "read_file_lines"}.issubset(schema))
        self.assertIn("src/main.py", tools.call("project_overview", {}))
        self.assertIn("src/main.py:1:", tools.call("search_project", {
            "query": "important_handler"}))
        self.assertIn("2:     return 42", tools.call("read_file_lines", {
            "path": "src/main.py", "start_line": 2, "end_line": 2}))
        self.assertEqual(tools.writes, 0)
        tools.close()


if __name__ == "__main__":
    unittest.main()
