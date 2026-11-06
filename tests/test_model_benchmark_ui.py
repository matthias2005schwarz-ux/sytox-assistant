"""Native Qt settings benchmark smoke tests; no real model required."""
from __future__ import annotations

import os
import threading
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from sytox.model_benchmark import BenchmarkCancelled
from sytox.ui import SettingsDialog, _ACTIVE_BENCHMARK_WORKERS


class BenchmarkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self):
        return SettingsDialog({
            "model": "qwen3-coder:30b",
            "ollama_url": "http://localhost:11434",
            "model_context_tokens": 4096,
            "workspace": "C:/temp/test-project",
        })

    def test_settings_show_opt_in_benchmark_without_starting_it(self):
        dialog = self.dialog()
        self.assertTrue(dialog.benchmark_button.isEnabled())
        self.assertFalse(dialog.benchmark_cancel_button.isEnabled())
        self.assertIn("Noch nicht gemessen", dialog.benchmark_status.text())
        self.assertEqual(len(_ACTIVE_BENCHMARK_WORKERS), 0)
        dialog.close()

    def test_benchmark_runs_in_worker_and_updates_status(self):
        report = {"model": "qwen3-coder:30b", "context_tokens": 4096,
                  "tokens_per_sample_cap": 96, "median_tokens_per_second": 40,
                  "median_first_token_seconds": 0.5, "samples": [
                      {"task": "Text", "wall_seconds": 2,
                       "output_tokens": 20, "tokens_per_second": 40},
                  ]}
        dialog = self.dialog()
        with patch("sytox.ui.run_local_benchmark", return_value=report) as run:
            dialog.start_benchmark()
            worker = dialog.benchmark_worker
            self.assertIsNotNone(worker)
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
            self.assertIn("40", dialog.benchmark_status.text())
            self.assertTrue(dialog.benchmark_button.isEnabled())
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["context_tokens"], 4096)
        dialog.close()
        self.app.processEvents()

    def test_closing_dialog_cancels_detached_running_worker(self):
        entered = threading.Event()
        def benchmark(_url, _model, *, context_tokens, cancel):
            entered.set()
            cancel.wait(3)
            raise BenchmarkCancelled("User stopped")
        dialog = self.dialog()
        with patch("sytox.ui.run_local_benchmark", side_effect=benchmark):
            dialog.start_benchmark()
            worker = dialog.benchmark_worker
            self.assertTrue(entered.wait(2))
            dialog.reject()
            self.assertTrue(worker.cancel_event.is_set())
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
        self.assertFalse(worker.isRunning())


if __name__ == "__main__":
    unittest.main()
