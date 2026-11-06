"""Offline-safe benchmark tests (fake Ollama streams; no GPU needed in CI)."""
import json
import threading
import unittest
from unittest.mock import patch

from sytox.model_benchmark import (
    BenchmarkCancelled, BenchmarkError, format_benchmark, run_local_benchmark,
)


class FakeStream:
    def __init__(self, frames, *, on_frame=None):
        self.frames = frames
        self.on_frame = on_frame
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def raise_for_status(self): pass
    def iter_lines(self):
        for x in self.frames:
            if self.on_frame:
                self.on_frame()
            yield json.dumps(x).encode("utf-8")


def frames(text="ok", *, done=True, output_tokens=20, reason="stop"):
    sequence = [{"message": {"content": text}, "done": False}]
    if done:
        sequence.append({
            "message": {"content": ""}, "done": True,
            "done_reason": reason, "eval_count": output_tokens,
            "eval_duration": 500_000_000, "load_duration": 1_000_000_000,
            "prompt_eval_count": 12,
        })
    return sequence


class ModelBenchmarkTests(unittest.TestCase):
    def test_fixed_prompts_local_endpoint_metrics_and_format(self):
        requested = []
        clocks = iter([0.0, 0.7, 1.9, 2.0, 2.4, 3.0])
        def post(url, **kwargs):
            requested.append((url, kwargs))
            return FakeStream(frames())
        report = run_local_benchmark(context_tokens=4096, post=post,
                                     clock=lambda: next(clocks))
        self.assertEqual(report["model"], "qwen3-coder:30b")
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["median_tokens_per_second"], 40)
        self.assertEqual(report["median_first_token_seconds"], 0.55)
        self.assertEqual(report["samples"][0]["load_seconds"], 1)
        self.assertEqual(report["samples"][0]["wall_seconds"], 1.9)
        for url, kwargs in requested:
            self.assertEqual(url, "http://localhost:11434/api/chat")
            self.assertEqual(kwargs["json"]["options"]["num_predict"], 96)
            self.assertTrue(kwargs["json"]["stream"])
            self.assertIs(kwargs["allow_redirects"], False)
            self.assertNotIn("private", json.dumps(kwargs["json"]))
        self.assertIn("40 Token/s", format_benchmark(report))
        self.assertIn("keine Chat-Nutzungsgrenze", format_benchmark(report))

    def test_remote_url_rejected_before_post(self):
        def forbidden(*_a, **_kw):
            self.fail("Should never send network request to remote endpoint")
        for url in ("http://attacker.example:11434", "https://localhost:11434",
                    "http://127.0.0.1:8000", "http://user:pass@localhost:11434",
                    "http://localhost:11434/evil"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                run_local_benchmark(url=url, context_tokens=4096, post=forbidden)

    def test_incomplete_stream_fails_instead_of_fake_success(self):
        with self.assertRaises(BenchmarkError):
            run_local_benchmark(
                context_tokens=4096, tasks=[("A", "Test")],
                post=lambda *_a, **_kw: FakeStream(frames(done=False)))
        with self.assertRaises(BenchmarkError):
            run_local_benchmark(
                context_tokens=4096, tasks=[("A", "Test")],
                post=lambda *_a, **_kw: FakeStream([
                    {"message": {"content": ""}, "done": True}]))

    def test_missing_eval_duration_is_unmeasured_not_guess(self):
        sample = [{"message": {"content": "hi"}, "done": False},
                  {"message": {}, "done": True, "eval_count": 12}]
        report = run_local_benchmark(context_tokens=4096,
            tasks=[("A", "fixed")],
            post=lambda *_a, **_kw: FakeStream(sample))
        self.assertIsNone(report["median_tokens_per_second"])
        self.assertIn("nicht gemessen", format_benchmark(report))

    def test_cancelled_before_or_during_stream(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(BenchmarkCancelled):
            run_local_benchmark(context_tokens=4096, cancel=cancel,
                post=lambda *_a, **_kw: self.fail("Must not request"))
        cancel.clear()
        def stop_when_streamed():
            cancel.set()
        with self.assertRaises(BenchmarkCancelled):
            run_local_benchmark(context_tokens=4096, cancel=cancel,
                post=lambda *_a, **_kw: FakeStream(frames(), on_frame=stop_when_streamed))

    def test_validation_and_per_sample_token_cap_are_not_chat_quotas(self):
        for args in (
            {"model": "../unsafe", "context_tokens": 4096},
            {"context_tokens": 1024},
            {"context_tokens": 4096, "tasks": []},
            {"context_tokens": 4096, "tasks": [("x", "")]},
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                run_local_benchmark(**args, post=lambda *_a, **_kw: self.fail("No request"))

    def test_auto_context_respects_ram_without_forcing_chat_setting(self):
        result_frames = frames()
        with patch("sytox.model_benchmark.probe_hardware", return_value={
            "ram_total_gb": 16, "ram_available_gb": 8}):
            report = run_local_benchmark(context_tokens=0,
                tasks=[("A", "Test")],
                post=lambda *_a, **_kw: FakeStream(result_frames))
        self.assertEqual(report["context_tokens"], 4096)


if __name__ == "__main__":
    unittest.main()
