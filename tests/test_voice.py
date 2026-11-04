"""Audio conversation tests without microphone, audio hardware or network."""
import json
import tempfile
import threading
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

from sytox.voice_features import VoiceTurnRouter, render_speech_file, transcribe_wav, spoken_text, desktop_voice_intent, agent_status_intent


class TestVoiceRouting(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.router = VoiceTurnRouter(clock=lambda: self.clock[0], follow_up_seconds=25)

    def test_requires_wakeword_initially(self):
        self.assertIsNone(self.router.command_for('öffne notepad'))

    def test_wake_with_inline_command(self):
        self.assertEqual(self.router.command_for('Hey Sytox öffne Notepad'), 'öffne Notepad')

    def test_wake_only_opens_followup(self):
        self.assertIsNone(self.router.command_for('Hey Sytox'))
        self.assertEqual(self.router.command_for('was geht'), 'was geht')

    def test_followup_after_reply(self):
        self.router.allow_follow_up()
        self.clock[0] += 24
        self.assertEqual(self.router.command_for('wie ist das Wetter'), 'wie ist das Wetter')

    def test_followup_expires(self):
        self.router.allow_follow_up()
        self.clock[0] += 26
        self.assertIsNone(self.router.command_for('und morgen'))

    def test_recognized_followup_extends_window(self):
        self.router.allow_follow_up()
        self.clock[0] += 24
        self.assertEqual(self.router.command_for('und dann'), 'und dann')
        self.clock[0] += 24
        self.assertEqual(self.router.command_for('noch was'), 'noch was')

    def test_reset_closes_wake_window(self):
        self.router.allow_follow_up()
        self.router.reset()
        self.assertIsNone(self.router.command_for('Frage'))

    def test_explicit_freely_listening_mode(self):
        router = VoiceTurnRouter(require_wake=False)
        self.assertEqual(router.command_for('Was kannst du'), 'Was kannst du')

    def test_blank_audio_text_ignored(self):
        self.assertIsNone(self.router.command_for(' '))

    def test_misrecognized_wakeword_variants(self):
        for phrase in ['hei saitox', 'he seitox', 'hey sytoks']:
            with self.subTest(phrase=phrase):
                self.router.reset()
                self.assertEqual(self.router.command_for(phrase+' hallo'), 'hallo')

    def test_near_match_is_not_accepted(self):
        self.assertIsNone(self.router.command_for('eine Sytox Webseite'))

    def test_overlong_followup_window_is_clamped(self):
        router = VoiceTurnRouter(follow_up_seconds=500, clock=lambda: self.clock[0])
        router.allow_follow_up()
        self.clock[0] += 121
        self.assertIsNone(router.command_for('weiter'))


class TestDesktopVoiceIntents(unittest.TestCase):
    def test_windows_and_control_panel(self):
        self.assertEqual(desktop_voice_intent('Zeig mir die offenen Fenster'), ('windows', ''))
        self.assertEqual(desktop_voice_intent('zeige mir alle Fenster'), ('windows', ''))
        self.assertEqual(desktop_voice_intent('öffne PC-Steuerung'), ('panel', ''))

    def test_program_search_only(self):
        self.assertEqual(desktop_voice_intent('suche Programm Firefox'), ('apps', 'Firefox'))
        self.assertEqual(desktop_voice_intent('öffne Editor'), ('apps', 'Editor'))
        self.assertEqual(desktop_voice_intent('starte Taschenrechner'), ('apps', 'Rechner'))

    def test_spoken_mic_off(self):
        self.assertEqual(desktop_voice_intent('Mikrofon ausschalten'), ('stop_listening', ''))
        self.assertEqual(desktop_voice_intent('Sprachmodus beenden'), ('stop_listening', ''))

    def test_unrelated_requests_remain_agent_tasks(self):
        self.assertIsNone(desktop_voice_intent('Wie ist das Wetter?'))
        self.assertIsNone(desktop_voice_intent('Schreib mir eine Datei'))
        self.assertIsNone(desktop_voice_intent('öffne die private Datei'))
        self.assertIsNone(desktop_voice_intent('suche Programm A'))
        self.assertIsNone(desktop_voice_intent(''))


class TestAgentStatusVoiceIntents(unittest.TestCase):
    def test_progress_questions_are_informational(self):
        for phrase in ('Wie weit bist du?', 'Was machst du gerade?',
                       'Arbeitest du noch?', 'Läuft mein Auftrag noch?',
                       'Wie ist der aktuelle Stand?'):
            with self.subTest(phrase=phrase):
                self.assertEqual(agent_status_intent(phrase), 'status')

    def test_progress_intent_does_not_catch_new_task_or_stop(self):
        for phrase in ('Programmier eine Webseite', 'Stopp',
                       'Öffne Notepad', 'Wie spät ist es?', ''):
            with self.subTest(phrase=phrase):
                self.assertIsNone(agent_status_intent(phrase))


class TestVoiceRendering(unittest.TestCase):
    def test_markdown_not_spoken_literally(self):
        result=spoken_text('**Hallo!** [Projekt](https://example.com)\n```python\nprint(1)\n```')
        self.assertEqual(result,'Hallo! Projekt Codebeispiel ausgelassen.')

    def test_long_response_shortened_at_sentence_boundary(self):
        result=spoken_text('Hallo. '+'Noch mehr Worte. '*30,limit=80)
        self.assertTrue(result.endswith('.'))
        self.assertLessEqual(len(result),80)

    def test_edge_requires_explicit_permission(self):
        with self.assertRaises(PermissionError):
            render_speech_file('Hallo', {'speech_engine':'edge','edge_consent':False})

    def test_edge_invalid_voice_rejected(self):
        with self.assertRaises(ValueError):
            render_speech_file('Hallo', {'speech_engine':'edge','edge_consent':True,'edge_voice':'bad'})

    def test_edge_synthetic_audio_generated_with_mock(self):
        values = {}
        class Communicate:
            def __init__(self, text, voice, rate):
                values.update(text=text, voice=voice, rate=rate)
            async def save(self, path):
                Path(path).write_bytes(b'MOCK_MP3')
        with patch.dict('sys.modules', {'edge_tts':types.SimpleNamespace(Communicate=Communicate)}):
            path = render_speech_file(' Guten  Tag ', {'speech_engine':'edge',
                                      'edge_consent':True,'edge_voice':'de-DE-KatjaNeural',
                                      'edge_rate':'+8%'})
        try:
            self.assertEqual(path.read_bytes(), b'MOCK_MP3')
            self.assertEqual(values, {'text':'Guten Tag','voice':'de-DE-KatjaNeural','rate':'+8%'})
        finally:
            path.unlink(missing_ok=True)

    def test_edge_cancel_before_sending(self):
        stop = threading.Event();stop.set()
        with self.assertRaises(InterruptedError):
            render_speech_file('Privat', {'speech_engine':'edge','edge_consent':True},stop)

    def test_piper_requires_existing_files(self):
        with self.assertRaises(FileNotFoundError):
            render_speech_file('Hallo', {'speech_engine':'piper','piper_exe':'', 'piper_model':''})

    def test_piper_uses_argument_list_not_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp)/'piper.exe';exe.touch()
            model = Path(tmp)/'voice.onnx';model.touch()
            def fake_run(args,**kwargs):
                self.assertEqual(kwargs.get('encoding'),'utf-8')
                self.assertEqual(kwargs.get('input'),'Hi <&>')
                self.assertIsInstance(args,list)
                Path(args[-1]).write_bytes(b'RIFF_WAVE')
                return types.SimpleNamespace(returncode=0,stderr='')
            with patch('subprocess.run',side_effect=fake_run) as run:
                output=render_speech_file('Hi <&>',{'speech_engine':'piper',
                                       'piper_exe':str(exe),'piper_model':str(model)})
            self.assertTrue(run.called)
            self.assertEqual(output.read_bytes(),b'RIFF_WAVE')
            output.unlink()

    def test_audio_failure_deletes_tmpfile(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'piper.exe';exe.touch()
            model=Path(tmp)/'voice.onnx';model.touch()
            with patch('subprocess.run',return_value=types.SimpleNamespace(returncode=1,stderr='synthetic error')):
                with self.assertRaisesRegex(RuntimeError,'synthetic error'):
                    render_speech_file('Hi',{'speech_engine':'piper',
                                              'piper_exe':str(exe),'piper_model':str(model)})

    def test_transcribe_rejects_incorrect_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.wav'
            with wave.open(str(path),'wb') as w:
                w.setnchannels(2);w.setsampwidth(2);w.setframerate(44100);w.writeframes(b'\0'*16)
            with patch.dict('sys.modules',{'vosk':types.SimpleNamespace(Model=MagicMock(),
                  KaldiRecognizer=MagicMock(),SetLogLevel=lambda n:None)}):
                with self.assertRaisesRegex(ValueError,'16-kHz'):
                    transcribe_wav(path,tmp)

    def test_transcribe_collects_all_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'a.wav'
            with wave.open(str(path),'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*16000)
            recognizer=MagicMock()
            recognizer.AcceptWaveform.return_value=True
            recognizer.Result.return_value=json.dumps({'text':'erster Teil'})
            recognizer.FinalResult.return_value=json.dumps({'text':'letzter Teil'})
            with patch.dict('sys.modules',{'vosk':types.SimpleNamespace(Model=MagicMock(),
                  KaldiRecognizer=MagicMock(return_value=recognizer),SetLogLevel=lambda n:None)}):
                self.assertIn('letzter Teil', transcribe_wav(path,tmp))
                self.assertTrue(transcribe_wav(path,tmp).startswith('erster Teil'))


if __name__=='__main__':
    unittest.main()
