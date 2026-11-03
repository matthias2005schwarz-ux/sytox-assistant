"""Voice handling: local Vosk recognition, conversation routing and opt-in speech.

Microphone contents stay local with Vosk. Edge voice synthesis (if explicitly
selected) sends the spoken response text to Microsoft's online TTS service.
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

from .storage import default_data_dir

_WAKE_RE = re.compile(r"\b(?:hey|hei|he)\s+(?:sytox|saitox|seitox|sytoks|seitoks)\b", re.I)


class VoiceTurnRouter:
    """Accept a wake phrase and allow short follow-ups after a spoken reply.

    Switching on the hands-free mode is a user action. A valid wake phrase is
    required by default; there is deliberately no permanent silent wake bypass.
    """

    def __init__(self, require_wake=True, follow_up_seconds=25, clock=None):
        self.require_wake = bool(require_wake)
        self.follow_up_seconds = max(0, min(float(follow_up_seconds), 120))
        self._clock = clock or time.monotonic
        self._armed_until = 0.0
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self._armed_until = 0

    def allow_follow_up(self):
        with self._lock:
            self._armed_until = self._clock() + self.follow_up_seconds

    def command_for(self, phrase):
        text = ' '.join(str(phrase).strip().split())
        if not text:
            return None
        with self._lock:
            now = self._clock()
            hit = _WAKE_RE.search(text)
            if hit:
                self._armed_until = now + max(14, self.follow_up_seconds)
                command = text[hit.end():].strip(' ,.!?')
                return command or None
            if self.require_wake and now >= self._armed_until:
                return None
            self._armed_until = now + self.follow_up_seconds
            return text


def spoken_text(text, limit=2200):
    """Turn a chat answer into pronounceable prose rather than reading Markdown."""
    raw = str(text)
    raw = re.sub(r'```[\s\S]*?```', ' Codebeispiel ausgelassen. ', raw)
    raw = re.sub(r'\[([^\]\n]+)\]\(https?://[^)]+\)', r'\1', raw)
    raw = re.sub(r'https?://\S+', 'ein Link', raw)
    raw = re.sub(r'`([^`\n]+)`', r'\1', raw)
    raw = re.sub(r'(?m)^\s{0,3}#{1,6}\s*', '', raw)
    raw = re.sub(r'(?m)^\s*[-*]\s+', '', raw)
    raw = re.sub(r'[*_]{2,}', '', raw)
    clean = ' '.join(raw.split())
    if len(clean) > limit:
        cut = clean[:limit]
        boundary = max(cut.rfind('. '), cut.rfind('! '), cut.rfind('? '))
        if boundary >= limit // 2:
            cut = cut[:boundary+1]
        else:
            cut = cut.rsplit(' ', 1)[0] + ' …'
        return cut
    return clean


def record_until(stop_event, path=None, sample_rate=16000):
    import sounddevice as sd
    dest = Path(path) if path else default_data_dir() / 'voice_memos' / (datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.wav')
    dest.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    with sd.RawInputStream(samplerate=sample_rate, channels=1, dtype='int16', blocksize=4096,
                           callback=lambda indata,frames_count,t,status:frames.append(bytes(indata))):
        while not stop_event.wait(.1):
            pass
    with wave.open(str(dest), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b''.join(frames))
    return dest


def transcribe_wav(wav_path, vosk_model_path):
    from vosk import Model, KaldiRecognizer, SetLogLevel
    SetLogLevel(-1)
    path = Path(vosk_model_path)
    if not path.is_dir():
        raise FileNotFoundError('Bitte in den Einstellungen einen entpackten Vosk-Deutsch-Modellordner auswählen.')
    with wave.open(str(wav_path), 'rb') as reader:
        if reader.getnchannels() != 1 or reader.getframerate() != 16000 or reader.getsampwidth() != 2:
            raise ValueError('Für die Spracherkennung wird 16-kHz-Mono-PCM benötigt.')
        recognizer = KaldiRecognizer(Model(str(path)), 16000)
        parts = []
        while data := reader.readframes(4000):
            if recognizer.AcceptWaveform(data):
                text = json.loads(recognizer.Result()).get('text', '').strip()
                if text:
                    parts.append(text)
        ending = json.loads(recognizer.FinalResult()).get('text', '').strip()
        if ending:
            parts.append(ending)
    return ' '.join(parts)


def render_speech_file(text, settings, cancel_event=None):
    """Produce a WAV (local Piper) or MP3 (opt-in online Edge TTS).

    Caller owns the temporary output and must delete it after playback.
    """
    text = spoken_text(text)
    if not text:
        raise ValueError('Kein Text zum Vorlesen vorhanden.')
    cancel_event = cancel_event or threading.Event()
    engine = settings.get('speech_engine', 'windows')
    if engine not in ('piper', 'edge'):
        raise ValueError('Dateiausgabe unterstützt nur Piper oder Edge; Windows spricht direkt.')
    if cancel_event.is_set():
        raise InterruptedError('Sprachausgabe abgebrochen.')
    suffix = '.mp3' if engine == 'edge' else '.wav'
    with tempfile.NamedTemporaryFile(prefix='sytox_voice_', suffix=suffix, delete=False) as output:
        dest = Path(output.name)
    try:
        if engine == 'piper':
            executable = Path(settings.get('piper_exe', ''))
            model = Path(settings.get('piper_model', ''))
            if not executable.is_file() or not model.is_file():
                raise FileNotFoundError('Piper-Programm und Piper-Stimmenmodell müssen in den Einstellungen gewählt werden.')
            result = subprocess.run([str(executable), '--model', str(model), '--output_file', str(dest)],
                                    input=text, encoding='utf-8', capture_output=True, timeout=180)
            if result.returncode:
                raise RuntimeError('Piper fehlgeschlagen: ' + (result.stderr or '')[-300:])
        else:
            if not settings.get('edge_consent', False):
                raise PermissionError('Online-Stimme nicht freigegeben. Bitte in den Einstellungen ausdrücklich zustimmen.')
            voice = settings.get('edge_voice', 'de-DE-KatjaNeural')
            rate = settings.get('edge_rate', '+8%')
            if not re.fullmatch(r'[+-]\d{1,2}%', rate):
                raise ValueError('Ungültige Sprechgeschwindigkeit.')
            if not re.fullmatch(r'[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural', voice):
                raise ValueError('Ungültige Online-Stimme.')
            try:
                import edge_tts
            except ImportError as e:
                raise RuntimeError('Online-Stimme benötigt edge-tts (pip install edge-tts).') from e
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(dest)))
        if cancel_event.is_set():
            raise InterruptedError('Sprachausgabe abgebrochen.')
        if dest.stat().st_size == 0:
            raise RuntimeError('Keine Audiodaten erzeugt.')
        return dest
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def speak(text, piper_exe='', piper_model='', stop_event=None):
    """Legacy offline speech path for Windows SAPI / pyttsx3.

    Piper playback is now handled through render_speech_file + Qt multimedia;
    this helper retains compatibility with previous callers.
    """
    text = spoken_text(text)
    if not text or (stop_event and stop_event.is_set()):
        return
    if piper_exe and piper_model:
        import winsound
        path = render_speech_file(text, {'speech_engine': 'piper', 'piper_exe': piper_exe,
                                         'piper_model': piper_model}, stop_event)
        try:
            if stop_event and stop_event.is_set():
                return
            winsound.PlaySound(str(path), winsound.SND_FILENAME)
        finally:
            path.unlink(missing_ok=True)
        return
    import pyttsx3
    engine = pyttsx3.init()
    try:
        voices = engine.getProperty('voices')
        for voice in voices:
            lang = ' '.join(str(v) for v in voice.languages).lower()
            if 'de' in lang or 'german' in voice.name.lower():
                engine.setProperty('voice', voice.id)
                break
        engine.setProperty('rate', 192)
        if stop_event and stop_event.is_set():
            return
        engine.say(text)
        engine.runAndWait()
    finally:
        engine.stop()
