"""End-to-end integration contracts for Sytox AI's local model workflow.

No real model, GPU, microphone, screenshot or remote network is used by CI.
A simulated Ollama HTTP stream drives the real Qwen3 client, task orchestrator,
workspace Toolkit and checkpoint storage. These tests deliberately do not
claim to measure real-world model quality or hardware speed.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.agent import Agent, CONTROL_TOOLS
from sytox.model_benchmark import run_local_benchmark
from sytox.model_runtime import ollama_generation_options
from sytox.screen_vision import analyze_screenshot
from sytox.storage import Store
from sytox.tool_protocol import normalize_tool_calls, ToolProtocolError
from sytox.voice_features import VoiceTurnRouter, agent_status_intent, desktop_voice_intent
from sytox.screen_intents import screen_intent as spoken_screen_intent


PNG = bytes.fromhex("89504e470d0a1a0a") + b"synthetic-ui-image"


def tool_reply(name, **arguments):
    # Use JSON-encoded argument objects, as supported by Qwen3/Ollama.
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {
                "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}]}


class FakeOllamaStream:
    def __init__(self, reply, *, metadata=None):
        self.reply = reply
        self.metadata = metadata or {}
        self.ok = True
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self):
        first = {"message": self.reply, "done": False}
        last = {"message": {"role": "assistant", "content": ""},
                "done": True, **self.metadata}
        yield json.dumps(first, ensure_ascii=False).encode("utf-8")
        yield json.dumps(last, ensure_ascii=False).encode("utf-8")

    def close(self):
        return None


class SystemIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.store = Store(self.root / "sytox.sqlite")
        self.chat = self.store.create_chat("Integrationstest")

    def agent(self):
        return Agent(self.store, "qwen3-coder:30b", "http://localhost:11434",
                     str(self.workspace), lambda *_: True, lambda *_: None,
                     threading.Event(), context_tokens=4096)

    def test_qwen3_stream_tools_architect_programmer_tests_reviewer_and_storage(self):
        goal = "Programmiere ein Python-Skript und teste die Ausgabe"
        self.store.add_message(self.chat, "user", goal)
        replies = iter([
            tool_reply("start_coding_team"),
            {"role": "assistant", "content": "Architekt: eine kleine Datei mit Test anlegen."},
            tool_reply("write_file", path="hello.py", content="print(42)\n"),
            tool_reply("run_command", command="python -m compileall hello.py"),
            tool_reply("complete_task", summary="Prüfung abgeschlossen",
                       evidence="compileall erfolgreich"),
            {"role": "assistant", "content": "Reviewer: keine Auffälligkeiten im Quelltext."},
            tool_reply("complete_task", summary="hello.py geschrieben und geprüft",
                       evidence="compileall erfolgreich; Code-Review gelesen"),
        ])
        payloads = []

        def fake_post(url, **kwargs):
            self.assertEqual(url, "http://localhost:11434/api/chat")
            self.assertTrue(kwargs.get("stream"))
            payload = kwargs["json"]
            payloads.append(payload)
            self.assertEqual(payload["model"], "qwen3-coder:30b")
            self.assertEqual(payload["options"]["num_ctx"], 4096)
            return FakeOllamaStream(next(replies))

        with patch("sytox.agent.requests.post", side_effect=fake_post) as posted:
            result = self.agent().run(self.chat, "until_done")

        self.assertEqual(result["status"], "done", result["content"])
        self.assertEqual(self.workspace.joinpath("hello.py").read_text(encoding="utf-8"),
                         "print(42)\n")
        self.assertEqual(len(payloads), 7)
        self.assertEqual(posted.call_count, 7)
        # The architect and reviewer receive NO tool schema or filesystem powers.
        for index in (1, 5):
            self.assertNotIn("tools", payloads[index])
        # Only the principal programmer is offered the validated tool catalog.
        self.assertTrue(any(spec["function"]["name"] == "write_file"
                            for spec in payloads[2]["tools"]))
        self.assertIn("Reviewer: keine Auffälligkeiten",
                      str(payloads[6]["messages"]))
        checkpoint = json.loads(self.store.tasks(self.chat)[0]["checkpoint"])
        self.assertTrue(checkpoint["coding_team"]["active"])
        self.assertEqual(checkpoint["coding_team"]["phase"], "reviewed")
        self.assertEqual(checkpoint["unvalidated_paths"], [])
        self.assertGreaterEqual(checkpoint["passed_checks"], 1)
        self.assertEqual(checkpoint["coding_team"]["last_reviewed_writes"], 1)
        self.assertEqual(self.store.messages(self.chat)[-1]["role"], "assistant")

    def test_resume_workflow_retains_team_and_approvals(self):
        self.store.add_message(self.chat, "user", "Programmiere ein Projekt")
        stages = [
            tool_reply("start_coding_team"),
            {"role": "assistant", "content": "Architekt: sicher testen."},
            tool_reply("report_blocker", reason="Pausiert für den Integrationstest."),
        ]
        with patch("sytox.agent.requests.post",
                   side_effect=lambda _url, **_kw: FakeOllamaStream(stages.pop(0))):
            paused = self.agent().run(self.chat, "until_done")
        self.assertEqual(paused["status"], "paused")
        stored = json.loads(self.store.tasks(self.chat)[0]["checkpoint"])
        self.assertTrue(stored["coding_team"]["active"])

        stages = [
            tool_reply("write_file", path="resume.py", content="print('resume')\n"),
            tool_reply("run_command", command="python -m compileall resume.py"),
            tool_reply("complete_task", summary="Getestet", evidence="compileall"),
            {"role": "assistant", "content": "Reviewer: in Ordnung."},
            tool_reply("complete_task", summary="Fortsetzung fertig", evidence="compileall"),
        ]
        captured = []
        def resume_post(_url, **kwargs):
            captured.append(kwargs["json"])
            return FakeOllamaStream(stages.pop(0))
        # Simulate reopening the program: a completely new Agent, same Store.
        with patch("sytox.agent.requests.post", side_effect=resume_post):
            finished = self.agent().run(self.chat, task_id=paused["task_id"])
        self.assertEqual(finished["status"], "done", finished["content"])
        self.assertEqual(len(captured), 5)
        self.assertIn("sicher testen", str(captured[0]["messages"]))
        self.assertNotIn("tools", captured[3])
        self.assertTrue(self.workspace.joinpath("resume.py").exists())

    def test_vision_and_benchmark_use_distinct_models_and_only_loopback(self):
        requests_sent = []

        def fake_post(url, **kwargs):
            self.assertEqual(url, "http://localhost:11434/api/chat")
            self.assertIs(kwargs["allow_redirects"], False)
            payload = kwargs["json"]
            requests_sent.append(payload)
            if payload["model"] == "qwen3-vl:4b":
                return FakeOllamaStream({"role": "assistant",
                                         "content": "Ein lokales Testfenster."})
            return FakeOllamaStream({"role": "assistant", "content": "Antwort"},
                metadata={"eval_count": 12, "eval_duration": 300_000_000,
                          "load_duration": 800_000_000})

        answer = analyze_screenshot(PNG, "Beschreibe diesen Test",
                                    "http://localhost:11434", "qwen3-vl:4b",
                                    post=fake_post)
        report = run_local_benchmark("http://localhost:11434", "qwen3-coder:30b",
                        context_tokens=4096, tasks=[("Text", "Was ist ein Test?")],
                        post=fake_post)
        self.assertEqual(answer, "Ein lokales Testfenster.")
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(report["samples"][0]["tokens_per_second"], 40)
        self.assertEqual([p["model"] for p in requests_sent],
                         ["qwen3-vl:4b", "qwen3-coder:30b"])
        self.assertIn("images", requests_sent[0]["messages"][0])
        self.assertNotIn("images", requests_sent[1]["messages"][0])
        self.assertNotIn("tools", requests_sent[0])
        self.assertNotIn("tools", requests_sent[1])
        self.assertEqual(requests_sent[1]["options"]["num_predict"], 96)
        self.assertGreater(ollama_generation_options("qwen3-coder:30b", 4096)["num_predict"], 96)

    def test_voice_screen_status_and_pc_control_intents_do_not_cross(self):
        router = VoiceTurnRouter(require_wake=True, follow_up_seconds=25)
        self.assertIsNone(router.command_for("Öffne Editor"))
        command = router.command_for("Hey Sytox, wie weit bist du?")
        self.assertEqual(command, "wie weit bist du")
        self.assertEqual(agent_status_intent(command), "status")
        self.assertIsNone(desktop_voice_intent(command))
        self.assertIsNone(spoken_screen_intent(command))
        self.assertEqual(spoken_screen_intent(
            router.command_for("Schau auf meinen Bildschirm")), "start")
        self.assertEqual(spoken_screen_intent(
            router.command_for("Verlass meinen Bildschirm")), "stop")

    def test_invalid_qwen_tool_batch_is_rejected_atomically(self):
        valid = {"function": {"name": "record_progress", "arguments":
            {"completed": "Lesen", "next_step": "Testen", "evidence": "keine"}}}
        malicious = {"function": {"name": "write_file",
                                    "arguments": {"path": "../outside.py", "content": "x"}}}
        # This tool is not in CONTROL_TOOLS, so the complete batch is invalid.
        with self.assertRaises(ToolProtocolError):
            normalize_tool_calls([valid, malicious], CONTROL_TOOLS)
        self.assertFalse((self.root / "outside.py").exists())
        normalized = normalize_tool_calls([{"function": {
            "name": "start_coding_team", "arguments": "{}"}}], CONTROL_TOOLS)
        self.assertEqual(normalized[0]["function"]["arguments"], {})


if __name__ == "__main__":
    unittest.main()
