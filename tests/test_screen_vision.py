"""No-network safety and command tests for local screenshot vision."""
from __future__ import annotations

import json
import threading
import unittest

from sytox.screen_vision import (
    DEFAULT_VISION_MODEL, screen_intent, screen_followup_intent,
    local_ollama_url, vision_request, analyze_screenshot,
)


class ScreenVisionTests(unittest.TestCase):
    def setUp(self):
        self.png = b"\x89PNG\r\n\x1a\n" + b"test"

    def test_voice_activation_and_revoke_intents(self):
        for phrase in (
            "Hey Sytox guck mal auf meinen Bildschirm, was ist das für ein Fehler?",
            "Schau auf meinen Bildschirm",
            "Analysiere meinen Screenshot",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(screen_intent(phrase), "enable")
        for phrase in (
            "Okay, kannst wieder aus meinem Bildschirm rausgehen",
            "Bildschirmfreigabe beenden",
            "Bildschirm stoppen",
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(screen_intent(phrase), "disable")
        self.assertIsNone(screen_intent("Öffne Notepad"))
        self.assertTrue(screen_followup_intent("Was ist dieser Fehler hier?"))
        self.assertFalse(screen_followup_intent("Schreib ein Python-Skript"))

    def test_only_local_ollama_receives_images(self):
        self.assertEqual(local_ollama_url("http://127.0.0.1:11434"),
                         "http://127.0.0.1:11434")
        for url in (
            "https://localhost:11434", "http://remote.example:11434",
            "http://localhost:11434/api/foo", "http://user@localhost:11434",
            "http://localhost:11435", "file:///secret",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_ollama_url(url)

    def test_model_request_contains_one_image_and_no_tools(self):
        payload = vision_request(self.png, "Was ist hier?", DEFAULT_VISION_MODEL)
        self.assertEqual(payload["model"], "qwen3-vl:4b")
        self.assertEqual(len(payload["messages"][0]["images"]), 1)
        self.assertNotIn("tools", payload)
        self.assertIn("Was ist hier?", payload["messages"][0]["content"])
        with self.assertRaises(ValueError):
            vision_request(b"not a png", "test")

    def test_streaming_response_and_model_error(self):
        class Response:
            def __init__(self, chunks):
                self.chunks = chunks
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def raise_for_status(self):
                pass
            def iter_lines(self):
                return iter(json.dumps(x).encode() for x in self.chunks)
        recorded = []
        def call(url, **kwargs):
            recorded.append((url, kwargs))
            return Response([
                {"message": {"content": "Fehler "}, "done": False},
                {"message": {"content": "404"}, "done": True},
            ])
        result = analyze_screenshot(self.png, "Was ist falsch?",
                                    "http://localhost:11434", "qwen3-vl:4b",
                                    post=call)
        self.assertEqual(result, "Fehler 404")
        self.assertEqual(recorded[0][0], "http://localhost:11434/api/chat")
        self.assertTrue(recorded[0][1]["stream"])
        self.assertIs(recorded[0][1]["allow_redirects"], False)

    def test_cancelled_request_aborts_without_displaying_answer(self):
        cancel = threading.Event()
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def raise_for_status(self):
                pass
            def close(self):
                pass
            def iter_lines(self):
                yield b'{"message":{"content":"private"},"done":false}'
                cancel.set()
                yield b'{"message":{"content":"secret"},"done":true}'
        with self.assertRaises(InterruptedError):
            analyze_screenshot(self.png, "Bitte ansehen",
                               "http://localhost:11434", "qwen3-vl:4b",
                               post=lambda *_args, **_kwargs: Response(),
                               cancel=cancel)


if __name__ == "__main__":
    unittest.main()
