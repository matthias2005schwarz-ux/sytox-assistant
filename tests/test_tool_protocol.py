"""Qwen3-Coder structured Ollama tool-call regression tests.

These tests are isolated: no Ollama download, network, native Windows action or
user project is needed. All tool calls run only in a disposable workspace.
"""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.actions import tool_schema
from sytox.agent import Agent
from sytox.storage import Store
from sytox.tool_protocol import (
    MAX_CALLS_PER_TURN, ToolProtocolError, normalize_tool_calls,
)


def proposed(name: str, args, *, index=None) -> dict:
    function = {"name": name, "arguments": args}
    if index is not None:
        function["index"] = index
    return {"function": function}


def assistant_tools(*calls) -> dict:
    return {"role": "assistant", "content": "", "tool_calls": list(calls)}


class ToolProtocolTests(unittest.TestCase):
    def setUp(self):
        self.schemas = tool_schema()

    def test_qwen3_json_string_arguments_are_decoded(self):
        call = proposed("write_file",
                        '{"path":"src/app.py","content":"print(42)\\n"}', index=0)
        result = normalize_tool_calls([call], self.schemas)
        self.assertEqual(result[0]["function"]["name"], "write_file")
        self.assertEqual(result[0]["function"]["arguments"]["content"], "print(42)\n")
        self.assertEqual(result[0]["function"]["index"], 0)

    def test_multiple_tools_preserve_order(self):
        calls = [
            proposed("write_file", {"path": "a.py", "content": "A"}),
            proposed("write_file", {"path": "b.py", "content": "B"}),
        ]
        result = normalize_tool_calls(calls, self.schemas)
        self.assertEqual([c["function"]["arguments"]["path"] for c in result],
                         ["a.py", "b.py"])

    def test_reject_ambiguous_or_unknown_functions(self):
        for calls in (
            [proposed("execute_arbitrary_command", {})],
            [{"function": {"arguments": {}}}],
            [{"not_function": {"name": "write_file"}}],
            [proposed("write_file", "{}")],
            [proposed("write_file", {"path": "x", "content": "a", "extra": True})],
            [proposed("pc_click", {"x": "100", "y": 20})],
            [proposed("pc_click", {"x": True, "y": 20})],
            [proposed("write_file", "INVALID JSON")],
            [proposed("write_file", '["not", "an", "object"]')],
            [proposed("write_file", ["not", "an", "object"])],
        ):
            with self.subTest(calls=str(calls)[:100]), self.assertRaises(ToolProtocolError):
                normalize_tool_calls(calls, self.schemas)

    def test_nested_patchset_must_have_all_required_fields(self):
        partial = [{"path": "a.py", "old_text": "x"}]
        with self.assertRaisesRegex(ToolProtocolError, "new_text"):
            normalize_tool_calls(
                [proposed("apply_patchset", {"changes": partial})], self.schemas)

    def test_oversized_batch_is_rejected_atomically(self):
        payload = [proposed("write_file", {"path": f"{i}.py", "content": "x"})
                   for i in range(MAX_CALLS_PER_TURN + 1)]
        with self.assertRaisesRegex(ToolProtocolError, "Zu viele"):
            normalize_tool_calls(payload, self.schemas)
        with self.assertRaises(ToolProtocolError):
            normalize_tool_calls(
                [proposed("write_file",
                          {"path": "x", "content": "x" * 150_000})], self.schemas)


class AgentToolProtocolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.workspace = self.dir / "workspace"
        self.db = Store(self.dir / "assistant.sqlite")
        self.cid = self.db.create_chat()
        self.db.add_message(self.cid, "user", "Schreibe ein Python-Skript")

    def agent(self, replies):
        logger = MagicMock()
        agent = Agent(self.db, "mock", "http://localhost:11434",
                      self.workspace, lambda *_: True, logger, threading.Event())
        agent.client.chat = MagicMock(side_effect=replies)
        return agent

    def test_malformed_arguments_are_not_executed_then_corrected(self):
        seen = []
        def first(*_a, **_k):
            return assistant_tools(
                proposed("write_file", '{"path":"app.py","content":'))
        def second(*_a, **_k):
            seen.append((self.workspace / "app.py").exists())
            return assistant_tools(
                proposed("write_file", {"path": "app.py", "content": "print(42)\n"}))
        agent = self.agent([first, second, {"role": "assistant", "content": "Gespeichert."}])
        # MagicMock side_effect iterables containing functions return the
        # function itself, so use an explicit dispatcher instead.
        outputs = [
            first(None), second(None),
            {"role": "assistant", "content": "Gespeichert."},
        ]
        agent.client.chat.side_effect = outputs
        result = agent.run(self.cid, "once")
        self.assertEqual(result["status"], "done")
        self.assertEqual(seen, [False])
        self.assertEqual((self.workspace / "app.py").read_text(), "print(42)\n")
        self.assertEqual(agent.client.chat.call_count, 3)
        messages = agent.client.chat.call_args.args[0]
        self.assertTrue(any("vor Ausführung abgelehnt" in m.get("content", "")
                            for m in messages if m["role"] == "user"))

    def test_three_invalid_turns_pause_with_no_side_effect(self):
        batch = assistant_tools(
            proposed("write_file",
                     {"path": "secret.py", "content": "private", "unexpected": "bad"}))
        agent = self.agent([batch, batch, batch])
        result = agent.run(self.cid, "until_done")
        self.assertEqual(result["status"], "paused")
        self.assertIn("dreimal", result["content"])
        self.assertFalse((self.workspace / "secret.py").exists())
        self.assertEqual(agent.client.chat.call_count, 3)

    def test_nine_tools_never_partially_execute(self):
        large = assistant_tools(*[
            proposed("write_file", {"path": f"{i}.py", "content": "print(1)"})
            for i in range(9)
        ])
        agent = self.agent([large, {"role": "assistant", "content": "Nicht ausgeführt."}])
        result = agent.run(self.cid, "once")
        self.assertEqual(result["status"], "paused")
        self.assertIn("nicht ausgeführt", result["content"].lower())
        self.assertEqual(list(self.workspace.glob("*.py")), [])

    def test_valid_batch_executes_all_and_returns_results_to_model(self):
        calls = assistant_tools(
            proposed("write_file", {"path": "a.py", "content": "print(1)\n"}),
            proposed("write_file", {"path": "b.py", "content": "print(2)\n"}),
        )
        agent = self.agent([calls, {"role": "assistant", "content": "Beide gespeichert."}])
        self.assertEqual(agent.run(self.cid, "once")["status"], "done")
        self.assertTrue((self.workspace / "a.py").is_file())
        self.assertTrue((self.workspace / "b.py").is_file())
        messages = agent.client.chat.call_args.args[0]
        self.assertEqual([m["tool_name"] for m in messages if m["role"] == "tool"],
                         ["write_file", "write_file"])



class OllamaStreamTests(unittest.TestCase):
    def test_stream_collects_tool_calls_from_separate_chunks(self):
        from unittest.mock import patch
        from sytox.agent import OllamaClient
        frames = [
            {"message": {"content": "Checking...", "tool_calls": [
                proposed("project_overview", {"path": "."})]}, "done": False},
            {"message": {"content": "", "tool_calls": [
                proposed("project_memory_lookup", {"query": "main"})]}, "done": False},
            {"message": {}, "done": True, "done_reason": "stop"},
        ]
        class Response:
            ok = True
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def iter_lines(self):
                return iter(json.dumps(x).encode() for x in frames)
        client = OllamaClient(model="qwen3-coder:30b")
        with patch("sytox.agent.requests.post", return_value=Response()):
            result = client.chat([{"role": "user", "content": "Arbeite"}],
                                 tools=tool_schema())
        self.assertEqual(len(result["tool_calls"]), 2)
        self.assertEqual(result["content"], "Checking...")
        self.assertEqual(result["tool_calls"][1]["function"]["name"], "project_memory_lookup")

    def test_stream_without_done_or_truncated_token_response_fails(self):
        from unittest.mock import patch
        from sytox.agent import OllamaClient, OllamaError
        class Response:
            ok = True
            def __init__(self, frames): self.frames = frames
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def iter_lines(self):
                return iter(json.dumps(x).encode() for x in self.frames)
        for frames in (
            [{"message": {"tool_calls": [proposed("write_file", {
                "path": "danger.py", "content": "do stuff"})]}, "done": False}],
            [{"message": {"content": "partial"}, "done": True, "done_reason": "length"}],
        ):
            with self.subTest(frames=frames), patch(
                    "sytox.agent.requests.post", return_value=Response(frames)):
                with self.assertRaises(OllamaError):
                    OllamaClient().chat([{"role": "user", "content": "Test"}])

if __name__ == "__main__":
    unittest.main()
