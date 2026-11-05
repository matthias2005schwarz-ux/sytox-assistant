"""Offline checks: coding help must be useful, limited, and privacy preserving."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.agent import Agent
from sytox.coding_research import (
    coding_research_allowed, coding_uncertain, failed_coding_tool,
    public_coding_query,
)
from sytox.storage import Store


def tool(name, **kwargs):
    return {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": name, "arguments": kwargs}}]}


class CodingResearchTests(unittest.TestCase):
    def test_query_never_includes_private_content(self):
        private = ("secret_password_567 private-team-project "
                   "C:\\Users\\Alice\\Documents\\secret-project\\main.py "
                   "https://private.example/hidden")
        query = public_coding_query("Programmiere Python " + private,
                                    "SyntaxError: " + private + " line 42")
        self.assertIn("Python", query)
        self.assertIn("syntax parser error", query)
        for token in ("secret", "Alice", "private.example", "Users", "main.py"):
            self.assertNotIn(token, query)
        self.assertLessEqual(len(query), 150)

    def test_csharp_and_cpp_have_stable_public_queries(self):
        self.assertTrue(public_coding_query("C++ Anwendung").startswith("C++"))
        self.assertTrue(public_coding_query("C# Anwendung").startswith("C#"))
        self.assertIn("CS0103", public_coding_query(
            "C# Programm", "error CS0103: The name is missing"))

    def test_uncertainty_and_failure_detection(self):
        self.assertTrue(coding_uncertain("Ich weiß nicht, wie ich das programmieren soll"))
        self.assertTrue(coding_uncertain("I don't know how to implement this"))
        self.assertFalse(coding_uncertain("Test fehlt, ich programmiere weiter."))
        self.assertTrue(failed_coding_tool("run_command", "Exit code: 1\nSyntaxError: ..."))
        self.assertTrue(failed_coding_tool("project_build", "FEHLER RuntimeError: compiler"))
        self.assertFalse(failed_coding_tool("run_command", "Exit code: 0\nsuccess"))
        self.assertFalse(failed_coding_tool("run_command", "FEHLER Denied: no approval"))
        self.assertFalse(failed_coding_tool("read_file", "FEHLER ValueError: missing"))

    def test_offline_requests_are_respected(self):
        self.assertFalse(coding_research_allowed("Programmiere Python ohne Internet"))
        self.assertFalse(coding_research_allowed("Programmiere offline"))
        self.assertFalse(coding_research_allowed("Bitte nicht im Internet suchen"))
        self.assertTrue(coding_research_allowed("Programmiere ein Python-Plugin"))


class CodingResearchAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "assistant.db")
        self.chat_id = self.store.create_chat("Coding tests")

    def agent(self, goal, sequence):
        self.store.add_message(self.chat_id, "user", goal)
        agent = Agent(self.store, "mock", "http://unused",
                      str(self.root / "project"), lambda *args: True,
                      lambda *args: None, threading.Event())
        agent.client.chat = MagicMock(side_effect=sequence)
        return agent

    @staticmethod
    def fake_results(*args, **kwargs):
        return [{"title": "Python documentation", "url": "https://docs.python.org/3/",
                 "snippet": "Review syntax errors and retry tests."}]

    def test_failed_test_researches_then_fixes_and_retests(self):
        agent = self.agent("Programmiere Python", [
            tool("write_file", path="main.py", content="def broken(:\n"),
            tool("run_command", command="python -m compileall main.py"),
            tool("replace_in_file", path="main.py",
                 old_text="def broken(:", new_text='print("hello")'),
            tool("run_command", command="python -m compileall main.py"),
            tool("complete_task", summary="Code corrected", evidence="compileall"),
        ])
        with patch("sytox.agent.search_web", side_effect=self.fake_results) as search:
            result = agent.run(self.chat_id, "until_done")
        self.assertEqual(result["status"], "done", result["content"])
        search.assert_called_once()
        query = search.call_args.args[0]
        self.assertIn("Python", query)
        self.assertIn("syntax parser error", query)
        self.assertNotIn("broken(", query)
        self.assertIn('print("hello")', (self.root / "project" / "main.py").read_text())
        model_messages = agent.client.chat.call_args_list[2].args[0]
        self.assertIn("https://docs.python.org/3/", str(model_messages))
        checkpoint = json.loads(self.store.tasks(self.chat_id)[0]["checkpoint"])
        self.assertEqual(len(checkpoint["coding_research_queries"]), 1)

    def test_offline_does_not_auto_search_after_failure(self):
        agent = self.agent("Programmiere Python ohne Internet", [
            tool("write_file", path="main.py", content="print((\n"),
            tool("run_command", command="python -m compileall main.py"),
            tool("report_blocker", reason="Die Syntax muss korrigiert werden."),
        ])
        with patch("sytox.agent.search_web") as search:
            result = agent.run(self.chat_id, "until_done")
        self.assertEqual(result["status"], "paused")
        search.assert_not_called()

    def test_unsure_text_triggers_help_without_raw_goal(self):
        agent = self.agent(
            "Programmiere Python GUI für internes Projekt mit PASSCODE_DO_NOT_LEAK", [
                {"role": "assistant", "content": "Ich weiß nicht, wie ich das programmieren soll."},
                tool("write_file", path="main.py", content='print("ok")\n'),
                tool("run_command", command="python -m compileall main.py"),
                tool("complete_task", summary="finished", evidence="compileall"),
            ])
        with patch("sytox.agent.search_web", side_effect=self.fake_results) as search:
            result = agent.run(self.chat_id, "until_done")
        self.assertEqual(result["status"], "done", result["content"])
        search.assert_called_once()
        self.assertNotIn("PASSCODE", search.call_args.args[0])

    def test_uncertain_blocker_researches_before_pausing(self):
        agent = self.agent("Programmiere Python GUI", [
            tool("report_blocker", reason="Ich weiß nicht, wie ich die GUI programmieren soll."),
            tool("write_file", path="main.py", content="print('ok')\n"),
            tool("run_command", command="python -m compileall main.py"),
            tool("complete_task", summary="ok", evidence="compileall"),
        ])
        with patch("sytox.agent.search_web", side_effect=self.fake_results) as search:
            result = agent.run(self.chat_id, "until_done")
        self.assertEqual(result["status"], "done", result["content"])
        search.assert_called_once()

    def test_permission_denial_does_not_trigger_research(self):
        agent = self.agent("Programmiere Python", [
            tool("report_blocker", reason="Erforderliche Freigabe verweigert."),
        ])
        with patch("sytox.agent.search_web") as search:
            result = agent.run(self.chat_id, "until_done")
        self.assertEqual(result["status"], "paused")
        search.assert_not_called()

    def test_unavailable_web_does_not_claim_success(self):
        agent = self.agent("Programmiere Python", [
            {"role": "assistant", "content": "Ich weiß nicht, wie ich das programmieren soll."},
            tool("report_blocker", reason="Ich weiß nicht weiter."),
        ])
        with patch("sytox.agent.search_web", return_value=[]) as search:
            result = agent.run(self.chat_id, "until_done")
        self.assertEqual(result["status"], "paused")
        search.assert_called_once()
        self.assertNotIn("erfolgreich recherchiert", result["content"].lower())


if __name__ == "__main__":
    unittest.main()
