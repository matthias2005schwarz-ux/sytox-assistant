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



# A spoken answer may be interrupted, but ordinary background conversation must
# not be sent to the assistant while its own loudspeaker is active.  An explicit
# wake phrase (or stop command) is required by default to prevent audio echo
# from silently launching PC actions.
_INTERRUPT_RE = re.compile(r'^\s*(?:stopp|stop|halt|anhalten|ruhe|sei still|sytox stopp|sytox stop)\s*[.!?]*$', re.I)


def interruption_command(phrase, free_listening=False):
    """Return (interrupt, next_command) while speech output is active.

    Empty next_command means to stop speaking and wait for a new utterance.
    No next_command is run without a human wake phrase unless the user opted in
    to the less conservative free-listening mode.
    """
    text = ' '.join(str(phrase).split())
    if not text:
        return False, ''
    if _INTERRUPT_RE.fullmatch(text):
        return True, ''
    wake = _WAKE_RE.search(text)
    if wake:
        return True, text[wake.end():].strip(' ,.!?')
    if free_listening and len(text.split()) >= 3:
        return True, text
    return False, ''


def desktop_voice_intent(phrase):
    """Recognize a few safe, local UI intents after normal wake-word routing.

    Return (kind, optional app query). Opening this panel never starts a program
    or changes focus; explicit on-screen approval is still required.
    Unknown requests are passed to the regular AI/agent permission workflow.
    """
    text = ' '.join(str(phrase or '').strip().split()).strip(' ,.!?')
    if not text:
        return None

    if re.fullmatch(
        r'(?:öffne|zeige|zeig|starte)(?:\s+mir)?\s+(?:die\s+)?'
        r'(?:desktop[- ]steuerung|windows[- ]steuerung|pc[- ]steuerung)',
        text, flags=re.I
    ):
        return ('panel', '')

    if re.fullmatch(
        r'(?:zeige|zeig|liste)(?:\s+mir)?\s+(?:die\s+)?'
        r'(?:(?:alle|offenen|geöffneten)\s+)?(?:fenster|windows)',
        text, flags=re.I
    ):
        return ('windows', '')

    match = re.fullmatch(
        r'(?:suche|finde|öffne|starte)(?:\s+mir)?\s+'
        r'(?:(?:die|das|den)\s+)?(?:app|programm|anwendung)\s+(.+)',
        text, flags=re.I
    )
    if match:
        query = match.group(1).strip()
        if 2 <= len(query) <= 80:
            return ('apps', query)
        return None

    # Frequently spoken Windows application names. Still only *search* here.
    aliases = {
        'editor': 'Editor', 'notepad': 'Notepad',
        'rechner': 'Rechner', 'taschenrechner': 'Rechner',
    }
    match = re.fullmatch(
        r'(?:öffne|starte)\s+(?:den\s+|das\s+)?'
        r'(editor|notepad|rechner|taschenrechner)',
        text, flags=re.I
    )
    if match:
        return ('apps', aliases[match.group(1).casefold()])

    if re.fullmatch(
        r'(?:sprachmodus|gesprächsmodus|mikrofon)\s+'
        r'(?:stoppen|beenden|ausschalten)',
        text, flags=re.I
    ):
        return ('stop_listening', '')
    return None


VOSK_DE_MODEL_NAME = 'vosk-model-small-de-0.15'
VOSK_DE_MODEL_URL = 'https://alphacephei.com/vosk/models/' + VOSK_DE_MODEL_NAME + '.zip'


