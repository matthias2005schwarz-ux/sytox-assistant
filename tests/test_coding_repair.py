"""Regression tests for self-correcting local coding workflows.

Run in a disposable workspace. Model and failed build output are mocked;
no Qwen3 download or real user project is required.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.agent import Agent
from sytox.actions import Toolkit
from sytox.coding_repair import (
    MAX_REPEATS, diagnostic_excerpt, failure_fingerprint,
    update_failure_state, repair_instruction,
)
from sytox.storage import Store


def tool(name: str, **kwargs):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": kwargs}}]}


class RepairDiagnosticTests(unittest.TestCase):
    def test_failure_fingerprint_ignores_changing_line_numbers_and_duration(self):
        first = "Exit code: 1\nFAILED tests/test_logic.py::test_result - AssertionError\nline 81\n1.1s\n"
        second = "Exit code: 1\nFAILED tests/test_logic.py::test_result - AssertionError\nline 122\n2.4s\n"
        self.assertEqual(failure_fingerprint("run_command", first),
                         failure_fingerprint("run_command", second))
        self.assertNotEqual(failure_fingerprint("run_command", first),
                            failure_fingerprint("run_command",
                                "Exit code: 1\nFAILED tests/test_other.py::test_decode - ValueError\n"))

    def test_three_identical_failures_pause_without_raw_output_in_state(self):
        message = "Exit code: 1\nFAIL: test_login (tests.test_user)\n" + "secret data\n" * 300
        state = {}
        for i in range(MAX_REPEATS):
            state, pause = update_failure_state(state, "run_command", message)
            self.assertEqual(pause, i == MAX_REPEATS - 1)
            self.assertEqual(state["streak"], i + 1)
        self.assertNotIn("secret data", json.dumps(state))
        self.assertLessEqual(len(diagnostic_excerpt(message)), 2200)
        self.assertIn("denselben Test", repair_instruction(
            "run_command", message, state))

    def test_new_failure_resets_streak(self):
        first = "Exit code: 1\nFAILED tests/test_a.py::test_a - AssertionError\n"
        second = "Exit code: 1\nFAILED tests/test_b.py::test_b - ValueError\n"
        state, _ = update_failure_state({}, "run_command", first)
        state, _ = update_failure_state(state, "run_command", first)
        state, stop = update_failure_state(state, "run_command", second)
        self.assertEqual(state["streak"], 1)
        self.assertFalse(stop)


class AgentRepairLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        self.store = Store(self.root / "assistant.sqlite")
        self.cid = self.store.create_chat()
        self.store.add_message(self.cid, "user",
                               "Programmiere offline ein Python-Skript zur Validierung")

    def make_agent(self, responses):
        a = Agent(self.store, "mock", "http://localhost:11434",
                  self.workspace, lambda *_: True, lambda *_: None,
                  threading.Event())
        a.client.chat = MagicMock(side_effect=responses)
        return a

    def test_repeated_failed_tests_pause_after_three_attempts(self):
        failures = [tool("run_command", command=f"python -m pytest tests/test_{part}.py")
                    for part in ("a", "b", "c")]
        agent = self.make_agent(failures)
        sample = "Exit code: 1\nFAILED tests/test_problem.py::test_x - AssertionError\n"
        with patch.object(Toolkit, "call", autospec=True, return_value=sample) as called:
            result = agent.run(self.cid, "until_done")
        self.assertEqual(result["status"], "paused")
        self.assertIn("wiederholt", result["content"])
        self.assertEqual(called.call_count, 3)
        checkpoint = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertEqual(checkpoint["repair_state"]["streak"], 3)
        self.assertNotIn("tests/test_problem.py", json.dumps(checkpoint))
        second_prompt = agent.client.chat.call_args_list[1].args[0]
        self.assertIn("Fehleranker", str(second_prompt))
        self.assertIn("denselben Test", str(second_prompt))

    def test_workflow_success_only_after_real_command_validation(self):
        agent = self.make_agent([
            tool("write_file", path="demo.py", content="print('ok')\n"),
            tool("run_command", command="python -m compileall demo.py"),
            {"role": "assistant", "content": "Die Datei wurde geschrieben und geprüft."},
        ])
        result = agent.run(self.cid, "once")
        self.assertEqual(result["status"], "done", result["content"])
        self.assertTrue((self.workspace / "demo.py").is_file())
        cp = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertEqual(cp["unvalidated_paths"], [])
        self.assertGreaterEqual(cp["passed_checks"], 1)

    def test_unverified_edit_does_not_count_as_completed_work(self):
        agent = self.make_agent([
            tool("write_file", path="not_tested.py", content="print('untested')\n"),
            {"role": "assistant", "content": "Fertig, alles getestet."},
        ])
        result = agent.run(self.cid, "once")
        self.assertEqual(result["status"], "paused")
        self.assertIn("nicht erfolgreich getestet", result["content"])
        cp = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertIn("not_tested.py", cp["unvalidated_paths"])

    def test_repair_state_survives_pause_and_resumption(self):
        first = self.make_agent([
            tool("run_command", command="python -m pytest tests/test_a.py"),
            tool("report_blocker", reason="Später erneut versuchen."),
        ])
        output = "Exit code: 1\nFAILED tests/test_problem.py::test_error - ValueError\n"
        with patch.object(Toolkit, "call", autospec=True, return_value=output):
            initial = first.run(self.cid, "until_done")
        self.assertEqual(initial["status"], "paused")
        restored = self.make_agent([
            tool("run_command", command="python -m pytest tests/test_b.py"),
            tool("report_blocker", reason="Noch offen."),
        ])
        with patch.object(Toolkit, "call", autospec=True, return_value=output):
            again = restored.run(self.cid, task_id=initial["task_id"])
        self.assertEqual(again["status"], "paused")
        cp = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertEqual(cp["repair_state"]["streak"], 2)


if __name__ == "__main__":
    unittest.main()
