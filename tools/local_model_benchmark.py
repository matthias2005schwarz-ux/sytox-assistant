"""Run a real opt-in Qwen/Ollama benchmark from the Windows terminal.

Example: python tools/local_model_benchmark.py --model qwen3-coder:30b
The script never downloads models or reads private files.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sytox.model_benchmark import (
    BenchmarkCancelled, BenchmarkError, TASKS,
    run_local_benchmark, format_benchmark,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Measure your locally installed Ollama model.")
    parser.add_argument("--model", default="qwen3-coder:30b")
    parser.add_argument("--url", default="http://localhost:11434")
    parser.add_argument("--context", type=int, default=0, help="0 for RAM-aware automatic context")
    parser.add_argument("--samples", type=int, choices=(1, 2), default=2)
    parser.add_argument("--json", action="store_true", help="Output only JSON to stdout")
    args = parser.parse_args(argv)
    try:
        report = run_local_benchmark(
            url=args.url, model=args.model, context_tokens=args.context,
            tasks=TASKS[:args.samples])
    except (BenchmarkCancelled, BenchmarkError, ValueError) as exc:
        print("Benchmark fehlgeschlagen: " + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(format_benchmark(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
