"""No-hardware unit tests for local performance diagnostics."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sytox.performance_monitor import measure_performance, format_performance


class PerformanceTests(unittest.TestCase):
    def test_local_cpu_ram_and_ollama_model_metrics(self):
        ps = SimpleNamespace(
            cpu_percent=lambda interval=None: 43.2,
            virtual_memory=lambda: SimpleNamespace(
                total=32 * (1024 ** 3), used=13 * (1024 ** 3),
            ),
        )
        class Reply:
            def raise_for_status(self):
                pass
            def json(self):
                return {"models": [{"name": "qwen3-coder:30b",
                                    "size_vram": 4 * 1024 ** 3}]}
        with patch("sytox.performance_monitor.shutil.which", return_value=None):
            result = measure_performance(
                "http://localhost:11434", psutil_module=ps,
                get=lambda *_args, **_kwargs: Reply(),
            )
        self.assertEqual(result["cpu_percent"], 43.2)
        self.assertEqual(result["ram_total_gb"], 32)
        self.assertEqual(result["ollama_vram_gb"], 4)
        self.assertIn("qwen3-coder:30b", format_performance(result))
        self.assertIn("13 / 32 GB", format_performance(result))

    def test_unknown_gpu_is_not_invented(self):
        with patch("sytox.performance_monitor.shutil.which", return_value=None):
            result = measure_performance(
                "http://localhost:11434",
                psutil_module=SimpleNamespace(
                    cpu_percent=lambda interval=None: 0,
                    virtual_memory=lambda: SimpleNamespace(total=1, used=0)),
                get=lambda *_args, **_kwargs:
                    (_ for _ in ()).throw(OSError("no Ollama")),
            )
        self.assertIsNone(result["gpu_name"])
        self.assertIn("nicht verfügbar", format_performance(result))


if __name__ == "__main__":
    unittest.main()
