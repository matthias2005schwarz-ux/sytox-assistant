"""Opt-in, bounded, entirely local Ollama inference benchmark.

These measurements are from the user's machine only. CI uses mocked HTTP and
cannot establish real Qwen performance. Benchmarks never read project files,
upload prompts, download models, or modify the normal chat usage policy.
"""
from __future__ import annotations

import json
from statistics import median
import threading
from time import perf_counter

import requests

from .model_autotune import probe_hardware, recommend_context
from .model_runtime import ollama_generation_options
from .ollama_setup import model_pull_command
from .screen_vision import local_ollama_url


class BenchmarkError(RuntimeError):
    pass


class BenchmarkCancelled(BenchmarkError):
    pass


# Public fixed prompts: no conversation history, private project or local files.
TASKS = (
    ("Text", "Antworte auf Deutsch in drei kurzen Sätzen: Was ist ein Unit-Test?"),
    ("Python", "Schreibe ausschließlich eine kleine Python-Funktion namens is_even, "
     "die für eine Ganzzahl True zurückgibt, wenn sie gerade ist."),
)


def _seconds_ns(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return round(value / 1_000_000_000, 5)


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _median(values):
    valid = [v for v in values if isinstance(v, (float, int)) and not isinstance(v, bool)]
    return round(median(valid), 3) if valid else None


def run_local_benchmark(url="http://localhost:11434",
                        model="qwen3-coder:30b", *,
                        context_tokens=0, post=None, clock=None,
                        cancel: threading.Event | None = None,
                        tasks=TASKS) -> dict:
    """Run exactly 1-3 fixed-prompt samples, using streamed Ollama responses.

    The first-token wall latency includes cold loading. Ollama's eval_duration
    yields decoding speed excluding load/prompt evaluation; the two are NOT the
    same measurement. Token counts cannot be inferred from text length.
    """
    endpoint = local_ollama_url(url)
    model_pull_command(model)  # Strict local model-name validation; no pull.
    if not isinstance(tasks, (tuple, list)) or not 1 <= len(tasks) <= 3:
        raise ValueError("Benchmark erwartet ein bis drei Testaufgaben.")
    for item in tasks:
        if (not isinstance(item, (tuple, list)) or len(item) != 2 or
                not isinstance(item[0], str) or not item[0].strip() or
                not isinstance(item[1], str) or not 0 < len(item[1]) <= 700):
            raise ValueError("Ungültige Benchmark-Testaufgabe.")
    if context_tokens in (None, 0):
        chosen_ctx = recommend_context(model, probe_hardware()).context_tokens
    else:
        chosen_ctx = context_tokens
    options = ollama_generation_options(model, chosen_ctx)
    # Per-SAMPLE bound only. This does not limit everyday chat or total usage.
    options["num_predict"] = 96
    request = post or requests.post
    now = clock or perf_counter
    stop = cancel or threading.Event()
    report = []
    for label, prompt in tasks:
        if stop.is_set():
            raise BenchmarkCancelled("Benchmark vom Benutzer abgebrochen.")
        payload = {
            "model": model,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "options": dict(options),
            "keep_alive": "5m",
        }
        began = now()
        first_token = None
        chunks = []
        done = None
        try:
            with request(endpoint + "/api/chat", json=payload, stream=True,
                         timeout=(8, 240)) as response:
                response.raise_for_status()
                for raw in response.iter_lines():
                    if stop.is_set():
                        raise BenchmarkCancelled("Benchmark vom Benutzer abgebrochen.")
                    if not raw:
                        continue
                    try:
                        frame = json.loads(raw)
                    except (ValueError, UnicodeError) as exc:
                        raise BenchmarkError("Ollama lieferte ungültige Streaming-Daten.") from exc
                    if not isinstance(frame, dict):
                        raise BenchmarkError("Ollama lieferte ein ungültiges Datenobjekt.")
                    if frame.get("error"):
                        raise BenchmarkError("Ollama meldete einen Modellfehler: "
                                             + str(frame["error"])[:250])
                    message = frame.get("message") or {}
                    if not isinstance(message, dict):
                        raise BenchmarkError("Ungültige Antwortnachricht.")
                    content = message.get("content") or ""
                    if not isinstance(content, str):
                        raise BenchmarkError("Ungültige Antwortzeichen.")
                    if content:
                        if first_token is None:
                            first_token = round(max(0.0, now() - began), 3)
                        chunks.append(content)
                    if frame.get("done") is True:
                        done = frame
                        break
        except BenchmarkCancelled:
            raise
        except requests.RequestException as exc:
            raise BenchmarkError("Lokales Ollama nicht erreichbar oder Zeitüberschreitung: "
                                 + type(exc).__name__) from exc
        elapsed = round(max(0.0, now() - began), 3)
        if stop.is_set():
            raise BenchmarkCancelled("Benchmark vom Benutzer abgebrochen.")
        if done is None or first_token is None:
            raise BenchmarkError("Keine vollständige Ollama-Antwort mit sichtbaren Tokens.")
        count = _positive_int(done.get("eval_count"))
        evaluation_s = _seconds_ns(done.get("eval_duration"))
        speed = (round(count / evaluation_s, 2)
                 if count is not None and evaluation_s and evaluation_s > 0 else None)
        report.append({
            "task": label,
            "wall_seconds": elapsed,
            "first_token_seconds": first_token,
            "output_tokens": count,
            "tokens_per_second": speed,
            "prompt_tokens": _positive_int(done.get("prompt_eval_count")),
            "load_seconds": _seconds_ns(done.get("load_duration")),
            "eval_seconds": evaluation_s,
            "stopped_at_sample_token_cap": done.get("done_reason") == "length",
        })
    return {
        "model": model,
        "context_tokens": options["num_ctx"],
        "tokens_per_sample_cap": options["num_predict"],
        "sample_count": len(report),
        "median_tokens_per_second": _median([p["tokens_per_second"] for p in report]),
        "median_first_token_seconds": _median([p["first_token_seconds"] for p in report]),
        "samples": report,
        "source": "Local Ollama API, measured on this computer",
    }


def format_benchmark(report: dict) -> str:
    """Keep missing telemetry explicit; never invent benchmark measurements."""
    def number(value, suffix):
        return ("nicht gemessen" if value is None else f"{value:g} {suffix}")
    lines = [
        "Lokaler Ollama-Benchmark – " + str(report["model"]),
        "Kontext: " + str(report["context_tokens"]) +
        " Tokens · max. " + str(report["tokens_per_sample_cap"]) + " Ausgabe-Tokens pro Test",
        "Median Antwortbeginn: " + number(report.get("median_first_token_seconds"), "s"),
        "Median Generierung: " + number(report.get("median_tokens_per_second"), "Token/s"),
    ]
    for sample in report["samples"]:
        lines.append(
            str(sample["task"]) + ": Gesamt " + number(sample.get("wall_seconds"), "s")
            + ", Ausgabe " + number(sample.get("output_tokens"), "Tokens")
            + ", Generierung " + number(sample.get("tokens_per_second"), "Token/s"))
    lines.append("Hinweis: Kalter Modellstart, RAM und GPU beeinflussen Ergebnisse. "
                 "Testlimit gilt nur für diese Messung; keine Chat-Nutzungsgrenze.")
    return "\n".join(lines)
