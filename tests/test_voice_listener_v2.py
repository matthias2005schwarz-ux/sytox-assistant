"""Native Qt listener regression tests using fake PCM/Vosk, no microphone access."""
import json
import os
import threading
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from sytox.ui import WakeListener


class VoiceListenerV2Tests(unittest.TestCase):
    @staticmethod
    def fake_stream(frame_count=2):
        class Stream:
            def __init__(self, *, callback, **_kwargs):
                self.callback = callback

            def __enter__(self):
                for _ in range(frame_count):
                    self.callback(b"\\x00" * 128, 64, None, None)
                return self

            def __exit__(self, *_args):
                return False
        return types.SimpleNamespace(RawInputStream=Stream)

    def vosk(self, recognizer):
        return types.SimpleNamespace(Model=lambda _path: object(),
            KaldiRecognizer=lambda *_args: recognizer, SetLogLevel=lambda _n: None)

    def run_with_deadline(self, listener):
        # Fail safely rather than trapping CI if a mock stops triggering.
        watchdog = threading.Timer(2.0, listener.stop_event.set)
        watchdog.daemon = True
        watchdog.start()
        try:
            listener.run()
        finally:
            watchdog.cancel()

    def test_repeated_partial_stop_interrupts_before_final_sentence(self):
        class Recognizer:
            def AcceptWaveform(self, _audio): return False
            def PartialResult(self): return json.dumps({"partial": "stopp"})
            def Reset(self): pass
        speaking = threading.Event()
        speaking.set()
        muted = threading.Event()
        muted.set()
        listener = WakeListener("unused-model", mute_event=muted,
                                speaking_event=speaking)
        interrupted = []
        listener.interrupted.connect(
            lambda command: (interrupted.append(command), listener.stop_event.set()))
        with patch.dict("sys.modules", {
                "sounddevice": self.fake_stream(),
                "vosk": self.vosk(Recognizer())}):
            self.run_with_deadline(listener)
        self.assertEqual(interrupted, [""])

    def test_stale_tts_fragments_are_discarded_after_speech(self):
        speaking = threading.Event()
        speaking.set()
        muted = threading.Event()
        muted.set()
        listener = WakeListener("unused-model", mute_event=muted,
                                speaking_event=speaking)
        heard = []
        listener.wake_command.connect(heard.append)

        class Recognizer:
            def __init__(self):
                self.reset_count = 0
                self.result_count = 0
            def AcceptWaveform(self, _audio):
                speaking.clear()  # TTS has just finished; queued audio is stale.
                muted.clear()
                return True
            def Result(self):
                self.result_count += 1
                # The first sample is normal loudspeaker content; the queued
                # stale sample would contain a fake wake word if not flushed.
                transcript = ("Hier ist ein Beispiel" if self.result_count == 1
                              else "hey sytox öffne notepad")
                return json.dumps({"text": transcript})
            def Reset(self):
                self.reset_count += 1
                listener.stop_event.set()

        recognition = Recognizer()
        with patch.dict("sys.modules", {
                "sounddevice": self.fake_stream(frame_count=3),
                "vosk": self.vosk(recognition)}):
            self.run_with_deadline(listener)
        self.assertEqual(heard, [])
        self.assertEqual(recognition.reset_count, 1)


if __name__ == "__main__":
    unittest.main()
