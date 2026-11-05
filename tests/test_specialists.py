"""Read-only specialist roles do not acquire the main agent's tools."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.specialists import specialist_messages, specialist_summary
from sytox.agent import CONTROL_TOOLS, Agent
from sytox.storage import Store


class SpecialistTests(unittest.TestCase):
    def test_roles_are_isolated_advisory_personas(self):
        for role in ("architect", "debugger"):
            with self.subTest(role=role):
                msgs = specialist_messages(role, "Neue App", "Fehlerquelle")
                self.assertEqual(msgs[0]["role"], "system")
                self.assertIn("keine Werkzeuge", msgs[0]["content"])
                self.assertIn("Fehlerquelle", msgs[1]["content"])
                self.assertNotIn("tool_calls", str(msgs))
        with self.assertRaises(ValueError):
            specialist_messages("superuser", "test")
        self.assertIn("unverifiziert", specialist_summary("architect", {"content": "Plan"}))

    def test_specialist_tool_runs_without_tool_permissions(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        store = Store(root / "assistant.sqlite")
        cid = store.create_chat()
        store.add_message(cid, "user", "Programmiere eine Anwendung")
        agent = Agent(store, "mock", "http://localhost:11434", root / "workspace",
                      lambda *_: True, lambda *_: None, threading.Event())
        response = lambda name, **args: {
            "role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": args}}]
        }
        agent.client.chat = MagicMock(side_effect=[
            response("consult_specialist", role="architect", details="Modular aufbauen"),
            {"role": "assistant", "content": "Zuerst Module und Tests prüfen."},
            response("report_blocker", reason="Tests noch nicht ausgeführt."),
        ])
        result = agent.run(cid, "until_done")
        self.assertEqual(result["status"], "paused")
        calls = agent.client.chat.call_args_list
        self.assertIn("consult_specialist", str(calls[0].kwargs["tools"]))
        self.assertIsNone(calls[1].kwargs["tools"])
        self.assertIn("Softwarearchitekt", str(calls[1].args[0]))
        self.assertIn("unverifiziert", str(calls[2].args[0]))
        self.assertIn("consult_specialist",
                      {x["function"]["name"] for x in CONTROL_TOOLS})


if __name__ == "__main__":
    unittest.main()
