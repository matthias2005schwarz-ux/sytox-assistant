"""Actual screen UI pipeline uses the configured, local vision model."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sytox.screen_question import ScreenQuestion


class ScreenQuestionRoutingTests(unittest.TestCase):
    def fixture(self):
        owner = ScreenQuestion()
        owner.screen_active = True
        owner.screen_busy = False
        owner.screen_generation = 5
        owner.screen_cancel = None
        owner.config = {
            "ollama_url": "http://localhost:11434",
            "vision_model": "qwen3-vl:4b",
        }
        owner.screen_state = SimpleNamespace(setText=MagicMock())
        owner.store = SimpleNamespace(add_message=MagicMock())
        owner.chat_id = "sample"
        owner.add_bubble = MagicMock()
        owner.log = MagicMock()
        owner._screen_error = MagicMock()
        owner.answers = []
        owner.errors = []
        owner.screen_signals = SimpleNamespace(
            answer=SimpleNamespace(emit=lambda generation, answer:
                                   owner.answers.append((generation, answer))),
            error=SimpleNamespace(emit=lambda generation, answer:
                                  owner.errors.append((generation, answer))))
        return owner

    def test_uses_configured_vision_model_and_session_cancellation(self):
        owner = self.fixture()
        image = bytes.fromhex("89504e470d0a1a0a") + b"synthetic"
        def fake_thread(*, target, **_kwargs):
            return SimpleNamespace(start=target)
        with patch("sytox.screen_question.screenshot_png", return_value=image) as capture, \
             patch("sytox.screen_question.analyze_screenshot", return_value="Ein Fenster.") as analyze, \
             patch("sytox.screen_question.threading.Thread", side_effect=fake_thread):
            owner.ask_screen("Was ist hier?")
        capture.assert_called_once()
        analyze.assert_called_once_with(
            image, "Was ist hier?", "http://localhost:11434",
            "qwen3-vl:4b", cancel=owner.screen_cancel)
        self.assertIsNotNone(owner.screen_cancel)
        self.assertFalse(owner.screen_cancel.is_set())
        self.assertEqual(owner.answers, [(5, "Ein Fenster.")])
        owner.store.add_message.assert_called_once_with("sample", "user", "Was ist hier?")

    def test_inactive_screen_never_captures(self):
        owner = self.fixture()
        owner.screen_active = False
        with patch("sytox.screen_question.screenshot_png") as capture:
            owner.ask_screen("Bitte anschauen")
        capture.assert_not_called()

    def test_bad_ollama_endpoint_is_not_sent_to_network(self):
        owner = self.fixture()
        owner.config["ollama_url"] = "http://outside.example:11434"
        with patch("sytox.screen_question.screenshot_png", return_value=b"image"), \
             patch("sytox.screen_question.threading.Thread",
                   side_effect=lambda *, target, **_: SimpleNamespace(start=target)):
            owner.ask_screen("Bitte anschauen")
        self.assertFalse(owner.answers)
        self.assertEqual(len(owner.errors), 1)
        self.assertIn("ValueError", owner.errors[0][1])


if __name__ == "__main__":
    unittest.main()
