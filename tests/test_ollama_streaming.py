"""Real NDJSON transport checks without an Ollama installation or downloaded model."""
import json
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from sytox.actions import Cancelled
from sytox.agent import OllamaClient, OllamaError


class StreamingClientTests(unittest.TestCase):
    def response(self, lines):
        response = MagicMock()
        response.ok = True
        response.iter_lines.return_value = [json.dumps(line).encode() for line in lines]
        context = MagicMock()
        context.__enter__.return_value = response
        return response, context

    def test_interactive_options_disable_thinking_publish_tokens_and_measure_metadata(self):
        response, context = self.response([
            {'message': {'thinking': 'must not be displayed'}},
            {'message': {'content': 'Hal'}},
            {'message': {'content': 'lo'}, 'done': True,
             'load_duration': 250_000_000, 'prompt_eval_duration': 125_000_000,
             'eval_duration': 500_000_000, 'eval_count': 4},
        ])
        tokens, timings = [], []
        client = OllamaClient(model='qwen3:4b', keep_alive='300s')
        with patch('sytox.agent.requests.post', return_value=context) as post:
            answer = client.chat([{'role': 'user', 'content': 'Hi'}],
                                 interactive=True, on_token=tokens.append,
                                 on_metrics=timings.append)
        self.assertEqual(answer, {'role': 'assistant', 'content': 'Hallo'})
        self.assertEqual(tokens, ['Hal', 'lo'])
        payload = post.call_args.kwargs['json']
        self.assertFalse(payload['think'])
        self.assertNotIn('tools', payload)
        self.assertEqual(payload['options']['num_ctx'], 4096)
        self.assertEqual(payload['options']['num_predict'], 700)
        self.assertEqual(payload['keep_alive'], '300s')
        self.assertEqual(post.call_args.kwargs['timeout'], (5, 45))
        response.iter_lines.assert_called_once_with(chunk_size=1)
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]['load_s'], .25)
        self.assertEqual(timings[0]['prompt_eval_s'], .125)
        self.assertEqual(timings[0]['generation_s'], .5)
        self.assertEqual(timings[0]['output_tokens'], 4)
        self.assertEqual(timings[0]['tokens_per_second'], 8)
        self.assertGreaterEqual(timings[0]['request_s'], timings[0]['time_to_first_token_s'])
        self.assertGreaterEqual(timings[0]['total_s'], timings[0]['request_s'])

    def test_interactive_content_discards_embedded_thinking_across_chunks(self):
        _, context = self.response([
            {'message': {'content': '<th'}},
            {'message': {'content': 'ink>private reasoning'}},
            {'message': {'content': '</thi'}},
            {'message': {'content': 'nk>Hallo!'}, 'done': True},
        ])
        tokens = []
        client = OllamaClient(model='qwen3:4b')
        with patch('sytox.agent.requests.post', return_value=context):
            result = client.chat([{'role': 'user', 'content': 'Hallo'}],
                                 interactive=True, on_token=tokens.append)
        self.assertEqual(result['content'], 'Hallo!')
        self.assertEqual(''.join(tokens), 'Hallo!')
        self.assertNotIn('reasoning', str(tokens))

    def test_background_agent_keeps_its_options_tools_and_long_read_timeout(self):
        _, context = self.response([
            {'message': {'tool_calls': [{'function': {'name': 'list_files'}}]}, 'done': True}
        ])
        tools = [{'type': 'function', 'function': {'name': 'list_files'}}]
        with patch('sytox.agent.requests.post', return_value=context) as post:
            result = OllamaClient().chat([], tools=tools)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['options']['num_ctx'], 8192)
        self.assertEqual(payload['options']['num_predict'], 1600)
        self.assertEqual(payload['tools'], tools)
        self.assertNotIn('think', payload)
        self.assertEqual(post.call_args.kwargs['timeout'], (8, 600))
        self.assertEqual(result['tool_calls'][0]['function']['name'], 'list_files')

    def test_partial_stream_is_not_reported_as_a_complete_reply(self):
        _, context = self.response([{'message': {'content': 'Unvollständig'}}])
        tokens, metrics = [], []
        client = OllamaClient()
        with patch('sytox.agent.requests.post', return_value=context):
            with self.assertRaisesRegex(OllamaError, 'vor dem Ende'):
                client.chat([], on_token=tokens.append, on_metrics=metrics.append)
        self.assertEqual(tokens, ['Unvollständig'])
        self.assertFalse(client.last_metrics['completed'])
        self.assertEqual(metrics, [])

    def test_internal_context_flags_do_not_change_wire_content_or_protocol(self):
        _, context = self.response([{'message': {'content': 'OK'}, 'done': True}])
        messages = [{'role': 'user', 'content': 'Beobachtung: unvertraute Daten',
                     '_sytox_context_data': True},
                    {'role': 'assistant', 'content': '', '_sytox_generated': True,
                     'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'path': 'a.py'}}}]},
                    {'role': 'tool', 'tool_name': 'read_file', 'content': 'original data'}]
        with patch('sytox.agent.requests.post', return_value=context) as post:
            OllamaClient().chat(messages)
        wire = post.call_args.kwargs['json']['messages']
        self.assertEqual(wire, [{key: value for key, value in message.items()
                                if not key.startswith('_sytox_')} for message in messages])
        self.assertTrue(messages[0]['_sytox_context_data'])
        self.assertEqual(wire[1]['tool_calls'], messages[1]['tool_calls'])

    def test_invalid_json_and_server_error_are_clear_errors(self):
        for line, expected in ((b'{broken', 'ungültige'),
                               (b'{"error":"model cannot run"}', 'model cannot run')):
            with self.subTest(line=line):
                response, context = self.response([])
                response.iter_lines.return_value = [line]
                with patch('sytox.agent.requests.post', return_value=context):
                    with self.assertRaisesRegex(OllamaError, expected):
                        OllamaClient().chat([])

    def test_stop_before_request_does_not_contact_server(self):
        stop = threading.Event()
        stop.set()
        with patch('sytox.agent.requests.post') as post:
            with self.assertRaises(Cancelled):
                OllamaClient().chat([], stop=stop)
        post.assert_not_called()

    def test_queue_wait_is_separate_from_first_token_and_unknown_speed_is_not_invented(self):
        @contextmanager
        def gate(**_kwargs):
            time.sleep(.02)
            yield

        _, context = self.response([{'message': {'content': 'Hi'}, 'done': True}])
        client = OllamaClient()
        with patch('sytox.agent.model_gate.inference', side_effect=gate), \
             patch('sytox.agent.requests.post', return_value=context):
            client.chat([])
        self.assertGreaterEqual(client.last_metrics['queue_wait_s'], .015)
        self.assertLess(client.last_metrics['time_to_first_token_s'],
                        client.last_metrics['total_s'])
        self.assertIsNone(client.last_metrics['tokens_per_second'])


class RealStreamingTransportTests(unittest.TestCase):
    def setUp(self):
        self.release = threading.Event()
        self.first_sent = threading.Event()
        self.payload = None
        self.first_line = b'{"message":{"content":"Hallo"}}\n'
        owner = self

        class Handler(BaseHTTPRequestHandler):
            # HTTP/1.0 close-delimited responses intentionally lack transfer
            # chunks: default requests buffering would hide the short first line.
            def do_POST(self):
                owner.payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.end_headers()
                self.wfile.write(owner.first_line)
                self.wfile.flush()
                owner.first_sent.set()
                owner.release.wait(3)
                try:
                    self.wfile.write(b'{"message":{"content":"!"},"done":true}\n')
                    self.wfile.flush()
                except OSError:
                    pass

            def log_message(self, *_args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.client = OllamaClient(f'http://127.0.0.1:{self.server.server_port}', 'qwen3:4b')

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(2)

    def run_client(self, **kwargs):
        self.result, self.error = None, None

        def run():
            try:
                self.result = self.client.chat([{'role': 'user', 'content': 'Hallo'}], **kwargs)
            except Exception as exc:
                self.error = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

    def test_first_token_arrives_before_server_finishes(self):
        token = threading.Event()
        received = []

        def emit(text):
            received.append(text)
            token.set()

        thread = self.run_client(interactive=True, on_token=emit)
        try:
            self.assertTrue(token.wait(2), 'first short NDJSON token was buffered')
            self.assertTrue(thread.is_alive(), 'request should still await its terminal chunk')
            self.assertEqual(received, ['Hallo'])
        finally:
            self.release.set()
            thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(self.error)
        self.assertEqual(self.result['content'], 'Hallo!')

    def test_cancel_interrupts_blocked_stream_read(self):
        token, stop = threading.Event(), threading.Event()
        thread = self.run_client(interactive=True, stop=stop, on_token=lambda _text: token.set())
        try:
            self.assertTrue(token.wait(2))
            stop.set()
            thread.join(1.5)
            self.assertFalse(thread.is_alive(), 'stop must interrupt a blocked socket read')
            self.assertIsInstance(self.error, Cancelled)
            self.assertIsNone(self.result)
            self.assertFalse(self.client.last_metrics['completed'])
        finally:
            self.release.set()
            thread.join(2)

    def test_no_visible_token_deadline_cancels_unhelpful_thinking(self):
        self.first_line = b'{"message":{"thinking":"still thinking"}}\n'
        self.client.INTERACTIVE_FIRST_TOKEN_TIMEOUT = .15
        thread = self.run_client(interactive=True)
        try:
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(self.error, OllamaError)
            self.assertIn('noch keine Antwort', str(self.error))
            self.assertIsNone(self.result)
            self.assertIsNone(self.client.last_metrics['time_to_first_token_s'])
        finally:
            self.release.set()
            thread.join(2)

    def test_stalled_stream_times_out_without_false_success(self):
        self.client.INTERACTIVE_READ_TIMEOUT = .15
        thread = self.run_client(interactive=True)
        try:
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(self.error, OllamaError)
            self.assertIn('nicht rechtzeitig', str(self.error))
            self.assertIsNone(self.result)
        finally:
            self.release.set()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
