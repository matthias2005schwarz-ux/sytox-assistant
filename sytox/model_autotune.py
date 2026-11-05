"""Conservative, offline-first hardware recommendations for local Ollama models.

Recommendations do not install models, alter stored user settings or guarantee
performance. They only choose a per-request context window in automatic mode.
Unmeasurable RAM/VRAM is reported as unknown, not fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess
from typing import Any


@dataclass(frozen=True)
class ModelRecommendation:
    context_tokens: int
    reason: str
    warning: str = ""
    estimated_model_gb: float | None = None


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    number = float(value)
    if number < 0 or number != number or number == float("inf"):
        return None
    return number


def known_model_size_gb(model: str) -> float | None:
    """Approximate Q4 model footprint in GB; actual installed size may differ."""
    lower = str(model or "").lower().strip()
    for prefix, size in (("qwen3-coder:30b", 19.0),
                         ("qwen2.5-coder:7b", 4.7),
                         ("qwen2.5-coder:3b", 2.0),
                         ("qwen2.5-coder:1.5b", 1.0)):
        if lower == prefix:
            return size
    return None


def recommend_context(model: str, hardware: dict | None = None) -> ModelRecommendation:
    """Choose 4K/8K/16K/32K based on physical RAM, free RAM and known VRAM.

    Ollama runtime overhead and the KV cache vary. Even on high-memory systems
    this is only an estimate, never a promise that the model can be loaded.
    """
    stats = hardware if isinstance(hardware, dict) else {}
    total = _numeric(stats.get("ram_total_gb"))
    available = _numeric(stats.get("ram_available_gb"))
    vram = _numeric(stats.get("vram_total_gb"))
    installed_size = _numeric(stats.get("model_size_gb"))
    approx_size = installed_size if installed_size and installed_size > 0 else known_model_size_gb(model)
    size_label = ("lokal gemessen" if installed_size and installed_size > 0 else "geschätzt")
    is_30b = str(model or "").lower().startswith("qwen3-coder:30b")

    if total is None or total <= 0:
        return ModelRecommendation(
            8192, "RAM-Daten nicht verfügbar; vorsichtige automatische Einstellung (8K).",
            "RAM-Größe unbekannt. Keine verlässliche Aussage zur Modellleistung möglich.",
            approx_size)

    if is_30b:
        if total < 24:
            return ModelRecommendation(
                4096,
                f"Nur {total:g} GB RAM: minimale 4K-Kontextgröße für einen vorsichtigen Versuch.",
                f"Qwen3-Coder 30B benötigt ungefähr {approx_size or 19:g} GB "
                f"Modellspeicher ({size_label}) plus Zusatzspeicher. "
                "Mit diesem RAM ist der Betrieb möglicherweise unmöglich oder extrem langsam.",
                approx_size)
        if total < 32:
            return ModelRecommendation(
                8192,
                f"{total:g} GB RAM: 8K-Kontext zur Begrenzung des Speicherbedarfs.",
                "30B-Modell auf diesem PC möglicherweise sehr langsam; nicht garantiert lauffähig.",
                approx_size)
        if available is not None and available < 7 and (vram is None or vram < 18):
            return ModelRecommendation(
                4096,
                f"Nur {available:g} GB RAM frei; 4K-Kontext empfohlen.",
                "Wenig verfügbarer RAM. Bitte andere Speicherverbraucher schließen.",
                approx_size)
        if available is not None and available < 12 and (vram is None or vram < 18):
            return ModelRecommendation(
                8192, f"Nur {available:g} GB RAM frei; 8K-Kontext empfohlen.",
                "Der Speicherbedarf kann trotz der geringeren Kontextgröße zu hoch sein.",
                approx_size)
        if total >= 64 and (available is None or available >= 28 or (vram and vram >= 24)):
            return ModelRecommendation(
                32768, "Ausreichend Gesamtspeicher für einen größeren 32K-Kontext vermutet.",
                "32K benötigt erheblich mehr KV-Cache und ist nicht auf echter Hardware geprüft.",
                approx_size)
        if total >= 48 or (total >= 32 and (available is None or available >= 16)):
            return ModelRecommendation(
                16384, "16K-Kontext als RAM-bewusster Mittelweg.",
                "Auch 16K kann bei großem Modell langsam sein; tatsächlichen RAM prüfen.",
                approx_size)
        return ModelRecommendation(
            8192, "8K-Kontext als konservative Einstellung für das große Modell.",
            "", approx_size)

    # Small coding models. Physical RAM and current headroom still matter.
    if total < 8 or (available is not None and available < 2):
        return ModelRecommendation(4096, "Wenig Arbeitsspeicher: 4K-Kontext.", "", approx_size)
    if total < 16 or (available is not None and available < 5):
        return ModelRecommendation(8192, "8K-Kontext bei begrenztem RAM.", "", approx_size)
    if total >= 48 and (available is None or available >= 18):
        return ModelRecommendation(32768, "32K-Kontext bei viel verfügbarem RAM.", "", approx_size)
    if available is None or available >= 8:
        return ModelRecommendation(16384, "16K-Kontext bei ausreichendem RAM.", "", approx_size)
    return ModelRecommendation(8192, "8K-Kontext bei aktuell knappem RAM.", "", approx_size)


def probe_hardware(*, psutil_module=None, which=None, command=None) -> dict:
    """Read-only memory and NVIDIA VRAM sampling without shell or networking."""
    result = {"ram_total_gb": None, "ram_available_gb": None,
              "vram_total_gb": None}
    try:
        psutil = psutil_module
        if psutil is None:
            import psutil
        mem = psutil.virtual_memory()
        result["ram_total_gb"] = round(float(mem.total) / (1024 ** 3), 1)
        result["ram_available_gb"] = round(float(mem.available) / (1024 ** 3), 1)
    except (ImportError, AttributeError, OSError, TypeError, ValueError):
        pass
    find = which or shutil.which
    exe = find("nvidia-smi")
    if exe:
        try:
            runner = command or subprocess.run
            proc = runner([exe, "--query-gpu=memory.total",
                           "--format=csv,noheader,nounits"],
                          capture_output=True, text=True, timeout=2,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                          check=False)
            if proc.returncode == 0:
                first = proc.stdout.strip().splitlines()[0].strip()
                result["vram_total_gb"] = round(float(first) / 1024, 1)
        except (IndexError, ValueError, OSError, subprocess.TimeoutExpired):
            pass
    return result


def describe_recommendation(model: str, hardware: dict | None = None,
                            *, manual_context: int | None = 0) -> str:
    """User-facing recommendation without pretending manual settings were changed."""
    r = recommend_context(model, hardware)
    override = manual_context not in (None, 0)
    if override:
        prefix = f"Manuell: {manual_context:,} Tokens; automatische Empfehlung: {r.context_tokens:,}."
    else:
        prefix = f"Automatisch empfohlen: {r.context_tokens:,} Kontext-Tokens."
    size = (f" Modellgröße ca. {r.estimated_model_gb:g} GB (Schätzung bzw. "
            "lokale Dateigröße; zusätzlicher RAM nötig)." if r.estimated_model_gb else "")
    return prefix + "\n" + r.reason + size + ("\nWARNUNG: " + r.warning if r.warning else "")
