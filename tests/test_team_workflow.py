"""Regression coverage for local Multi-Agent 2.0 coding workflow."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.team_workflow import CodingTeam, local_model_only, reviewer_request
from sytox.agent import Agent
from sytox.storage import Store


def tool(name, **params):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": params}}]}


class TeamStateTests(unittest.TestCase):
    def test_lifecycle_checkpoint_and_review_invalidated_by_new_edit(self):
        team = CodingTeam()
        self.assertFalse(team.active)
        self.assertTrue(team.start("Plan"))
        self.assertFalse(team.start("Overwrite"))
        team.test_passed(True)
        self.assertTrue(team.review_needed(2))
        team.reviewed(2, "Reviewed")
        self.assertFalse(CodingTeam(team.snapshot()).review_needed(2))
        team.changed()
        self.assertTrue(team.review_needed(3))
        self.assertEqual(team.snapshot()["phase"], "implementation")

    def test_debugger_deduplication_and_bound(self):
        team = CodingTeam()
        team.start("Plan")
        self.assertTrue(team.test_failed("run_command", "NameError"))
        self.assertFalse(team.test_failed("run_command", "NameError"))
        self.assertTrue(team.test_failed("run_command", "TypeError"))
        self.assertTrue(team.test_failed("project_build", "link error"))
        self.assertFalse(team.test_failed("project_build", "new error"))
        self.assertEqual(team.snapshot()["debug_consultations"], 3)

    def test_only_local_model_may_access_private_files(self):
        self.assertTrue(local_model_only("http://127.0.0.1:11434"))
        self.assertTrue(local_model_only("http://[::1]:11434"))
        for url in ("https://localhost:11434", "http://example.test:11434",
                    "http://user:secret@localhost:11434", "http://10.0.0.2:11434"):
            self.assertFalse(local_model_only(url))

    def test_review_cannot_follow_symlink_or_escape_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            (root / "secret.py").write_text("PRIVATE")
            (project / "main.py").write_text("print(2)\n")
            try:
                (project / "link.py").symlink_to(root / "secret.py")
            except OSError:
                # Windows CI may not grant symlink creation to the test account.
                pass
            msg = reviewer_request("Change", "Tests", project,
                                   {"main.py", "link.py", "../secret.py"})
            self.assertIn("print(2)", msg[1]["content"])
            self.assertNotIn("PRIVATE", msg[1]["content"])
            self.assertIn("KEINE Werkzeuge", msg[0]["content"])
            with self.assertRaises(ValueError):
                reviewer_request("Change", "Tests", project, ["missing.py"])


class TeamIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "store.sqlite")
        self.cid = self.store.create_chat()
        self.store.add_message(self.cid, "user", "Programmiere ein Python-Projekt")

    def agent(self, responses, url="http://localhost:11434"):
        agent = Agent(self.store, "mock", url, self.root / "workspace",
                      lambda *_: True, lambda *_: None, threading.Event())
        agent.client.chat = MagicMock(side_effect=responses)
        return agent

    def test_architect_programmer_tests_reviewer_completion(self):
        agent = self.agent([
            tool("start_coding_team"),
            {"role": "assistant", "content": "Architekt: kleine Änderungen"},
            tool("write_file", path="hello.py", content="print(1)\n"),
            tool("run_command", command="python -m compileall hello.py"),
            tool("complete_task", summary="Build done", evidence="compileall"),
            {"role": "assistant", "content": "Reviewer: okay"},
            tool("complete_task", summary="Geprüft", evidence="compileall exit 0"),
        ])
        result = agent.run(self.cid, "until_done")
        self.assertEqual(result["status"], "done", result["content"])
        self.assertEqual(agent.client.chat.call_count, 7)
        self.assertIsNone(agent.client.chat.call_args_list[1].kwargs["tools"])
        self.assertIn("Softwarearchitekt", str(agent.client.chat.call_args_list[1].args[0]))
        self.assertIsNone(agent.client.chat.call_args_list[5].kwargs["tools"])
        self.assertIn("unabhängige", str(agent.client.chat.call_args_list[5].args[0]))
        checkpoint = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertTrue(checkpoint["coding_team"]["active"])
        self.assertEqual(checkpoint["coding_team"]["phase"], "reviewed")

    def test_team_resumes_after_pause(self):
        first = self.agent([
            tool("start_coding_team"),
            {"role": "assistant", "content": "Architekt: Designvorschlag"},
            tool("report_blocker", reason="Pausiert"),
        ]).run(self.cid, "until_done")
        self.assertEqual(first["status"], "paused")
        self.assertTrue(json.loads(self.store.tasks(self.cid)[0]["checkpoint"])[
            "coding_team"]["active"])
        agent = self.agent([
            tool("write_file", path="hello.py", content="print(4)\n"),
            tool("run_command", command="python -m compileall hello.py"),
            tool("complete_task", summary="Checked", evidence="compileall"),
            {"role": "assistant", "content": "Reviewer: okay"},
            tool("complete_task", summary="Done", evidence="compileall"),
        ])
        resumed = agent.run(self.cid, task_id=first["task_id"])
        self.assertEqual(resumed["status"], "done", resumed["content"])
        self.assertIn("Designvorschlag", str(agent.client.chat.call_args_list[0].args[0]))

    def test_debugger_read_only_after_failed_test(self):
        agent = self.agent([
            tool("start_coding_team"),
            {"role": "assistant", "content": "Architekt: Tests"},
            tool("write_file", path="broken.py", content="print((\n"),
            tool("run_command", command="python -m compileall broken.py"),
            {"role": "assistant", "content": "Debugger: close bracket"},
            tool("write_file", path="broken.py", content="print(1)\n"),
            tool("run_command", command="python -m compileall broken.py"),
            tool("complete_task", summary="Syntax checked", evidence="Exit 0"),
            {"role": "assistant", "content": "Reviewer: okay"},
            tool("complete_task", summary="Done", evidence="Exit 0"),
        ])
        result = agent.run(self.cid, "until_done")
        self.assertEqual(result["status"], "done", result["content"])
        debug_request = agent.client.chat.call_args_list[4]
        self.assertIsNone(debug_request.kwargs["tools"])
        self.assertIn("Debugging-Spezialist", str(debug_request.args[0]))
        checkpoint = json.loads(self.store.tasks(self.cid)[0]["checkpoint"])
        self.assertEqual(checkpoint["coding_team"]["debug_consultations"], 1)

    def test_remote_ollama_team_refused(self):
        agent = self.agent([
            tool("start_coding_team"),
            tool("report_blocker", reason="local Ollama required"),
        ], url="http://example.test:11434")
        result = agent.run(self.cid, "until_done")
        self.assertEqual(result["status"], "paused")
        self.assertEqual(agent.client.chat.call_count, 2)
        self.assertFalse(json.loads(self.store.tasks(self.cid)[0]["checkpoint"])[
            "coding_team"]["active"])


if __name__ == "__main__":
    unittest.main()
