"""Offline tests for explicit screen sharing and local-only vision API."""
import base64
import threading
import unittest
from unittest.mock import patch

from sytox.screen_intents import screen_intent
from sytox.voice_features import VoiceTurnRouter
from sytox.screen_assist import explain_image

PNG = bytes.fromhex('89504e470d0a1a0a') + b'synthetic'


class ScreenTests(unittest.TestCase):
    def test_spoken_start_stop(self):
        self.assertEqual(screen_intent('Hey Sytox, guck auf meinen Bildschirm'), 'start')
        self.assertEqual(screen_intent('SYTOX, verlass meinen Bildschirm'), 'stop')
        self.assertEqual(screen_intent('Kannst wieder aus meinem Bildschirm rausgehen'), 'stop')
        self.assertIsNone(screen_intent('Was ist das fuer ein Fehler?'))

    def test_bare_sytox_wake_word(self):
        router = VoiceTurnRouter()
        self.assertEqual(router.command_for('Sytox guck auf meinen Bildschirm'),
                         'guck auf meinen Bildschirm')
        router.reset()
        self.assertIsNone(router.command_for('eine Sytox Webseite'))

    @patch('sytox.screen_assist.requests.post')
    def test_png_is_sent_only_to_loopback(self, post):
        post.return_value.json.return_value = {'message': {'content': 'Ein Fehlerfenster.'}}
        result = explain_image(PNG, 'Was steht da?')
        self.assertEqual(result, 'Ein Fehlerfenster.')
        args, kw = post.call_args
        self.assertEqual(args[0], 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(kw['json']['model'], 'qwen3-vl:2b')
        encoded = kw['json']['messages'][1]['images'][0]
        self.assertEqual(base64.b64decode(encoded), PNG)
        self.assertFalse(kw['allow_redirects'])

    def test_cancel_before_capture_analysis(self):
        stop = threading.Event()
        stop.set()
        with patch('sytox.screen_assist.requests.post') as post:
            with self.assertRaises(InterruptedError):
                explain_image(PNG, 'Was ist das?', stop=stop)
            post.assert_not_called()

    def test_invalid_image_rejected(self):
        with self.assertRaises(ValueError):
            explain_image(b'notpng', 'Test')

    def test_ui_entrypoint_uses_screen_window(self):
        from pathlib import Path
        main = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')
        self.assertIn('ScreenMainWindow as MainWindow', main)


if __name__ == '__main__':
    unittest.main()
