"""Deterministic tests for task-relevant coding context and safe truncation."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.context_planner import (
    rank_project_files, project_focus_map, build_context_bundle,
)
from sytox.project_memory import update_project_memory, _read_index
from sytox.model_runtime import (
    compact_agent_history, history_character_budget,
)
from sytox.actions import tool_schema, Toolkit
from sytox.storage import Store
import threading


class FocusedCodeContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.data = self.root / "local_index"
        (self.workspace / "payments.py").write_text(
            "import decimal\n\nclass PaymentProcessor:\n"
            "    def refund_order(self, order_id):\n"
            "        amount = decimal.Decimal('5')\n"
            "        return amount\n", encoding="utf-8")
        (self.workspace / "storage.py").write_text(
            "class CacheManager:\n    pass\n", encoding="utf-8")
        (self.workspace / "test_payments.py").write_text(
            "from payments import PaymentProcessor\n\n"
            "def test_refund_order():\n"
            "    assert PaymentProcessor().refund_order(1)\n", encoding="utf-8")
        (self.workspace / ".env").write_text(
            "API_KEY=SUPER_SECRET_NEVER_INDEX\n", encoding="utf-8")
        (self.workspace / "credentials.json").write_text(
            '{"token": "PRIVATE"}', encoding="utf-8")
        (self.workspace / "node_modules").mkdir()
        (self.workspace / "node_modules" / "bad.py").write_text(
            "def dangerous(): pass", encoding="utf-8")
        update_project_memory(self.workspace, data_dir=self.data)

    def test_relevance_ranking_prefers_task_symbols(self):
        index = _read_index(self.workspace, self.data)
        ranked = rank_project_files(index, "Fix refund_order in PaymentProcessor")
        self.assertEqual(ranked[0]["path"], "payments.py")
        self.assertIn("PaymentProcessor", project_focus_map(
            self.workspace, "PaymentProcessor", data_dir=self.data))
        self.assertNotIn("storage.py", build_context_bundle(
            self.workspace, "refund_order", data_dir=self.data, max_files=2))

    def test_bundle_contains_bounded_line_numbers_and_no_secret_files(self):
        result = build_context_bundle(
            self.workspace, "refund_order", data_dir=self.data,
            max_chars=5000, max_files=3)
        self.assertIn("DATEI payments.py", result)
        self.assertIn("4:     def refund_order", result)
        self.assertIn("DATEI test_payments.py", result)
        self.assertIn("untrusted", result.casefold().replace("unvertraute", "untrusted"))
        self.assertNotIn("SUPER_SECRET_NEVER_INDEX", result)
        self.assertNotIn("credentials.json", result)
        self.assertNotIn("node_modules", result)
        self.assertLessEqual(len(result), 5000)

    def test_stale_source_never_appears_in_read_bundle(self):
        (self.workspace / "payments.py").write_text(
            "class PaymentProcessor:\n    def refund_order(self):\n"
            "        return 'CHANGED_SINCE_INDEX'\n", encoding="utf-8")
        old = build_context_bundle(
            self.workspace, "PaymentProcessor", data_dir=self.data)
        self.assertNotIn("CHANGED_SINCE_INDEX", old)
        update_project_memory(self.workspace, data_dir=self.data)
        new = build_context_bundle(
            self.workspace, "PaymentProcessor", data_dir=self.data)
        self.assertIn("CHANGED_SINCE_INDEX", new)

    def test_hard_budget_limits_large_code(self):
        (self.workspace / "payments.py").write_text(
            "class PaymentProcessor:\n" +
            "\n".join(f"    def refund_{i}(self): pass" for i in range(2400)),
            encoding="utf-8",
        )
        update_project_memory(self.workspace, data_dir=self.data)
        result = build_context_bundle(
            self.workspace, "PaymentProcessor", max_chars=2800, max_files=2,
            data_dir=self.data)
        self.assertLessEqual(len(result), 2800)
        self.assertIn("DATEI payments.py", result)

    def test_index_does_not_include_symlinks_or_sensitive_folders(self):
        result = build_context_bundle(
            self.workspace, "dangerous", data_dir=self.data)
        self.assertNotIn("bad.py", result)
        private = self.root / "secret.py"
        private.write_text("secret_marker", encoding="utf-8")
        link = self.workspace / "linked.py"
        try:
            link.symlink_to(private)
        except (OSError, NotImplementedError):
            return  # Windows CI might prohibit unprivileged symlink creation.
        update_project_memory(self.workspace, data_dir=self.data)
        self.assertNotIn("linked.py", project_focus_map(
            self.workspace, "secret_marker", data_dir=self.data))

    def test_invalid_requests_and_tool_declaration(self):
        with self.assertRaises(ValueError):
            build_context_bundle(self.workspace, "a", data_dir=self.data)
        with self.assertRaises(ValueError):
            build_context_bundle(self.workspace, "refund", max_chars=True,
                                 data_dir=self.data)
        schema = {x["function"]["name"]: x for x in tool_schema()}
        self.assertIn("project_context_bundle", schema)
        tool = schema["project_context_bundle"]["function"]["parameters"]
        self.assertEqual(tool["required"], ["query"])

    def test_agent_receives_file_focus_without_full_source_text(self):
        from sytox.agent import Agent
        store = Store(self.data / "agent.sqlite")
        chat = store.create_chat()
        store.add_message(chat, "user", "Programmiere PaymentProcessor refund_order")
        agent = Agent(store, "qwen3-coder:30b", "http://localhost:11434",
                      self.workspace, lambda *_: True,
                      lambda *_: None, threading.Event())
        agent.client.chat = MagicMock(return_value={
            "role": "assistant", "content": "Ich muss zuerst den aktuellen Code prüfen."
        })
        with patch("sytox.project_memory.default_data_dir", return_value=self.data):
            agent.run(chat, "once")
        sent = agent.client.chat.call_args.args[0]
        prompt = sent[0]["content"]
        self.assertIn("Priorisierter Projektfokus", prompt)
        self.assertIn("payments.py", prompt)
        self.assertNotIn("return amount", prompt)

    def test_tool_uses_existing_workspace_without_saving_code(self):
        store = Store(self.data / "assistant.sqlite")
        toolkit = Toolkit(store, self.workspace, lambda *_: True, threading.Event())
        try:
            # The production tool uses default_data_dir; override only the
            # index location with an isolated temporary directory.
            with patch("sytox.project_memory.default_data_dir",
                       return_value=self.data):
                result = toolkit.call("project_context_bundle", {
                    "query": "PaymentProcessor", "max_chars": 2600,
                    "max_files": 2})
            self.assertIn("DATEI payments.py", result)
            self.assertLessEqual(len(result), 2600)
            self.assertFalse((self.workspace / "project_context.json").exists())
        finally:
            toolkit.close()


class ContextBudgetTests(unittest.TestCase):
    def test_model_context_budget_scales_but_is_not_usage_limit(self):
        small = history_character_budget("qwen2.5-coder:7b")
        large = history_character_budget("qwen3-coder:30b")
        self.assertGreater(large, small)
        self.assertLessEqual(history_character_budget("qwen3-coder:30b", 32768),
                             54_000)

    def test_compacts_oversized_tool_output_even_under_message_count_limit(self):
        messages = [{"role": "system", "content": "SYSTEM SAFETY"}]
        for i in range(8):
            messages.extend([
                {"role": "assistant", "content": "", "tool_calls": [{
                    "function": {"name": "read_file_lines", "arguments": {
                        "path": f"source_{i}.py", "start_line": 1,
                        "end_line": 100,
                    }},
                }]},
                {"role": "tool", "tool_name": "read_file_lines",
                 "content": "X" * 9000 + f"\nLAST_TEST_{i}: OK"},
            ])
        cp = {
            "last_result": "run_command: tests green",
            "coding_plan": {"steps": ["finden", "patchen", "testen"]},
            "progress_notes": [{"next_step": "Fix in solver.py"}],
            "modified_paths": ["solver.py"],
            "unvalidated_paths": ["needs_test.py"],
            "passed_checks": 3,
        }
        result = compact_agent_history(
            messages, "Plugin implementieren", cp, max_chars=6500)
        self.assertEqual(result[0]["content"], "SYSTEM SAFETY")
        self.assertIn("Plugin implementieren", result[1]["content"])
        self.assertIn("needs_test.py", result[1]["content"])
        self.assertIn("solver.py", result[1]["content"])
        self.assertNotEqual(result[2]["role"], "tool")
        self.assertIn("LAST_TEST_7: OK", str(result))
        self.assertLessEqual(sum(len(str(m)) for m in result), 7000)
        for i, msg in enumerate(result[2:], start=2):
            if msg["role"] == "tool":
                self.assertEqual(result[i - 1]["role"], "assistant")

    def test_short_messages_preserved_by_identity(self):
        messages = [{"role": "system", "content": "rules"},
                    {"role": "user", "content": "Hallo"}]
        self.assertIs(compact_agent_history(
            messages, "Hallo", max_chars=3000), messages)


if __name__ == "__main__":
    unittest.main()
