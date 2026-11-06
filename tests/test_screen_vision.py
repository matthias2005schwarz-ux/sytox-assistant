"""On-demand screen reading: no unsolicited capture or image upload."""
import json
import threading
import unittest
from unittest.mock import MagicMock, patch

from sytox.screen_vision import ScreenVisionError, _local_ollama_url, describe_screen


class ScreenVisionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'ollama_url': 'http://localhost:11434',
                    'vision_model': 'qwen3-vl:4b', 'ram_keep_alive_seconds': 60}

    def test_never_send_screenshot_to_remote_host(self):
        for addr in ('https://remote.invalid:11434',
                     'http://localhost:11434/other',
                     'http://localhost:11434?x=1',
                     'http://user:pass@localhost:11434'):
            with self.subTest(url=addr), self.assertRaises(ScreenVisionError):
                _local_ollama_url(addr)

    def test_explanation_never_captures(self):
        with patch('sytox.screen_vision.capture_screen_base64') as capture:
            with self.assertRaises(ScreenVisionError):
                describe_screen('Was ist ein Monitor?', self.cfg)
            capture.assert_not_called()

    def test_screen_vision_stream_sends_image_only_to_local_ollama(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 200
        response.iter_lines.return_value = [
            json.dumps({'message': {'content': 'Editor '}}).encode(),
            json.dumps({'message': {'content': 'geöffnet.'}, 'done': True}).encode(),
        ]
        with patch('sytox.screen_vision.capture_screen_base64', return_value='ZmFrZQ==') as cap, \
             patch('sytox.screen_vision.requests.post', return_value=response) as post:
            observation = describe_screen('Schau auf meinen Bildschirm', self.cfg)
        self.assertEqual(observation, 'Editor geöffnet.')
        self.assertEqual(post.call_args.args[0], 'http://localhost:11434/api/chat')
        self.assertIs(post.call_args.kwargs['allow_redirects'], False)
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['model'], 'qwen3-vl:4b')
        self.assertEqual(payload['messages'][-1]['images'], ['ZmFrZQ=='])
        self.assertEqual(payload['keep_alive'], '60s')
        cap.assert_called_once()

    def test_stopping_prevents_capture(self):
        stop = threading.Event()
        stop.set()
        with patch('sytox.screen_vision.capture_screen_base64') as cap:
            with self.assertRaises(ScreenVisionError):
                describe_screen('Guck auf meinen Bildschirm', self.cfg, stop)
            cap.assert_not_called()

    def test_missing_vision_model_returns_actionable_error(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = 404
        with patch('sytox.screen_vision.capture_screen_base64', return_value='ZmFrZQ=='), \
             patch('sytox.screen_vision.requests.post', return_value=response):
            with self.assertRaisesRegex(ScreenVisionError, 'ollama pull qwen3-vl:4b'):
                describe_screen('Sieh auf meinen Bildschirm', self.cfg)


if __name__ == '__main__':
    unittest.main()
