"""Regression tests for RAM-aware Ollama sizing and no-download local inspection."""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sytox.model_autotune import (
    ModelRecommendation, describe_recommendation, known_model_size_gb,
    probe_hardware, read_local_model_size_gb, recommend_context,
)
from sytox.model_runtime import ollama_generation_options, history_character_budget
from sytox.agent import OllamaClient


class ModelAutotuneTests(unittest.TestCase):
    def test_30b_low_ram_is_flagged_without_switching_models(self):
        rec = recommend_context("qwen3-coder:30b", {
            "ram_total_gb": 16, "ram_available_gb": 8})
        self.assertEqual(rec.context_tokens, 4096)
        self.assertIn("19", rec.warning)
        self.assertIn("unmöglich", rec.warning)

    def test_30b_medium_high_and_low_available_ram(self):
        examples = [
            ({"ram_total_gb": 24, "ram_available_gb": 17}, 8192),
            ({"ram_total_gb": 32, "ram_available_gb": 20}, 16384),
            ({"ram_total_gb": 64, "ram_available_gb": 40}, 32768),
            ({"ram_total_gb": 64, "ram_available_gb": 5}, 4096),
        ]
        for sample, expected in examples:
            with self.subTest(sample=sample):
                self.assertEqual(
                    recommend_context("qwen3-coder:30b", sample).context_tokens,
                    expected)

    def test_missing_ram_is_explicitly_uncertain_and_conservative(self):
        rec = recommend_context("qwen3-coder:30b", {})
        self.assertEqual(rec.context_tokens, 8192)
        self.assertIn("unbekannt", rec.warning)
        self.assertIn("8K", rec.reason)

    def test_smaller_models_can_use_larger_context_with_enough_ram(self):
        self.assertEqual(recommend_context("qwen2.5-coder:3b", {
            "ram_total_gb": 8, "ram_available_gb": 6}).context_tokens, 8192)
        self.assertEqual(recommend_context("qwen2.5-coder:3b", {
            "ram_total_gb": 24, "ram_available_gb": 13}).context_tokens, 16384)

    def test_manual_context_override_is_not_replaced_by_hardware(self):
        weak = {"ram_total_gb": 8, "ram_available_gb": 2}
        self.assertEqual(ollama_generation_options("qwen3-coder:30b",
                         hardware=weak)["num_ctx"], 4096)
        self.assertEqual(ollama_generation_options("qwen3-coder:30b",
                         32768, hardware=weak)["num_ctx"], 32768)
        self.assertIn("Manuell", describe_recommendation(
            "qwen3-coder:30b", weak, manual_context=32768))

    def test_ram_probe_has_no_shell_or_download_calls(self):
        ram = SimpleNamespace(total=32 * 1024**3, available=15 * 1024**3)
        ps = SimpleNamespace(virtual_memory=lambda: ram)
        with patch("sytox.model_autotune.shutil.which", return_value=None):
            observed = probe_hardware(psutil_module=ps)
        self.assertEqual(observed["ram_total_gb"], 32)
        self.assertEqual(observed["ram_available_gb"], 15)
        self.assertIsNone(observed["vram_total_gb"])

    def test_nvidia_memory_is_optional_and_read_only(self):
        ram = SimpleNamespace(total=64 * 1024**3, available=40 * 1024**3)
        ps = SimpleNamespace(virtual_memory=lambda: ram)
        recorded = []
        def command(argv, **kwargs):
            recorded.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="16384\n")
        result = probe_hardware(psutil_module=ps,
                                which=lambda _: "C:/nvidia-smi.exe",
                                command=command)
        self.assertEqual(result["vram_total_gb"], 16.0)
        self.assertEqual(recorded[0][0][0], "C:/nvidia-smi.exe")
        self.assertNotIn("shell", recorded[0][1])

    def test_local_model_size_only_contacts_safe_ollama_tag_endpoint(self):
        accessed = []
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"models": [{"name": "qwen3-coder:30b",
                                    "size": 19_000_000_000}]}
        def request(url, **kwargs):
            accessed.append((url, kwargs))
            return Response()
        self.assertEqual(read_local_model_size_gb(
            "qwen3-coder:30b", "http://localhost:11434", get=request), 19)
        self.assertEqual(accessed[0][0], "http://localhost:11434/api/tags")
        self.assertEqual(read_local_model_size_gb(
            "qwen3-coder:30b", "https://evil.example", get=request), None)
        self.assertEqual(len(accessed), 1)

    def test_missing_or_malformed_model_metadata_never_claims_size(self):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"models": [{"name": "wrong", "size": 4000}]}
        self.assertIsNone(read_local_model_size_gb(
            "qwen3-coder:30b", "http://localhost:11434",
            get=lambda *_a, **_k: Response()))

    def test_auto_ollama_client_caches_hardware_once_per_task(self):
        profile = {"ram_total_gb": 16, "ram_available_gb": 7}
        client = OllamaClient("http://localhost:11434", "qwen3-coder:30b", 0)
        called = []
        class Response:
            ok = True
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def iter_lines(self):
                yield json.dumps({"message": {"content": "OK"},
                                  "done": True}).encode()
        def send(url, **kwargs):
            called.append(kwargs["json"]["options"]["num_ctx"])
            return Response()
        with patch("sytox.agent.probe_hardware", return_value=profile) as probe, \
             patch("sytox.agent.requests.post", side_effect=send):
            client.chat([{"role": "user", "content": "eins"}])
            client.chat([{"role": "user", "content": "zwei"}])
            self.assertEqual(client.effective_context_tokens, 4096)
        self.assertEqual(called, [4096, 4096])
        probe.assert_called_once()

    def test_manual_client_never_probes_hardware(self):
        client = OllamaClient("http://localhost:11434", "qwen3-coder:30b", 32768)
        with patch("sytox.agent.probe_hardware", side_effect=AssertionError()):
            self.assertEqual(client.effective_context_tokens, 32768)


if __name__ == "__main__":
    unittest.main()
