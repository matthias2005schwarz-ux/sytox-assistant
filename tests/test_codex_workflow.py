"""Regression tests for larger, checkpointed coding workflows."""
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.actions import Toolkit, tool_schema
from sytox.agent import Agent
from sytox.storage import Store


def tool(name, **kwargs):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": kwargs}}]}


class PatchsetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.store = Store(self.root / "store.sqlite")
        cid = self.store.create_chat()
        self.tools = Toolkit(self.store, self.workspace, lambda *_: True,
                             threading.Event(), cid)
        self.addCleanup(self.tools.close)
        (self.workspace / "first.py").write_text("FIRST = 1\n", encoding="utf-8")
        (self.workspace / "second.py").write_text("SECOND = 1\n", encoding="utf-8")

    def test_schema_describes_structured_batch(self):
        schema = {item["function"]["name"]: item for item in tool_schema()}
        prop = schema["apply_patchset"]["function"]["parameters"]["properties"]["changes"]
        self.assertEqual(prop["type"], "array")
        self.assertEqual(prop["items"]["properties"]["old_text"]["type"], "string")

    def test_batch_updates_multiple_files_and_invalidates_prior_checks(self):
        self.tools.passed_checks = 2
        self.tools.built_artifacts = [{"path": "old.exe", "sha256": "fake"}]
        result = self.tools.call("apply_patchset", {"changes": [
            {"path": "first.py", "old_text": "FIRST = 1", "new_text": "FIRST = 2"},
            {"path": "second.py", "old_text": "SECOND = 1", "new_text": "SECOND = 2"},
        ]})
        self.assertIn("2 Dateien gezielt geändert", result)
        self.assertEqual((self.workspace / "first.py").read_text(encoding="utf-8"), "FIRST = 2\n")
        self.assertEqual((self.workspace / "second.py").read_text(encoding="utf-8"), "SECOND = 2\n")
        self.assertEqual(self.tools.writes, 2)
        self.assertEqual(self.tools.unvalidated_paths, {"first.py", "second.py"})
        self.assertFalse(self.tools.built_artifacts)

    def test_preflight_refuses_partial_edit_on_wrong_sha(self):
        mismatch = "0" * 64
        changes = [
            {"path": "first.py", "old_text": "FIRST = 1", "new_text": "FIRST = 9"},
            {"path": "second.py", "old_text": "SECOND = 1", "new_text": "SECOND = 9",
             "expected_sha256": mismatch},
        ]
        response = self.tools.call("apply_patchset", {"changes": changes})
        self.assertIn("FEHLER", response)
        self.assertIn("FIRST = 1", (self.workspace / "first.py").read_text())
        self.assertIn("SECOND = 1", (self.workspace / "second.py").read_text())
        self.assertEqual(self.tools.writes, 0)
        self.assertEqual(self.tools.unvalidated_paths, set())

    def test_preflight_rejects_duplicate_paths_and_ambiguous_snippets(self):
        changes = [
            {"path": "first.py", "old_text": "FIRST", "new_text": "A"},
            {"path": "first.py", "old_text": "FIRST", "new_text": "B"},
        ]
        self.assertIn("FEHLER", self.tools.call("apply_patchset", {"changes": changes}))
        (self.workspace / "first.py").write_text("same same", encoding="utf-8")
        response = self.tools.call("apply_patchset", {"changes": [
            {"path": "first.py", "old_text": "same", "new_text": "new"}]})
        self.assertIn("FEHLER", response)
        self.assertEqual((self.workspace / "first.py").read_text(), "same same")


class CodingPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "db.sqlite")
        self.cid = self.store.create_chat()
        self.store.add_message(self.cid, "user", "Programmiere ein mehrteiliges Python-Projekt")

    def agent(self, responses):
        agent = Agent(self.store, "mock", "http://unused", str(self.root / "workspace"),
                      lambda *_: True, lambda *_: None, threading.Event())
        agent.client.chat = MagicMock(side_effect=responses)
        return agent

    def test_coding_plan_is_saved_and_restored(self):
        first = self.agent([
            tool("set_coding_plan",
                 steps=["Projekt prüfen", "Module ändern", "Tests ausführen"],
                 test_strategy="Unit-Tests nach jeder Änderung",
                 risks="Bestehende Schnittstellen erhalten"),
            tool("report_blocker", reason="Freigabe zur Fortsetzung nötig."),
        ]).run(self.cid, "until_done")
        self.assertEqual(first["status"], "paused")
        stored = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertEqual(stored["coding_plan"]["steps"][1], "Module ändern")
        resumed = self.agent([
            tool("report_blocker", reason="Pausiert, weil noch keine Umsetzung erfolgte."),
        ])
        result = resumed.run(self.cid, task_id=first["task_id"])
        self.assertEqual(result["status"], "paused")
        prompt = str(resumed.client.chat.call_args_list[0].args[0])
        self.assertIn("Unit-Tests nach jeder Änderung", prompt)
        self.assertIn("Module ändern", prompt)


    def test_read_only_reviewer_runs_with_local_model_after_tests(self):
        agent = Agent(self.store, "mock", "http://localhost:11434",
                      str(self.root / "workspace"),
                      lambda *_: True, lambda *_: None, threading.Event())
        agent.client.chat = MagicMock(side_effect=[
            tool("write_file", path="main.py", content="print(3)\\n"),
            tool("run_command", command="python -m compileall main.py"),
            tool("review_coding_changes"),
            {"role": "assistant", "content": "Review: kein offensichtlicher Syntaxfehler."},
            tool("complete_task", summary="Code geschrieben und geprüft", evidence="compileall 0"),
        ])
        done = agent.run(self.cid, "until_done")
        self.assertEqual(done["status"], "done", done["content"])
        review_request = agent.client.chat.call_args_list[3].args[0]
        self.assertIn("unabhängige SYTOX-Codeprüfer", str(review_request))
        self.assertIn("main.py", str(review_request))
        self.assertIn("print(3)", str(review_request))
        final_request = agent.client.chat.call_args_list[4].args[0]
        self.assertIn("Prüferhinweise", str(final_request))


if __name__ == "__main__":
    unittest.main()
