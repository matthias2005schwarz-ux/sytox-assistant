"""Measure visible streaming latency, without inventing model/hardware results.

Default: a controlled local NDJSON server simulates a first token after 30 ms
and completion after 500 ms. One request compares the old complete-only UI's
visible latency with the new on_token callback. This measures transport and
presentation opportunities only, not a before/after inference speedup.

Optional: --live contacts an existing Ollama server using the quick-chat client
options. It does not install, pull, unload, or change any model. Only timings
are printed; neither prompt nor generated answer is written to the output.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sytox.actions import Cancelled  # noqa: E402
from sytox.agent import OllamaClient, OllamaError  # noqa: E402


@contextmanager
def simulated_ollama():
    """Serve two deliberately separated NDJSON chunks on loopback only."""
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            # Consume the full JSON request; the scripted response is not inference.
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-ndjson')
            self.end_headers()
            try:
                time.sleep(.03)
                self.wfile.write(b'{"message":{"content":"Hallo"}}\n')
                self.wfile.flush()
                time.sleep(.47)
                self.wfile.write(b'{"message":{"content":"!"},"done":true}\n')
                self.wfile.flush()
            except OSError:
                pass  # The benchmark may have been cancelled.

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.05),
                              name='sytox-benchmark-server', daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1)


def measure(url, model, prompt, stop):
    received_tokens = 0

    def on_token(_text):
        nonlocal received_tokens
        received_tokens += 1

    client = OllamaClient(url, model, keep_alive='300s')
    client.chat([
        {'role': 'system', 'content': 'Du bist SYTOX. Antworte kurz und freundlich auf Deutsch.'},
        {'role': 'user', 'content': prompt},
    ], interactive=True, think=False, priority='interactive', stop=stop,
        on_token=on_token)
    result = dict(client.last_metrics)
    result['visible_content_chunks'] = received_tokens
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--live', action='store_true',
                        help='Measure the existing Ollama server instead of the simulation.')
    parser.add_argument('--url', default='http://localhost:11434', help='Existing Ollama URL.')
    parser.add_argument('--model', default='qwen3:4b', help='Already installed Ollama model.')
    parser.add_argument('--prompt', default='Hallo', help='Live prompt (not printed).')
    parser.add_argument('--runs', type=int, default=1,
                        help='Repeated measurements; does not force cold/warm model state.')
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be at least 1')
    stop = threading.Event()
    previous_handler = signal.signal(signal.SIGINT, lambda *_args: stop.set())
    try:
        if args.live:
            runs = [measure(args.url, args.model, args.prompt, stop)
                    for _ in range(args.runs)]
            report = {
                'mode': 'live_ollama', 'model': args.model,
                'note': 'Actual inference timings; model cache state is not forced. '
                        'No legacy inference baseline was measured.',
                'runs': runs,
            }
        else:
            with simulated_ollama() as url:
                runs = [measure(url, 'simulated-not-a-real-model', 'Hallo', stop)
                        for _ in range(args.runs)]
            report = {
                'mode': 'simulated_transport_only',
                'model_inference_measured': False,
                'note': 'Same scripted response: before=wait for completion, '
                        'after=show first token. No hardware/model speed claim.',
                'runs': [{
                    'first_visible_before_s': item['request_s'],
                    'first_visible_after_s': item['time_to_first_token_s'],
                    'completion_s': item['request_s'],
                    'queue_wait_s': item['queue_wait_s'],
                    'visible_content_chunks': item['visible_content_chunks'],
                } for item in runs],
            }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Cancelled:
        print('Messung abgebrochen.', file=sys.stderr)
        return 130
    except OllamaError as exc:
        print('Messung fehlgeschlagen: ' + str(exc), file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)


if __name__ == '__main__':
    raise SystemExit(main())
