"""On-device voice diagnosis, verifying real PCM calculations and safeguards."""
from array import array
import threading
import unittest
from pathlib import Path

from sytox.voice_diagnostics import pcm_rms_percent, microphone_probe

ROOT = Path(__file__).resolve().parents[1]


class FakeSoundDevice:
    def __init__(self, samples=None, device_name='Testmikrofon', channels=1):
        self.samples = samples
        self.device_name = device_name
        self.channels = channels
        self.stream_calls = []

    def query_devices(self, *, kind):
        assert kind == 'input'
        return {'name': self.device_name, 'max_input_channels': self.channels}

    def RawInputStream(self, *, samplerate, channels, dtype, blocksize, callback):
        self.stream_calls.append((samplerate, channels, dtype, blocksize))
        data = self.samples
        class FakeStream:
            def __enter__(self):
                if data is not None:
                    callback(data, len(data) // 2, None, None)
                return self
            def __exit__(self, *exc):
                return False
        return FakeStream()


class MicrophoneDiagnosticTests(unittest.TestCase):
    def test_zero_and_full_scale_pcm(self):
        self.assertEqual(pcm_rms_percent(b''), 0.0)
        self.assertEqual(pcm_rms_percent(bytes(400)), 0.0)
        self.assertAlmostEqual(pcm_rms_percent(array('h', [16384] * 32).tobytes()), 50.0)
        self.assertAlmostEqual(pcm_rms_percent(array('h', [32767] * 30).tobytes()), 99.997, places=2)

    def test_rejects_odd_pcm_length(self):
        with self.assertRaises(ValueError):
            pcm_rms_percent(b'abc')

    def test_real_samples_are_required_and_not_saved(self):
        fake = FakeSoundDevice(array('h', [3000] * 2048).tobytes())
        progress = []
        result = microphone_probe(progress.append, seconds=.051, sound_module=fake)
        self.assertTrue(result['signal_detected'])
        self.assertEqual(result['device'], 'Testmikrofon')
        self.assertGreater(result['bytes_read'], 0)
        self.assertGreater(progress[-1], .7)
        self.assertEqual(fake.stream_calls, [(16000, 1, 'int16', 2048)])
        self.assertNotIn('audio', result)

    def test_silence_is_not_reported_as_success(self):
        fake = FakeSoundDevice(bytes(4096))
        result = microphone_probe(lambda _: None, seconds=.051, sound_module=fake)
        self.assertFalse(result['signal_detected'])

    def test_no_samples_not_reported_as_success(self):
        fake = FakeSoundDevice(None)
        with self.assertRaisesRegex(RuntimeError, 'keine Audiodaten'):
            microphone_probe(lambda _: None, seconds=.051, sound_module=fake)

    def test_microphone_missing(self):
        fake = FakeSoundDevice(bytes(4000), channels=0)
        with self.assertRaisesRegex(RuntimeError, 'Kein Mikrofon'):
            microphone_probe(lambda _: None, seconds=.051, sound_module=fake)

    def test_cancelled_does_not_open_microphone(self):
        fake = FakeSoundDevice(bytes(4000))
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            microphone_probe(lambda _: None, cancelled, seconds=.051, sound_module=fake)
        self.assertFalse(fake.stream_calls)

    def test_ui_wires_real_listener_and_speaker_without_agent_actions(self):
        ui = (ROOT / 'sytox' / 'ui.py').read_text(encoding='utf-8')
        self.assertIn('class VoiceDiagnosticsDialog(QDialog)', ui)
        self.assertIn('Mikrofon und Unterbrechung testen', ui)
        self.assertIn('listener.hearing.connect(self._heard_phrase)', ui)
        self.assertIn('listener.interrupted.connect(self._interrupted)', ui)
        self.assertIn('speaker.stop_event.set()', ui)
        self.assertIn("QTimer.singleShot(1800, self._verify_interrupted)", ui)


if __name__ == '__main__':
    unittest.main()