def download_german_voice_model(progress, cancel_event=None, data_dir=None, opener=None):
    """Explicitly requested Vosk download, validated and installed atomically.

    Never unpack network archives directly into the user's live model directory.
    The archive is a fixed, publicly documented Vosk small German model;
    rejects redirected hosts, traversal, links and decompression bombs.
    """
    import os
    import shutil
    import stat
    import tempfile
    import urllib.parse
    import urllib.request
    import zipfile

    cancel_event = cancel_event if cancel_event is not None else threading.Event()
    models = (Path(data_dir) if data_dir is not None else default_data_dir()) / 'models'
    target = models / VOSK_DE_MODEL_NAME
    if (target / 'conf').is_dir():
        progress(100, 'Deutsches Sprachmodell ist bereits eingerichtet.')
        return target
    if cancel_event.is_set():
        raise InterruptedError('Sprachmodell-Download abgebrochen.')
    models.mkdir(parents=True, exist_ok=True)
    progress(0, 'Lade deutsches Sprachmodell von alphacephei.com …')
    request = urllib.request.Request(VOSK_DE_MODEL_URL, headers={'User-Agent': 'SYTOXAssistant/0.3'})
    open_fn = opener or urllib.request.urlopen
    with tempfile.TemporaryDirectory(prefix='.sytox_voice_', dir=str(models)) as tmp:
        staging = Path(tmp)
        archive = staging / 'model.zip'
        with open_fn(request, timeout=35) as response, archive.open('wb') as output:
            actual_url = response.geturl()
            address = urllib.parse.urlsplit(actual_url)
            if address.scheme != 'https' or address.hostname != 'alphacephei.com':
                raise ValueError('Sprachmodell-Download wurde auf eine unerwartete Adresse umgeleitet.')
            expected = int(response.headers.get('Content-Length', '0') or 0)
            if expected and not (1_000_000 <= expected <= 150_000_000):
                raise ValueError('Unerwartete Downloadgröße des Sprachmodells.')
            total = 0
            while True:
                if cancel_event.is_set():
                    raise InterruptedError('Sprachmodell-Download abgebrochen.')
                data = response.read(65536)
                if not data:
                    break
                total += len(data)
                if total > 150_000_000:
                    raise ValueError('Sprachmodell-Archiv ist zu groß.')
                output.write(data)
                if expected:
                    progress(min(85, int(total * 85 / expected)), 'Lade deutsches Sprachmodell …')
            if total < 1_000_000:
                raise ValueError('Sprachmodell-Datei ist unvollständig.')
        progress(86, 'Prüfe Sprachmodell-Archiv …')
        root = staging / VOSK_DE_MODEL_NAME
        with zipfile.ZipFile(archive) as zf:
            entries = zf.infolist()
            if len(entries) > 4500 or sum(info.file_size for info in entries) > 700_000_000:
                raise ValueError('Sprachmodell-Archiv überschreitet sichere Grenzen.')
            for entry in entries:
                name = entry.filename.replace('\\', '/')
                parts = name.split('/')
                mode = entry.external_attr >> 16
                if (not parts or parts[0] != VOSK_DE_MODEL_NAME or
                        any(p in ('..', '') for p in parts[:-1]) or
                        name.startswith('/') or ':' in name or
                        stat.S_ISLNK(mode)):
                    raise ValueError('Sprachmodell-Archiv enthält einen unsicheren Pfad.')
            for index, entry in enumerate(entries):
                if cancel_event.is_set():
                    raise InterruptedError('Sprachmodell-Download abgebrochen.')
                name = entry.filename.replace('\\', '/')
                dest = staging.joinpath(*name.split('/'))
                if entry.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(entry) as source, dest.open('wb') as output:
                        shutil.copyfileobj(source, output, 65536)
                if index % 60 == 0:
                    progress(86 + int(index / max(1, len(entries)) * 12), 'Entpacke Sprachmodell …')
        if not (root / 'conf').is_dir() or not (root / 'am').is_dir():
            raise ValueError('Sprachmodell-Archiv ist unvollständig.')
        if cancel_event.is_set():
            raise InterruptedError('Sprachmodell-Download abgebrochen.')
        if not target.exists():
            root.rename(target)
        if not (target / 'conf').is_dir():
            raise RuntimeError('Sprachmodell konnte nicht eingerichtet werden.')
        progress(100, 'Deutsches Sprachmodell ist bereit.')
        return target

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



def speak_with_windows_sapi(text, stop_event=None):
    """Use Windows COM async speech, polling the cancellation event."""
    import pythoncom
    from win32com.client import Dispatch
    pythoncom.CoInitialize()
    try:
        speaker = Dispatch('SAPI.SpVoice')
        try:
            for candidate in speaker.GetVoices():
                description = str(candidate.GetDescription()).lower()
                if 'german' in description or 'de-de' in description:
                    speaker.Voice = candidate
                    break
        except Exception:
            pass
        speaker.Rate = 1
        speaker.Speak(text, 1)  # SVSFlagsAsync
        while not speaker.WaitUntilDone(100):
            if stop_event and stop_event.is_set():
                speaker.Speak('', 3)  # SVSFlagsAsync | SVSFPurgeBeforeSpeak
                return
        if stop_event and stop_event.is_set():
            speaker.Speak('', 3)
    finally:
        pythoncom.CoUninitialize()

def speak(text, piper_exe='', piper_model='', stop_event=None):
    """Interruptible Windows SAPI playback, with a platform fallback.

    A regular ``pyttsx3.runAndWait`` call blocks without observing stop_event.
    Windows SAPI's async mode lets us purge its queue within 100 ms when the
    user clicks Stop or says a wake phrase during playback.
    """
    text = spoken_text(text)
    if not text or (stop_event and stop_event.is_set()):
        return
    if piper_exe and piper_model:
        import winsound
        path = render_speech_file(text, {'speech_engine': 'piper', 'piper_exe': piper_exe,
                                         'piper_model': piper_model}, stop_event)
        try:
            if not (stop_event and stop_event.is_set()):
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
        finally:
            path.unlink(missing_ok=True)
        return
    if __import__('os').name == 'nt':
        try:
            speak_with_windows_sapi(text, stop_event)
        except ImportError:
            pass  # Some minimal Windows environments lack pywin32.
        else:
            return
    import pyttsx3
    engine = pyttsx3.init()
    try:
        for available in engine.getProperty('voices'):
            lang = ' '.join(str(v) for v in available.languages).lower()
            if 'de' in lang or 'german' in available.name.lower():
                engine.setProperty('voice', available.id)
                break
        engine.setProperty('rate', 192)
        if stop_event and stop_event.is_set():
            return
        engine.say(text)
        engine.runAndWait()  # Fallback for non-Windows systems; may not interrupt.
    finally:
        engine.stop()
