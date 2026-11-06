"""Regression checks for model-aware generation and long-task compaction."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sytox.model_runtime import ollama_generation_options, compact_agent_history
from sytox.agent import OllamaClient


class ModelRuntimeTests(unittest.TestCase):
    def test_large_qwen3_coder_gets_more_context_and_output(self):
        opts = ollama_generation_options("qwen3-coder:30b")
        self.assertEqual(opts["num_ctx"], 16384)
        self.assertEqual(opts["num_predict"], 4096)
        self.assertEqual(opts["temperature"], 0.2)

    def test_smaller_models_retain_conservative_defaults(self):
        opts = ollama_generation_options("qwen2.5-coder:7b")
        self.assertEqual(opts["num_ctx"], 8192)
        self.assertLessEqual(opts["num_predict"], 2048)

    def test_manual_context_setting_is_bounded(self):
        self.assertEqual(ollama_generation_options("qwen3-coder:30b", 32768)["num_ctx"], 32768)
        self.assertEqual(ollama_generation_options("qwen3-coder:30b", 0)["num_ctx"], 16384)
        for invalid in (-1, True, "32768", 65536, 1000):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ollama_generation_options("qwen3-coder:30b", invalid)

    def test_compaction_preserves_goal_progress_and_tool_pairing(self):
        messages = [{"role": "system", "content": "Rules"}]
        for i in range(50):
            messages.extend([
                {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "read_file", "arguments": {"path": f"file{i}.py"}}}]},
                {"role": "tool", "tool_name": "read_file", "content": f"contents {i}"},
            ])
        state = {"last_result": "Tests erfolgreich", "coding_plan": {
                    "steps": ["Code prüfen", "Tests", "Review"]},
                 "progress_notes": [{"next_step": "Schnittstellen aktualisieren"}],
                 "unvalidated_paths": ["new.py"]}
        output = compact_agent_history(messages, "Großes Programm entwickeln", state)
        self.assertEqual(output[0]["role"], "system")
        self.assertEqual(output[1]["role"], "user")
        self.assertIn("Großes Programm entwickeln", output[1]["content"])
        self.assertIn("Schnittstellen aktualisieren", output[1]["content"])
        self.assertIn("new.py", output[1]["content"])
        self.assertLessEqual(len(output), 29)
        self.assertNotEqual(output[2]["role"], "tool")
        self.assertIn("contents 49", str(output))

    def test_small_history_is_unchanged(self):
        messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "hello"}]
        self.assertIs(compact_agent_history(messages, "hello"), messages)

    def test_client_sends_new_options_to_ollama(self):
        class Response:
            ok = True
            status_code = 200
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def iter_lines(self):
                yield json.dumps({"message": {"content": "Alles klar"}, "done": True}).encode()
        seen = {}
        def fake_post(url, **kwargs):
            seen["url"] = url
            seen["options"] = kwargs["json"]["options"]
            return Response()
        client = OllamaClient("http://localhost:11434", "qwen3-coder:30b", 32768)
        with patch("sytox.agent.requests.post", side_effect=fake_post):
            result = client.chat([{"role": "user", "content": "test"}])
        self.assertEqual(result["content"], "Alles klar")
        self.assertEqual(seen["options"]["num_ctx"], 32768)
        self.assertEqual(seen["options"]["num_predict"], 4096)
        self.assertEqual(seen["url"], "http://localhost:11434/api/chat")


if __name__ == "__main__":
    unittest.main()
