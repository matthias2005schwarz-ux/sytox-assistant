"""No-hardware unit tests for local performance diagnostics."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sytox.performance_monitor import measure_performance, format_performance, read_windows_gpu


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


    def test_windows_amd_gpu_via_cim_without_shell_commands(self):
        recorded = []
        def runner(argv, **kwargs):
            recorded.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout='{"name":"Radeon RX 570","utilization":42.5}')
        with patch("sytox.performance_monitor.platform.system", return_value="Windows"):
            gpu = read_windows_gpu(
                which=lambda key: "powershell.exe" if key == "powershell.exe" else None,
                command=runner,
            )
        self.assertEqual(gpu["gpu_name"], "Radeon RX 570")
        self.assertEqual(gpu["gpu_percent"], 42.5)
        self.assertEqual(gpu["gpu_load_kind"], "Windows 3D-Engine (Näherung)")
        self.assertIn("-NoProfile", recorded[0][0])
        self.assertNotIn("shell", recorded[0][1])
        self.assertIn("Radeon RX 570", format_performance(gpu))
        self.assertIn("Näherung", format_performance(gpu))

    def test_windows_gpu_counters_missing_does_not_invent_usage(self):
        with patch("sytox.performance_monitor.platform.system", return_value="Windows"):
            gpu = read_windows_gpu(
                which=lambda key: "powershell.exe",
                command=lambda *_args, **_kw:
                    SimpleNamespace(returncode=0, stdout='{"name":"AMD Radeon","utilization":null}'),
            )
        self.assertEqual(gpu["gpu_name"], "AMD Radeon")
        self.assertIsNone(gpu["gpu_percent"])
        self.assertNotIn("0 %", format_performance(gpu))


if __name__ == "__main__":
    unittest.main()
