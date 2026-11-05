"""Local, read-only PC and Ollama runtime diagnostics for the UI.

The dashboard performs no installs and never sends personal information to
remote hosts. GPU telemetry is best-effort (NVIDIA SMI when available); AMD/
Intel values are reported as unavailable rather than invented.
"""
from __future__ import annotations

import platform
import shutil
import subprocess

import requests

from .screen_vision import local_ollama_url


def measure_performance(base_url="http://localhost:11434", *,
                        psutil_module=None, get=None, command=None) -> dict:
    metrics = {
        "cpu_percent": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "gpu_name": None,
        "gpu_percent": None,
        "vram_used_gb": None,
        "vram_total_gb": None,
        "loaded_models": [],
        "ollama_vram_gb": None,
    }
    try:
        psutil = psutil_module
        if psutil is None:
            import psutil
        metrics["cpu_percent"] = round(float(psutil.cpu_percent(interval=None)), 1)
        ram = psutil.virtual_memory()
        metrics["ram_total_gb"] = round(float(ram.total) / (1024 ** 3), 1)
        metrics["ram_used_gb"] = round(float(ram.used) / (1024 ** 3), 1)
    except (ImportError, OSError, ValueError, AttributeError):
        pass

    binary = shutil.which("nvidia-smi")
    if binary:
        args = [
            binary,
            "--query-gpu=name,utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            runner = command or subprocess.run
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = runner(args, capture_output=True, text=True,
                         timeout=2, creationflags=flags, check=False)
            if out.returncode == 0:
                columns = out.stdout.splitlines()[0].split(",")
                if len(columns) >= 4:
                    metrics["gpu_name"] = columns[0].strip()[:100]
                    metrics["gpu_percent"] = float(columns[1])
                    metrics["vram_used_gb"] = round(float(columns[2]) / 1024, 1)
                    metrics["vram_total_gb"] = round(float(columns[3]) / 1024, 1)
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            pass

    try:
        endpoint = local_ollama_url(base_url)
        requester = get or requests.get
        response = requester(endpoint + "/api/ps", timeout=2)
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models", []) if isinstance(payload, dict) else []
        if isinstance(models, list):
            loaded = [m for m in models if isinstance(m, dict)]
            metrics["loaded_models"] = [
                str(x.get("name", "unbekannt"))[:100] for x in loaded[:5]
            ]
            metrics["ollama_vram_gb"] = round(
                sum(float(x.get("size_vram") or 0) for x in loaded[:5]) / (1024 ** 3), 1
            )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        pass
    return metrics


def format_performance(data: dict) -> str:
    def pct(v):
        return "nicht verfügbar" if v is None else f"{v:g} %"
    def gb(a, b):
        return ("nicht verfügbar" if a is None or b is None else
                f"{a:g} / {b:g} GB")
    parts = [
        "CPU: " + pct(data.get("cpu_percent")),
        "RAM: " + gb(data.get("ram_used_gb"), data.get("ram_total_gb")),
        "GPU: " + (str(data["gpu_name"]) if data.get("gpu_name") else
                    "Auslastung nicht verfügbar (NVIDIA-SMI optional)"),
    ]
    if data.get("gpu_percent") is not None:
        parts[-1] += " · " + pct(data["gpu_percent"])
        parts.append("Grafikspeicher: " +
                     gb(data.get("vram_used_gb"), data.get("vram_total_gb")))
    running = data.get("loaded_models") or []
    parts.append("Ollama: " + (", ".join(running) if running else
                                "kein laufendes Modell erkannt"))
    if data.get("ollama_vram_gb") is not None:
        parts.append("Ollama GPU-Speicher: " + str(data["ollama_vram_gb"]) + " GB")
    return "\n".join(parts)
