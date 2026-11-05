"""Local, read-only PC and Ollama runtime diagnostics for the UI.

The dashboard performs no installs and never sends personal information to
remote hosts. GPU telemetry is best-effort (NVIDIA SMI or Windows CIM GPU engine
counters). Unavailable readings are displayed as unavailable, never invented.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess

import requests

from .screen_vision import local_ollama_url


# Read-only Windows GPU driver and 3D-engine performance counters. This is a
# fixed command without any interpolated input or shell, not a GPU stress test.
_WINDOWS_GPU_QUERY = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$gpu=Get-CimInstance -ClassName Win32_VideoController | "
    "Where-Object {$_.Name -and $_.Name -notmatch 'Microsoft Basic|Remote Display'} | "
    "Select-Object -First 1;"
    "$perf=Get-CimInstance -ClassName Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine | "
    "Where-Object {$_.Name -like '*engtype_3D*'} | "
    "Measure-Object -Property UtilizationPercentage -Maximum;"
    "[PSCustomObject]@{name=$gpu.Name;utilization=$perf.Maximum} | ConvertTo-Json -Compress"
)


def read_windows_gpu(*, which=None, command=None) -> dict:
    """Best-effort AMD/Intel/NVIDIA GPU name and rough 3D engine load."""
    result = {"gpu_name": None, "gpu_percent": None, "gpu_load_kind": None}
    if platform.system() != "Windows":
        return result
    locate = which or shutil.which
    powershell = locate("powershell.exe") or locate("powershell")
    if not powershell:
        return result
    runner = command or subprocess.run
    try:
        proc = runner(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_GPU_QUERY],
            capture_output=True, text=True, timeout=4, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode:
            return result
        data = json.loads(proc.stdout)
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return result
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            result["gpu_name"] = name.strip()[:120]
        utilization = data.get("utilization")
        if isinstance(utilization, (float, int)) and not isinstance(utilization, bool):
            value = float(utilization)
            if 0 <= value <= 100:
                result["gpu_percent"] = round(value, 1)
                result["gpu_load_kind"] = "Windows 3D-Engine (Näherung)"
    except (OSError, ValueError, TypeError, IndexError, subprocess.TimeoutExpired):
        pass
    return result


def measure_performance(base_url="http://localhost:11434", *,
                        psutil_module=None, get=None, command=None) -> dict:
    metrics = {
        "cpu_percent": None,
        "ram_used_gb": None,
        "ram_total_gb": None,
        "ram_available_gb": None,
        "gpu_name": None,
        "gpu_percent": None,
        "gpu_load_kind": None,
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
        if getattr(ram, 'available', None) is not None:
            metrics['ram_available_gb'] = round(float(ram.available) / (1024 ** 3), 1)
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

    if not metrics['gpu_name']:
        metrics.update(read_windows_gpu(command=command))

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
    except (requests.RequestException, OSError, ValueError, TypeError, KeyError):
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
                    "nicht erkannt (GPU-Treiber oder Leistungszähler fehlen)"),
    ]
    if data.get("gpu_percent") is not None:
        parts[-1] += " · " + pct(data["gpu_percent"])
        if data.get("gpu_load_kind"):
            parts[-1] += " (" + str(data["gpu_load_kind"]) + ")"
    if data.get("vram_used_gb") is not None and data.get("vram_total_gb") is not None:
        parts.append("Grafikspeicher: " +
                     gb(data.get("vram_used_gb"), data.get("vram_total_gb")))
    running = data.get("loaded_models") or []
    parts.append("Ollama: " + (", ".join(running) if running else
                                "kein laufendes Modell erkannt"))
    if data.get("ollama_vram_gb") is not None:
        parts.append("Ollama GPU-Speicher: " + str(data["ollama_vram_gb"]) + " GB")
    return "\n".join(parts)
