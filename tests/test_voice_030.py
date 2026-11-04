"""Voice 0.3.0: interruption, SAPI stop and safe optional Vosk download."""
import io
import random
import json
import tempfile
import threading
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.voice_features import (
    interruption_command, download_german_voice_model, speak_with_windows_sapi,
    VOSK_DE_MODEL_NAME, VOSK_DE_MODEL_URL,
)


class TestVoiceInterruptions(unittest.TestCase):
    def test_wake_phrase_interrupts_and_carries_remaining_command(self):
        self.assertEqual(interruption_command('Hey Sytox öffne Discord'), (True, 'öffne Discord'))

    def test_wake_only_stops_speech_and_arms_followup(self):
        self.assertEqual(interruption_command('hey sytox'), (True, ''))

    def test_stop_speech_short_command(self):
        for text in ('Stopp', 'STOP!', 'sei still', 'sytox stopp'):
            with self.subTest(text=text):
                self.assertEqual(interruption_command(text), (True, ''))

    def test_background_or_spoken_response_must_not_trigger_actions(self):
        for text in ('öffne Discord', 'Das Wort stopp ist relevant', 'SYTOX Webseite'):
            with self.subTest(text=text):
                self.assertEqual(interruption_command(text), (False, ''))

    def test_free_listening_must_be_explicit_and_nontrivial(self):
        self.assertEqual(interruption_command('öffne bitte Discord', True), (True, 'öffne bitte Discord'))
        self.assertEqual(interruption_command('öffne Discord', True), (False, ''))


class TestInterruptibleWindowsSapi(unittest.TestCase):
    def test_async_speech_is_purged_when_stop_event_set(self):
        cancel = threading.Event()
        speaker = MagicMock()
        def await_done(ms):
            cancel.set()
            return False
        speaker.WaitUntilDone.side_effect = await_done
        dispatcher = MagicMock(return_value=speaker)
        com = types.SimpleNamespace(CoInitialize=MagicMock(), CoUninitialize=MagicMock())
        with patch.dict('sys.modules', {'pythoncom': com,
                           'win32com': types.ModuleType('win32com'),
                           'win32com.client': types.SimpleNamespace(Dispatch=dispatcher)}):
            speak_with_windows_sapi('Hallo', cancel)
        self.assertEqual(speaker.Speak.call_args_list[0].args, ('Hallo', 1))
        self.assertEqual(speaker.Speak.call_args_list[-1].args, ('', 3))
        com.CoInitialize.assert_called_once()
        com.CoUninitialize.assert_called_once()

    def test_finished_speech_needs_no_purge(self):
        speaker = MagicMock()
        speaker.WaitUntilDone.return_value = True
        with patch.dict('sys.modules', {
            'pythoncom': types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None),
            'win32com': types.ModuleType('win32com'),
            'win32com.client': types.SimpleNamespace(Dispatch=lambda *_: speaker),
        }):
            speak_with_windows_sapi('Hallo')
        speaker.Speak.assert_called_once_with('Hallo', 1)


class FakeResponse:
    def __init__(self, data, url=VOSK_DE_MODEL_URL):
        self._buffer = io.BytesIO(data)
        self.headers = {'Content-Length': str(len(data))}
        self._url = url

    def __enter__(self): return self
    def __exit__(self, *args): return None
    def geturl(self): return self._url
    def read(self, size): return self._buffer.read(size)


def make_archive(entries):
    file = io.BytesIO()
    with zipfile.ZipFile(file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    # The test data must be >=1 MB to exercise the normal downloader path.
    return file.getvalue()


class TestVoskModelInstaller(unittest.TestCase):
    def test_successful_safe_download_and_reuse_without_network(self):
        base = VOSK_DE_MODEL_NAME + '/'
        archive = make_archive({base+'conf/model.conf': 'ok',
                                base+'am/final.mdl': random.Random(11).randbytes(1_300_000)})
        statuses = []
        def opener(request, **kwargs):
            self.assertEqual(request.full_url, VOSK_DE_MODEL_URL)
            return FakeResponse(archive)
        with tempfile.TemporaryDirectory() as tmp:
            dest = download_german_voice_model(lambda pct,msg: statuses.append(pct),
                                                data_dir=tmp, opener=opener)
            self.assertTrue((dest/'conf/model.conf').exists())
            self.assertEqual(statuses[-1], 100)
            reused = download_german_voice_model(lambda pct,msg: None, data_dir=tmp,
                                                  opener=lambda *args,**kw: self.fail('extra network'))
            self.assertEqual(reused, dest)

    def test_rejects_redirected_model_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = b'x'*1_100_000
            with self.assertRaisesRegex(ValueError, 'umgeleitet'):
                download_german_voice_model(lambda *args: None, data_dir=tmp,
                   opener=lambda *args,**kwargs: FakeResponse(data,'https://evil.example/file.zip'))

    def test_cancellation_before_download_does_not_open_network(self):
        stop = threading.Event(); stop.set()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(InterruptedError):
                download_german_voice_model(lambda *args: None,stop,data_dir=tmp,
                    opener=lambda *args,**kwargs: self.fail('network must not start'))

    def test_rejects_path_traversal_and_no_partial_install(self):
        base = VOSK_DE_MODEL_NAME + '/'
        archive = make_archive({base+'conf/model.conf':'ok',
                                base+'am/final.mdl':random.Random(19).randbytes(1_300_000),
                                base+'../../evil.txt':'untrusted'})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'unsicheren Pfad'):
                download_german_voice_model(lambda *args: None, data_dir=tmp,
                   opener=lambda *args,**kwargs:FakeResponse(archive))
            self.assertFalse((Path(tmp)/'evil.txt').exists())
            self.assertFalse((Path(tmp)/'models'/VOSK_DE_MODEL_NAME).exists())


if __name__ == '__main__':
    unittest.main()
