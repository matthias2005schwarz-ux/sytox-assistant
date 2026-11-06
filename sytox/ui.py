"""SYTOX desktop interface: local-first chats, voice, agent tasks and approvals."""
from __future__ import annotations
import html
import json
import re
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer, QUrl, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QKeyEvent, QKeySequence, QShortcut, QTextCursor, QDesktopServices, QLinearGradient, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,QWidget,QMainWindow,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QTextEdit,QPlainTextEdit,QListWidget,QListWidgetItem,QScrollArea,QSplitter,
    QMessageBox,QFileDialog,QLineEdit,QDialog,QFormLayout,QCheckBox,QComboBox,
    QSystemTrayIcon,QMenu,QInputDialog,QSpinBox,QFrame,QProgressBar, QGraphicsOpacityEffect, QGraphicsDropShadowEffect
)
from .theme import STYLE as QSS, BACKGROUND as BG, PANEL, SURFACE, ACCENT as RED, TEXT as LIGHT, MUTED
from .agent import Agent,OllamaClient
from .ram_saver import keep_alive_for_config, normalized_keep_alive_seconds
from .task_eta import task_eta
from .task_queue import is_change_request
from .model_router import select_chat_model, wants_screen, requires_agent
from .screen_vision import describe_screen
from .storage import Store,default_data_dir
from .voice_features import record_until,transcribe_wav,speak,render_speech_file,VoiceTurnRouter,interruption_command,download_german_voice_model, desktop_voice_intent, agent_status_intent
from .desktop_ui import DesktopControlDialog
from .parallel_chat import ParallelChatDialog, ParallelReplyWorker
from .chat_content import MessageLabel, fenced_code_blocks
from .updater import (check_for_update, download_verified_installer,
                      download_verified_portable, is_installed_app,
                      schedule_installer, schedule_portable_update, RELEASES_PAGE)
from .work_intents import work_intent
from .voice_diagnostics import microphone_probe
from .ollama_setup import OllamaStatus, check_ollama_status, model_pull_command, OLLAMA_DOWNLOAD
from .ollama_installer import MODEL_CHOICES, SetupCancelled, setup_local_ollama, valid_local_endpoint


def task_status_text(status):
    return {
        'running': 'Aufgabe läuft', 'done': 'Aufgabe abgeschlossen',
        'paused': 'Aufgabe pausiert', 'failed': 'Aufgabe fehlgeschlagen',
        'time_elapsed': 'Arbeitszeit beendet', 'cancelled': 'Aufgabe abgebrochen',
    }.get(status, 'Aufgabe beendet')


def brand_asset(filename):
    """Resolve bundled artwork both in development and in the frozen Windows app."""
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'assets' / filename


class BrandMark(QWidget):
    """Use the supplied metallic SYTOX application icon inside the sidebar."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 50)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._pixmap = QPixmap(str(brand_asset('sytox-app.png')))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self._pixmap.isNull():
            painter.drawPixmap(self.rect(), self._pixmap)
        else:
            painter.setPen(QColor('#E0525A'))
            painter.drawText(self.rect(), Qt.AlignCenter, 'SYTOX')
        painter.end()


def brand_banner(width=220):
    """Display the supplied SYTOX KI wordmark, retaining its original aspect ratio."""
    banner = QPixmap(str(brand_asset('sytox-banner.png')))
    if banner.isNull():
        return None
    label = QLabel()
    label.setObjectName('brandBanner')
    label.setPixmap(banner.scaledToWidth(width, Qt.SmoothTransformation))
    label.setAlignment(Qt.AlignCenter)
    label.setAccessibleName('SYTOX KI Logo')
    return label


def microphone_icon():
    """Crisp native painted microphone; avoids platform-specific emoji rendering."""
    pixmap = QPixmap(28, 28)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor('#F8EBEF'), 2.0, Qt.SolidLine,
                        Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(11, 4, 6, 13, 3, 3)
    painter.drawArc(7, 7, 14, 14, 180 * 16, 180 * 16)
    painter.drawLine(14, 21, 14, 25)
    painter.drawLine(10, 25, 18, 25)
    painter.end()
    return QIcon(pixmap)


def subtle_glow(widget, color='#92303E', radius=23, opacity=135):
    """Create restrained red illumination, never a blocking animation."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(radius)
    effect.setColor(QColor(color))
    effect.setOffset(0, 1)
    widget.setGraphicsEffect(effect)
    return effect


def app_icon():
    # The supplied icon is the first choice for window chrome and system tray.
    for filename in ('sytox-app.png', 'sytox.ico'):
        icon_file = brand_asset(filename)
        if icon_file.exists():
            return QIcon(str(icon_file))
    pix=QPixmap(64,64);pix.fill(Qt.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(178,37,52));p.setPen(Qt.NoPen);p.drawRoundedRect(3,3,58,58,15,15)
    p.setPen(QColor('#ffffff'));f=QFont('Segoe UI',30,QFont.Bold);p.setFont(f)
    p.drawText(pix.rect(),Qt.AlignCenter,'S');p.end()
    return QIcon(pix)


class InputBox(QTextEdit):
    send=Signal()
    def keyPressEvent(self,e:QKeyEvent):
        if e.key() in (Qt.Key_Return,Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.send.emit();e.accept();return
        super().keyPressEvent(e)


class Worker(QThread):
    log_line=Signal(str,str)
    approval_request=Signal(str,str,object)
    completed=Signal(object)

    def __init__(self,store,chat_id,settings,mode='once',hours=1.0,task_id=None):
        super().__init__()
        self.store=store;self.chat_id=chat_id;self.settings=settings
        self.mode=mode;self.hours=hours;self.task_id=task_id
        self.stop_event=threading.Event()

    def request_approval(self,label,description):
        gate=threading.Event();payload={'gate':gate,'allowed':False}
        self.approval_request.emit(label,description,payload)
        while not gate.wait(.15):
            if self.stop_event.is_set():return False
        return payload['allowed']

    def run(self):
        try:
            messages = self.store.messages(self.chat_id, limit=24)
            question = next((item['content'] for item in reversed(messages)
                             if item['role'] == 'user'), '')
            model, route = select_chat_model(question, self.settings, self.mode)
            self.log_line.emit('System', 'Verwendetes Modell: ' + model
                               + (' (Projekt)' if route == 'project' else ' (Schnellchat)'))
            screen_context = ''
            if wants_screen(question):
                self.log_line.emit('Status', 'Bildschirm wird auf Wunsch analysiert …')
                screen_context = describe_screen(question, self.settings, self.stop_event)
            a=Agent(self.store,model,self.settings['ollama_url'],
                    self.settings['workspace'],self.request_approval,self.log_line.emit,self.stop_event,
                    self.settings.get('gmail_client_secrets',''),
                    ram_keep_alive=keep_alive_for_config(self.settings),
                    screen_context=screen_context)
            result=a.run(self.chat_id,self.mode,self.hours,self.task_id)
            self.completed.emit(result)
        except Exception as e:
            self.completed.emit({'status':'failed','content':f'{type(e).__name__}: {e}','task_id':self.task_id})


class UpdateCheckWorker(QThread):
    result_ready = Signal(object, str)

    def run(self):
        try:
            self.result_ready.emit(check_for_update(), '')
        except Exception as exc:
            self.result_ready.emit(None, str(exc))


class UpdateDownloadWorker(QThread):
    progress = Signal(int)
    result_ready = Signal(str, str)

    def __init__(self, update):
        super().__init__()
        self.update = update

    def run(self):
        try:
            if self.update.has_portable:
                path = download_verified_portable(self.update, self.progress.emit)
            else:
                path = download_verified_installer(self.update, self.progress.emit)
            self.result_ready.emit(str(path), '')
        except Exception as exc:
            self.result_ready.emit('', str(exc))


class VoiceRecorder(QThread):
    finished_note=Signal(str,str)
    def __init__(self,model):
        super().__init__();self.stop_event=threading.Event();self.model=model
    def run(self):
        try:
            path=record_until(self.stop_event)
            if not self.model:
                self.finished_note.emit(str(path),'')
            else:
                try:text=transcribe_wav(path,self.model)
                except Exception as e:text='[Spracherkennung fehlgeschlagen: '+str(e)+']'
                self.finished_note.emit(str(path),text)
        except Exception as e:
            self.finished_note.emit('','[Mikrofonfehler: '+str(e)+']')


class WakeListener(QThread):
    """Local speech listener with wake word and timed conversational follow-ups."""
    wake_command = Signal(str)
    interrupted = Signal(str)
    error = Signal(str)
    hearing = Signal(str)

    def __init__(self, model_path, require_wake=True, follow_up_seconds=25,
                 mute_event=None, speaking_event=None, allow_interruption=True):
        super().__init__()
        self.model_path = model_path
        self.stop_event = threading.Event()
        self.mute_event = mute_event if mute_event is not None else threading.Event()
        self.speaking_event = speaking_event if speaking_event is not None else threading.Event()
        self.allow_interruption = bool(allow_interruption)
        self.router = VoiceTurnRouter(require_wake, follow_up_seconds)

    def allow_follow_up(self):
        self.router.allow_follow_up()

    def run(self):
        import queue
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            recognizer = KaldiRecognizer(Model(self.model_path), 16000)
            audio_queue = queue.Queue(maxsize=16)
            def on_audio(data, frame_count, timing, status):
                if self.mute_event.is_set() and not (
                        self.allow_interruption and self.speaking_event.is_set()):
                    return
                try:
                    audio_queue.put_nowait(bytes(data))
                except queue.Full:
                    pass

            muted_before = False
            was_speaking = False
            barge_latched = False
            with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16',
                                   callback=on_audio, blocksize=4000):
                while not self.stop_event.is_set():
                    speaking = self.speaking_event.is_set()
                    if self.mute_event.is_set() and not (self.allow_interruption and speaking):
                        muted_before = True
                        while True:
                            try: audio_queue.get_nowait()
                            except queue.Empty: break
                        self.stop_event.wait(.06)
                        continue
                    if muted_before or (was_speaking and not speaking):
                        recognizer.Reset()  # no fragments from a muted/previous utterance
                        muted_before = False
                    if not speaking:
                        barge_latched = False
                    was_speaking = speaking
                    try:
                        audio = audio_queue.get(timeout=.25)
                    except queue.Empty:
                        continue
                    if not recognizer.AcceptWaveform(audio):
                        continue
                    phrase = json.loads(recognizer.Result()).get('text', '').strip()
                    if phrase:
                        self.hearing.emit(phrase)  # Diagnostic only: never stored or uploaded.
                    if speaking:
                        interrupt, next_command = interruption_command(
                            phrase, free_listening=not self.router.require_wake)
                        if interrupt and not barge_latched:
                            barge_latched = True
                            self.router.allow_follow_up()
                            self.mute_event.set()
                            self.interrupted.emit(next_command)
                        continue
                    command = self.router.command_for(phrase)
                    if command:
                        # Do not capture a second command while Qt is processing this turn.
                        self.mute_event.set()
                        self.wake_command.emit(command)
        except Exception as e:
            self.error.emit(f'Spracherkennung: {type(e).__name__}: {e}')


class MicrophoneProbeWorker(QThread):
    level = Signal(float)
    completed = Signal(object)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.stop_event = threading.Event()

    def run(self):
        try:
            self.completed.emit(microphone_probe(self.level.emit, self.stop_event))
        except Exception as exc:
            self.error.emit(f'{type(exc).__name__}: {exc}')


class VoiceDiagnosticsDialog(QDialog):
    """On-device guided hardware test; does not send any commands to the Agent."""

    def __init__(self, model_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle('SYTOX · Mikrofon und Unterbrechung prüfen')
        self.resize(590, 430)
        self.model_path = str(model_path or '')
        self.mic_worker = None
        self.listener = None
        self.speaker = None
        self.speaking = threading.Event()
        self.muted = threading.Event()
        self.phase = 'idle'
        self.mic_ok = False
        self.wake_ok = False
        self.interrupt_ok = False
        self.interrupt_pending = False
        layout = QVBoxLayout(self)
        heading = QLabel('SPRACHDIAGNOSE AUF DEINEM PC')
        heading.setStyleSheet('font-weight:800;font-size:18px')
        layout.addWidget(heading)
        explain = QLabel('Die Tests nutzen dein echtes Mikrofon. Das Audio wird ausschließlich lokal verarbeitet, nicht gespeichert und nicht hochgeladen. Alle Tests starten nur nach deinem Klick.')
        explain.setWordWrap(True)
        layout.addWidget(explain)
        self.step_label = QLabel('1. Mikrofontest: Sprich fünf Sekunden normal ins Mikrofon.')
        self.step_label.setWordWrap(True)
        layout.addWidget(self.step_label)
        self.meter = QProgressBar()
        self.meter.setRange(0, 100)
        self.meter.setValue(0)
        self.meter.setFormat('Mikrofonsignal %p%')
        layout.addWidget(self.meter)
        self.result = QLabel('Noch nicht getestet.')
        self.result.setWordWrap(True)
        self.result.setObjectName('muted')
        layout.addWidget(self.result)
        self.test_mic = QPushButton('1  Mikrofon testen (5 Sekunden)')
        self.test_mic.clicked.connect(self.start_mic_test)
        layout.addWidget(self.test_mic)
        self.test_wake = QPushButton('2  „Hey Sytox, Test“ erkennen')
        self.test_wake.clicked.connect(self.start_wake_test)
        self.test_wake.setEnabled(False)
        layout.addWidget(self.test_wake)
        self.test_interrupt = QPushButton('3  Sprachausgabe mit „Stopp“ unterbrechen')
        self.test_interrupt.clicked.connect(self.start_interrupt_test)
        self.test_interrupt.setEnabled(False)
        layout.addWidget(self.test_interrupt)
        self.close_button = QPushButton('Schließen')
        self.close_button.clicked.connect(self.close)
        layout.addWidget(self.close_button)

    def _model_ready(self):
        if not self.model_path or not (Path(self.model_path) / 'conf').is_dir():
            self.result.setText('Für die Sprachtests fehlt das deutsche Vosk-Modell. Schließe diesen Dialog und klicke auf „Deutsches Sprachmodell laden“.')
            return False
        return True

    def start_mic_test(self):
        if self.mic_worker and self.mic_worker.isRunning():
            return
        if self.listener and self.listener.isRunning():
            self._stop_listener()
        self.phase = 'microphone'
        self.mic_ok = self.wake_ok = self.interrupt_ok = False
        self.test_mic.setEnabled(False)
        self.test_wake.setEnabled(False)
        self.test_interrupt.setEnabled(False)
        self.result.setText('Mikrofon geöffnet. Sprich jetzt fünf Sekunden laut und deutlich.')
        self.meter.setValue(0)
        worker = MicrophoneProbeWorker()
        self.mic_worker = worker
        worker.level.connect(lambda level: self.meter.setValue(min(100, int(level * 12))))
        worker.completed.connect(self._mic_finished)
        worker.error.connect(self._mic_error)
        worker.finished.connect(lambda: self.test_mic.setEnabled(True))
        worker.start()

    def _mic_finished(self, data):
        self.mic_ok = bool(data['signal_detected'])
        self.result.setText(f'Mikrofon: {data["device"]}  ·  RMS-Spitze: {data["peak_percent"]:.2f}%  ·  '
                            + ('Signal erkannt.' if self.mic_ok else 'Signal zu leise. Mikrofon-Lautstärke und Windows-Berechtigung prüfen.'))
        self.test_wake.setEnabled(self.mic_ok)
        self.phase = 'idle'

    def _mic_error(self, message):
        self.result.setText('Mikrofontest fehlgeschlagen: ' + message + '\nWindows → Einstellungen → Datenschutz und Sicherheit → Mikrofon: Desktop-Apps zulassen.')
        self.phase = 'idle'

    def _ensure_listener(self):
        if not self._model_ready():
            return False
        if self.listener and self.listener.isRunning():
            return True
        self.muted.clear()
        self.speaking.clear()
        listener = WakeListener(self.model_path, require_wake=True,
                                mute_event=self.muted, speaking_event=self.speaking,
                                allow_interruption=True)
        self.listener = listener
        listener.hearing.connect(self._heard_phrase)
        listener.wake_command.connect(self._wake_passed)
        listener.interrupted.connect(self._interrupted)
        listener.error.connect(self._listen_error)
        listener.start()
        return True

    def start_wake_test(self):
        if not self.mic_ok or not self._ensure_listener():
            return
        self.phase = 'wake'
        self.wake_ok = False
        self.test_interrupt.setEnabled(False)
        self.result.setText('Sag jetzt: „Hey Sytox, Test“ und warte anschließend kurz auf die Erkennung. Es werden keine PC-Befehle ausgeführt.')

    def _heard_phrase(self, phrase):
        if self.phase == 'wake':
            self.result.setText('Gehört: ' + phrase[:150] + '\nSag „Hey Sytox, Test“, falls noch nicht erkannt.')
        elif self.phase == 'interrupt':
            self.result.setText('Sprachausgabe läuft. Erkannt: ' + phrase[:130])

    def _wake_passed(self, command):
        # Never forward a diagnostic utterance to chat, PC tools or the Agent.
        if self.phase == 'wake':
            self.wake_ok = True
            self.phase = 'ready'
            self.test_interrupt.setEnabled(True)
            self.result.setText('Spracherkennung erfolgreich: „Hey Sytox“ wurde verstanden. Jetzt Schritt 3 starten.')

    def start_interrupt_test(self):
        if not self.wake_ok or not self._ensure_listener():
            return
        if self.speaker and self.speaker.isRunning():
            return
        self.phase = 'interrupt'
        self.interrupt_ok = False
        self.interrupt_pending = False
        self.muted.set()  # During playback only explicit stop/wake interrupts.
        self.speaking.set()
        self.test_interrupt.setEnabled(False)
        self.result.setText('SYTOX spricht gleich. Sag während der Stimme deutlich „Stopp“, danach kurz still sein. Die Antwort selbst enthält kein Stoppwort.')
        long_text = ('Dies ist eine Testansage für die freihändige Sprachbedienung. '
                     'Du kannst eine Antwort jederzeit unterbrechen. '
                     'Während ich hier weitere Sätze vorlese, kannst du dich bemerkbar machen. '
                     'Dieser Test überprüft die Zusammenarbeit von Mikrofon, Spracherkennung und Tonausgabe. ') * 5
        speaker = Speaker(long_text)
        self.speaker = speaker
        speaker.error.connect(self._speaker_error)
        speaker.finished.connect(self._speaker_finished)
        speaker.start()

    def _interrupted(self, command):
        if self.phase != 'interrupt':
            return
        self.interrupt_pending = bool(self.speaker and self.speaker.isRunning())
        if self.speaker:
            self.speaker.stop_event.set()
        self.result.setText('„Stopp“ erkannt. Prüfe, ob die Windows-Sprachausgabe tatsächlich beendet wird …')
        QTimer.singleShot(1800, self._verify_interrupted)

    def _verify_interrupted(self):
        if self.phase != 'interrupt' or not self.interrupt_pending:
            return
        if self.speaker and self.speaker.isRunning():
            self.result.setText('Unterbrechung erkannt, aber die Sprachausgabe läuft weiter. Audiotreiber/SAPI prüfen.')
        else:
            self.interrupt_ok = True
            self.result.setText('Erfolgreich: Mikrofon hat „Stopp“ erkannt und die Windows-Sprachausgabe wurde gestoppt. Bitte zusätzlich prüfen, ob du sie wirklich verstummen gehört hast.')
        self.phase = 'ready'
        self.muted.clear()
        self.speaking.clear()
        self.test_interrupt.setEnabled(True)

    def _speaker_finished(self):
        if self.phase == 'interrupt' and not self.interrupt_pending:
            self.result.setText('Sprachausgabe endete ohne erkanntes „Stopp“. Versuche Schritt 3 erneut; Kopfhörer verhindern Lautsprecher-Echo.')
            self.phase = 'ready'
            self.speaking.clear()
            self.muted.clear()
            self.test_interrupt.setEnabled(True)

    def _speaker_error(self, message):
        self.result.setText('Windows-Stimme fehlgeschlagen: ' + message)
        self.phase = 'ready'
        self.speaking.clear()
        self.muted.clear()
        self.test_interrupt.setEnabled(True)

    def _listen_error(self, error):
        self.result.setText('Spracherkennung fehlgeschlagen: ' + error)
        self.phase = 'idle'
        self.test_interrupt.setEnabled(False)

    def _stop_listener(self):
        if self.listener and self.listener.isRunning():
            self.listener.stop_event.set()
            self.listener.wait(3000)

    def closeEvent(self, event):
        if self.mic_worker and self.mic_worker.isRunning():
            self.mic_worker.stop_event.set()
            if not self.mic_worker.wait(2500):
                event.ignore()
                self.result.setText('Mikrofontest wird beendet. Bitte gleich erneut schließen.')
                return
        if self.speaker and self.speaker.isRunning():
            self.speaker.stop_event.set()
            if not self.speaker.wait(2500):
                event.ignore()
                self.result.setText('Sprachausgabe wird beendet. Bitte gleich erneut schließen.')
                return
        self._stop_listener()
        if self.listener and self.listener.isRunning():
            event.ignore()
            return
        self.speaking.clear()
        self.muted.clear()
        event.accept()


class VoiceModelDownload(QThread):
    progress_update = Signal(int, str)
    installed = Signal(str)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()

    def run(self):
        try:
            dest = download_german_voice_model(self.progress_update.emit, self.cancel_event)
            self.installed.emit(str(dest))
        except InterruptedError:
            self.error.emit('Sprachmodell-Download wurde abgebrochen.')
        except Exception as exc:
            self.error.emit(f'{type(exc).__name__}: {exc}')


class Speaker(QThread):
    error = Signal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text
        self.stop_event = threading.Event()

    def run(self):
        try:
            speak(self.text, stop_event=self.stop_event)
        except Exception as e:
            self.error.emit(f'Windows-Stimme: {type(e).__name__}: {e}')


class SpeechSynthesizer(QThread):
    audio_ready = Signal(str)
    error = Signal(str)

    def __init__(self, text, settings):
        super().__init__()
        self.text = text
        self.settings = settings
        self.stop_event = threading.Event()

    def run(self):
        try:
            output = render_speech_file(self.text, self.settings, self.stop_event)
            self.audio_ready.emit(str(output))
        except InterruptedError:
            return
        except Exception as e:
            self.error.emit(f'Sprachausgabe: {type(e).__name__}: {e}')


class OllamaProbe(QThread):
    """Avoid freezing the Qt event loop while checking a local model server."""
    checked = Signal(object)

    def __init__(self, url: str, model: str):
        super().__init__()
        self.url = url
        self.model = model

    def run(self):
        self.checked.emit(check_ollama_status(self.url, self.model))


class OllamaSetupWorker(QThread):
    """Blocking model download and package installation stay off Qt's UI thread."""
    progress = Signal(str, object)
    result = Signal(bool, str)

    def __init__(self, url: str, model: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.model = model
        self.cancel_event = threading.Event()

    def run(self):
        try:
            model = setup_local_ollama(self.url, self.model, self.cancel_event,
                                       self.progress.emit)
            self.result.emit(True, model)
        except SetupCancelled:
            self.result.emit(False, 'Einrichtung abgebrochen. Bereits geladene Teile bleiben erhalten.')
        except Exception as exc:
            self.result.emit(False, f'{type(exc).__name__}: {exc}')


class OllamaHelpDialog(QDialog):
    """User-consented Windows setup, with cancellable background model downloads."""
    def __init__(self, model: str, status: OllamaStatus | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('SYTOX · Lokale KI einrichten')
        self.resize(610, 430)
        self.worker = None
        self.installed_model = None
        self._pending_accept = False
        self.url = parent.config.get('ollama_url', 'http://localhost:11434') if parent else 'http://localhost:11434'
        lay = QVBoxLayout(self)
        heading = QLabel('DEINE LOKALE KI EINRICHTEN')
        heading.setStyleSheet('font-size:19px;font-weight:800;color:#F0F1F6')
        lay.addWidget(heading)
        details = QLabel(status.details if status else 'Wähle dein Modell und starte die Einrichtung.')
        details.setWordWrap(True)
        lay.addWidget(details)
        guide = QLabel('SYTOX kann Ollama über den Windows-Paketmanager installieren, im '
                       'Hintergrund starten und dein gewünschtes KI-Modell herunterladen. '
                       'Dafür ist Internet erforderlich. Das Modell wird anschließend lokal verwendet.')
        guide.setWordWrap(True)
        guide.setStyleSheet('color:#C3C7D3;line-height:1.4')
        lay.addWidget(guide)
        lay.addWidget(QLabel('KI-Modell auswählen'))
        self.model_choice = QComboBox()
        self.model_choice.setEditable(True)
        for label, value in MODEL_CHOICES:
            self.model_choice.addItem(label, value)
        initial = self.model_choice.findData(model)
        if initial >= 0:
            self.model_choice.setCurrentIndex(initial)
        else:
            self.model_choice.setEditText(model)
        self.model_choice.currentTextChanged.connect(self._refresh_command)
        lay.addWidget(self.model_choice)
        self.command_box = QLineEdit()
        self.command_box.setReadOnly(True)
        lay.addWidget(self.command_box)
        self._refresh_command()
        buttons = QHBoxLayout()
        download = QPushButton('Offizielle Ollama-Webseite')
        download.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(OLLAMA_DOWNLOAD)))
        buttons.addWidget(download)
        copy_button = QPushButton('Befehl kopieren')
        copy_button.clicked.connect(lambda: QApplication.clipboard().setText(self.command_box.text()))
        buttons.addWidget(copy_button)
        lay.addLayout(buttons)
        self.progress_label = QLabel('Bereit zum Einrichten.')
        self.progress_label.setWordWrap(True)
        self.progress_label.setObjectName('muted')
        lay.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        lay.addWidget(self.progress_bar)
        action_row = QHBoxLayout()
        self.install_button = QPushButton('◈  Ollama + Modell einrichten')
        self.install_button.setObjectName('primary')
        self.install_button.clicked.connect(self.begin_install)
        action_row.addWidget(self.install_button)
        self.cancel_button = QPushButton('Schließen')
        self.cancel_button.clicked.connect(self.reject)
        action_row.addWidget(self.cancel_button)
        lay.addLayout(action_row)

    def chosen_model(self):
        index = self.model_choice.currentIndex()
        # The combobox contains friendly labels; preserve the exact underlying model tag.
        if index >= 0 and self.model_choice.currentText() == self.model_choice.itemText(index):
            return self.model_choice.itemData(index)
        return self.model_choice.currentText().strip()

    def _refresh_command(self, *_):
        try:
            self.command_box.setText(model_pull_command(self.chosen_model()))
        except ValueError:
            self.command_box.setText('Ungültiger Modellname')

    def begin_install(self):
        if self.worker and self.worker.isRunning():
            return
        try:
            address = valid_local_endpoint(self.url)
            command = model_pull_command(self.chosen_model())
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, 'KI-Einrichtung', str(exc))
            return
        answer = QMessageBox.question(
            self, 'KI lokal einrichten',
            'SYTOX wird – falls nötig – Ollama über den Windows-Paketmanager '
            'installieren und anschließend das Modell „' + self.chosen_model() + '“ laden.\n\n'
            'Dafür werden mehrere GB freier Speicherplatz und Internet benötigt. '
            'Die Installation kann einige Minuten dauern. Fortfahren?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._pending_accept = False
        self.install_button.setEnabled(False)
        self.model_choice.setEnabled(False)
        self.cancel_button.setText('Abbrechen')
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText('Einrichtung startet …')
        self.worker = OllamaSetupWorker(address, self.chosen_model(), self)
        self.worker.progress.connect(self._progress)
        self.worker.result.connect(self._result)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _progress(self, message, percent):
        self.progress_label.setText(str(message))
        if percent is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(int(percent))

    def _result(self, success, message):
        if success:
            self.installed_model = message
            self._pending_accept = True
            self.progress_label.setText('Lokale KI ist bereit!')
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
        else:
            self.progress_label.setText(str(message))
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)

    def _worker_finished(self):
        self.install_button.setEnabled(True)
        self.model_choice.setEnabled(True)
        self.cancel_button.setText('Schließen')
        if self._pending_accept:
            super().accept()

    def reject(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText('Einrichtung wird angehalten …')
            return
        super().reject()


class SettingsDialog(QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.setWindowTitle('Einstellungen');self.setMinimumWidth(560)
        self.original=settings.copy()
        form=QFormLayout(self)
        self.model=QLineEdit(settings['model'])
        self.fast_model=QLineEdit(settings.get('fast_model') or settings['model'])
        self.project_model=QLineEdit(settings.get('project_model') or settings['model'])
        self.vision_model=QLineEdit(settings.get('vision_model') or 'qwen3-vl:4b')
        self.vision_model.setToolTip('Internes Bildmodell, verwendet in jedem Chat bei ausdrücklicher Bildschirm-Anfrage.')
        self.url=QLineEdit(settings['ollama_url'])
        self.folder=QLineEdit(settings['workspace'])
        choose=QPushButton('…');choose.setMaximumWidth(38)
        choose.clicked.connect(self.browse_workspace)
        row=QHBoxLayout();row.addWidget(self.folder);row.addWidget(choose)
        self.vosk=QLineEdit(settings.get('vosk_model',''))
        self.piperexe=QLineEdit(settings.get('piper_exe',''))
        self.pipermodel=QLineEdit(settings.get('piper_model',''))
        self.gmail=QLineEdit(settings.get('gmail_client_secrets',''))
        self.voice=QCheckBox('Antworten automatisch vorlesen')
        self.voice.setChecked(settings.get('voice_enabled',False))
        self.speech_engine=QComboBox()
        self.speech_engine.addItem('Windows-Stimme (offline)', 'windows')
        self.speech_engine.addItem('Piper (natürlicher, offline)', 'piper')
        self.speech_engine.addItem('Edge Neural (natürlich, online)', 'edge')
        self.speech_engine.setCurrentIndex(max(0,self.speech_engine.findData(settings.get('speech_engine','windows'))))
        self.edge_voice=QComboBox()
        for label,code in [('Katja (Deutsch)','de-DE-KatjaNeural'),
                           ('Conrad (Deutsch)','de-DE-ConradNeural'),
                           ('Ingrid (Österreich)','de-AT-IngridNeural'),
                           ('Jonas (Österreich)','de-AT-JonasNeural')]:
            self.edge_voice.addItem(label,code)
        self.edge_voice.setCurrentIndex(max(0,self.edge_voice.findData(settings.get('edge_voice','de-DE-KatjaNeural'))))
        self.edge_consent=QCheckBox('Ich erlaube, dass gesprochene Antworten für die Online-Stimme an Microsoft übertragen werden.')
        self.edge_consent.setChecked(settings.get('edge_consent',False))
        self.auto_updates=QCheckBox('Automatisch nach neuen SYTOX-Versionen suchen (keine Installation ohne Zustimmung)')
        self.auto_updates.setChecked(settings.get('auto_check_updates', True))
        self.ram_saver=QCheckBox('RAM-Sparmodus: ungenutzte Ollama-Modelle entladen')
        self.ram_saver.setChecked(settings.get('ram_saver_enabled', True))
        self.ram_delay=QSpinBox()
        self.ram_delay.setRange(0, 3600)
        self.ram_delay.setSuffix(' Sekunden')
        self.ram_delay.setSpecialValueText('Sofort nach Antwort')
        self.ram_delay.setToolTip('Ab der fertigen Antwort. 300 Sekunden Standard vermeiden häufiges Neuladen bei Anschlussfragen; eigene Einstellungen bleiben erhalten.')
        self.ram_delay.setValue(normalized_keep_alive_seconds(
            settings.get('ram_keep_alive_seconds', 300)))
        self.ram_delay.setEnabled(self.ram_saver.isChecked())
        self.ram_saver.toggled.connect(self.ram_delay.setEnabled)
        self.auto_voice=QCheckBox('Beim App-Start automatisch auf „Hey Sytox“ hören (Mikrofon aktiv)')
        self.auto_voice.setChecked(settings.get('voice_auto_start', False))
        self.interruption=QCheckBox('Sprachausgabe durch „Hey Sytox“ oder „Stopp“ unterbrechen')
        self.interruption.setChecked(settings.get('voice_interruptible', True))
        self.no_wake=QCheckBox('Nach Start des Gesprächs ohne „Hey Sytox“ zuhören (Mikrofon bleibt aktiv)')
        self.no_wake.setChecked(settings.get('voice_no_wake',False))
        self.follow_up=QSpinBox()
        self.follow_up.setRange(5,90)
        self.follow_up.setSuffix(' Sekunden')
        self.follow_up.setValue(int(settings.get('voice_followup_seconds',25)))
        form.addRow('Ollama-Fallback-Modell',self.model)
        form.addRow('Schnellchat-Modell',self.fast_model)
        form.addRow('Projekt-/Coding-Modell',self.project_model)
        form.addRow('Bildmodell (in beiden Chats)',self.vision_model)
        form.addRow('Ollama-Adresse',self.url)
        form.addRow('',self.ram_saver)
        form.addRow('Modell nach Inaktivität entladen',self.ram_delay)
        form.addRow('Projektordner',row)
        form.addRow('Vosk-Modellordner (Deutsch)',self.vosk)
        form.addRow('Piper EXE (optional)',self.piperexe)
        form.addRow('Piper Stimmenmodell (.onnx)',self.pipermodel)
        form.addRow('Sprachausgabe',self.speech_engine)
        form.addRow('Neurale Stimme',self.edge_voice)
        form.addRow('',self.edge_consent)
        form.addRow('',self.voice)
        form.addRow('',self.auto_voice)
        form.addRow('',self.auto_updates)
        form.addRow('',self.interruption)
        form.addRow('',self.no_wake)
        form.addRow('Zeitfenster für Anschlussfrage',self.follow_up)
        form.addRow('Gmail OAuth-Desktop-Client JSON',self.gmail)
        check=QPushButton('Ollama-Verbindung testen')
        check.clicked.connect(self.check_ollama);form.addRow('',check)
        save=QPushButton('Speichern');save.setObjectName('primary')
        save.clicked.connect(self.validate_and_save);form.addRow('',save)

    def validate_and_save(self):
        if self.speech_engine.currentData()=='edge' and not self.edge_consent.isChecked():
            QMessageBox.warning(self,'Online-Stimme',
                                'Bitte der Datenübertragung ausdrücklich zustimmen oder eine Offline-Stimme auswählen.')
            return
        if self.speech_engine.currentData()=='piper' and not (
                Path(self.piperexe.text().strip()).is_file() and
                Path(self.pipermodel.text().strip()).is_file()):
            QMessageBox.warning(self,'Piper',
                                'Bitte eine existierende Piper-EXE und ein Stimmenmodell (.onnx) auswählen.')
            return
        self.accept()

    def browse_workspace(self):
        folder=QFileDialog.getExistingDirectory(self,'Projektordner wählen',self.folder.text())
        if folder:self.folder.setText(folder)

    def check_ollama(self):
        status = check_ollama_status(self.url.text(), self.model.text())
        message = status.details
        if status.available_models:
            message += '\nInstallierte Modelle: ' + ', '.join(status.available_models[:8])
        if status.ready:
            QMessageBox.information(self, status.title, message)
        else:
            QMessageBox.warning(self, status.title, message)

    def values(self):
        return {'model':self.model.text().strip(),'ollama_url':self.url.text().strip(),
                'fast_model':self.fast_model.text().strip(),
                'project_model':self.project_model.text().strip(),
                'vision_model':self.vision_model.text().strip(),
                'model_mode':self.original.get('model_mode', 'auto'),
                'workspace':self.folder.text().strip(), 'vosk_model':self.vosk.text().strip(),
                'piper_exe':self.piperexe.text().strip(),'piper_model':self.pipermodel.text().strip(),
                'voice_enabled':self.voice.isChecked(),
                'speech_engine':self.speech_engine.currentData(),
                'edge_voice':self.edge_voice.currentData(),
                'edge_consent':self.edge_consent.isChecked(),
                'edge_rate':'+8%',
                'voice_no_wake':self.no_wake.isChecked(),
                'voice_auto_start':self.auto_voice.isChecked(),
                'auto_check_updates':self.auto_updates.isChecked(),
                'ram_saver_enabled':self.ram_saver.isChecked(),
                'ram_keep_alive_seconds':self.ram_delay.value(),
                'voice_interruptible':self.interruption.isChecked(),
                'voice_followup_seconds':self.follow_up.value(),
                'gmail_client_secrets':self.gmail.text().strip()}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store=Store();self.store.interrupted_tasks()
        self.config_path=default_data_dir()/'settings.json'
        self.config=self.load_settings()
        self.chat_id=None;self.worker=None;self.recorder=None;self.listener=None;self.speakers=[]
        self._chat_drafts = {}  # Unsent text stays in this session, outside chat history.
        self.quick_worker = None
        self._quick_turn = None
        self._exit_after_quick = False
        self._quick_reply_timer = QTimer(self)
        self._quick_reply_timer.setSingleShot(True)
        self._quick_reply_timer.setInterval(40)
        self._quick_reply_timer.timeout.connect(self._flush_quick_tokens)
        self.voice_muted=threading.Event()
        self.voice_speaking=threading.Event()
        self.voice_jobs=[]
        self.voice_download=None
        self.voice_download_dialog=None
        self.voice_diagnostic_dialog=None
        self.desktop_tools_dialog=None
        self.parallel_chat=None
        self._update_check_worker=None
        self._update_download_worker=None
        self._resume_after_pause=False
        self._agent_last_status='Auftrag gestartet; noch kein konkreter Fortschritt gemeldet.'
        self.active_speaker=None
        self._voice_generation=0
        self._audio_path=None
        self._speaking=False
        self.player=QMediaPlayer(self)
        self.audio_output=QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(.85)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(self._media_error)
        self.tray=None
        self._is_exiting=False
        self.ollama_status=None
        self.ollama_probe=None
        self._probe_again=False
        self.setWindowTitle('SYTOX Assistant · Dein KI-Workspace')
        self.setWindowIcon(app_icon());self.resize(1390,860);self.setMinimumSize(960,630)
        self.setStyleSheet(QSS)
        self.build_ui()
        if self.config.get('focus_mode') is True:
            self.toggle_focus_mode(True)
        self.setup_tray();self.reload_chats()
        if not (self.chatlist.count() or self.projectlist.count()):
            self.create_chat()
        elif self.chatlist.count():
            self.select_chat(self.chatlist.item(0).data(Qt.UserRole))
        else:
            self.select_chat(self.projectlist.item(0).data(Qt.UserRole))
        self.log('System','Bereit. Lokale Daten: '+str(default_data_dir()))
        self._progress_refresh = QTimer(self)
        self._progress_refresh.setInterval(1400)
        self._progress_refresh.timeout.connect(self.refresh_live_progress)
        self._progress_refresh.start()
        # A failed swap reopens the previous EXE; show its rollback reason once.
        QTimer.singleShot(1500, self._show_pending_update_result)
        QTimer.singleShot(10000, self._show_pending_update_result)
        QTimer.singleShot(700, self.check_model_status)
        if self.config.get('auto_check_updates', True):
            QTimer.singleShot(2200, self.check_for_updates)
        if self.config.get('voice_auto_start', False):
            QTimer.singleShot(1600, self, lambda: self.toggle_listener(auto=True))

    def load_settings(self):
        base=default_data_dir();base.mkdir(parents=True,exist_ok=True)
        settings={'model':'qwen2.5-coder:7b','ollama_url':'http://localhost:11434',
                  'workspace':str(base/'projects'/'default'),'vosk_model':'',
                  'piper_exe':'','piper_model':'','voice_enabled':False,
                  'speech_engine':'windows','edge_voice':'de-DE-KatjaNeural','edge_rate':'+8%',
                  'edge_consent':False,'voice_no_wake':False,'voice_followup_seconds':25,
                  'voice_auto_start':False,'voice_interruptible':True,
                  'auto_check_updates':True,
                  'model_mode':'auto','fast_model':'qwen3:4b',
                  'project_model':'qwen3-coder:30b','vision_model':'qwen3-vl:4b',
                  'ram_saver_enabled':True,'ram_keep_alive_seconds':300,
                  'gmail_client_secrets':''}
        default_model=base/'models'/'vosk-model-small-de-0.15'
        if default_model.is_dir(): settings['vosk_model']=str(default_model)
        if self.config_path.exists():
            try:settings.update(json.loads(self.config_path.read_text(encoding='utf-8')))
            except Exception:pass
        return settings

    def build_ui(self):
        central = QWidget()
        central.setObjectName('appRoot')
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        self.splitter = splitter
        layout.addWidget(splitter)

        # Left: simple navigation, with a distinctive native vector brand.
        left = QFrame()
        left.setObjectName('sidebar')
        self.navigation_panel = left
        left.setMinimumWidth(218)
        l = QVBoxLayout(left)
        l.setContentsMargins(14, 23, 14, 17)
        l.setSpacing(9)
        identity = QHBoxLayout()
        identity.setSpacing(11)
        mark = BrandMark()
        subtle_glow(mark)
        identity.addWidget(mark)
        names = QVBoxLayout()
        names.setSpacing(1)
        title = QLabel('SYTOX')
        title.setObjectName('brandName')
        names.addWidget(title)
        subtitle = QLabel('LOCAL WORKSPACE')
        subtitle.setObjectName('brandSubtitle')
        names.addWidget(subtitle)
        identity.addLayout(names)
        identity.addStretch(1)
        l.addLayout(identity)
        l.addSpacing(21)
        btn_new = QPushButton('+  Neuer Chat')
        btn_new.setObjectName('primary')
        btn_new.clicked.connect(self.create_chat)
        btn_new.setMinimumHeight(44)
        l.addWidget(btn_new)
        btn_project = QPushButton('◆  Neues Qwen-Projekt')
        btn_project.setObjectName('subtle')
        btn_project.setMinimumHeight(42)
        btn_project.setToolTip('Dauerhaftes Coding-Projekt mit dem großen Qwen-Modell starten')
        btn_project.clicked.connect(self.create_project)
        self.new_project_btn = btn_project
        l.addWidget(btn_project)
        l.addSpacing(7)
        self.search = QLineEdit()
        self.search.setObjectName('chatSearch')
        self.search.setAccessibleName('Gespräche durchsuchen')
        self.search.setPlaceholderText('Titel und Nachrichten suchen')
        self.search.setToolTip('Durchsucht gespeicherte Titel und Nachrichten lokal auf diesem PC')
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload_chats)
        l.addWidget(self.search)
        l.addSpacing(3)
        projects_heading = QLabel('QWEN-PROJEKTE')
        projects_heading.setObjectName('sectionTitle')
        l.addWidget(projects_heading)
        self.projectlist = QListWidget()
        self.projectlist.setObjectName('projectList')
        self.projectlist.setAccessibleName('Gespeicherte Qwen-Projekte')
        self.projectlist.setSpacing(2)
        self.projectlist.itemClicked.connect(lambda it: self.select_chat(it.data(Qt.UserRole)))
        l.addWidget(self.projectlist, 1)
        recent = QLabel('DEINE GESPRÄCHE')
        recent.setObjectName('sectionTitle')
        l.addWidget(recent)
        self.chatlist = QListWidget()
        self.chatlist.setObjectName('chatList')
        self.chatlist.setAccessibleName('Schnelle Gespräche')
        self.chatlist.setSpacing(2)
        self.chatlist.itemClicked.connect(lambda it: self.select_chat(it.data(Qt.UserRole)))
        l.addWidget(self.chatlist, 2)
        rename = QPushButton('Chat umbenennen')
        rename.setObjectName('ghost')
        rename.clicked.connect(self.rename_chat)
        l.addWidget(rename)
        delete = QPushButton('Chat löschen')
        delete.setObjectName('ghost')
        delete.clicked.connect(self.delete_chat)
        l.addWidget(delete)
        cfg = QPushButton('Einstellungen')
        cfg.setObjectName('subtle')
        cfg.clicked.connect(self.edit_settings)
        l.addWidget(cfg)
        update_button = QPushButton('Nach Updates suchen')
        update_button.setObjectName('subtle')
        update_button.clicked.connect(lambda: self.check_for_updates(manual=True))
        l.addWidget(update_button)
        self.update_button = update_button
        version = QLabel('SYTOX  /  VERSION 0.3.9')
        version.setObjectName('version')
        version.setAlignment(Qt.AlignCenter)
        l.addSpacing(7)
        l.addWidget(version)
        splitter.addWidget(left)

        # Center: spacious conversation, quiet header, floating composer.
        center = QWidget()
        center.setObjectName('chatCenter')
        c = QVBoxLayout(center)
        c.setContentsMargins(0, 0, 0, 0)
        c.setSpacing(0)
        top = QFrame()
        top.setObjectName('topbar')
        th = QHBoxLayout(top)
        th.setContentsMargins(24, 14, 24, 14)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        breadcrumb = QLabel('WORKSPACE  /  KONVERSATION')
        breadcrumb.setObjectName('sectionTitle')
        self.chat_breadcrumb = breadcrumb
        titles.addWidget(breadcrumb)
        self.chat_heading = QLabel('Neuer Chat')
        self.chat_heading.setObjectName('chatTitle')
        titles.addWidget(self.chat_heading)
        th.addLayout(titles)
        th.addStretch(1)
        header_brand = brand_banner(168)
        if header_brand is not None:
            th.addWidget(header_brand, 0, Qt.AlignVCenter)
            th.addSpacing(12)
        self.focus_btn = QPushButton('Fokusmodus')
        self.focus_btn.setObjectName('panelToggle')
        self.focus_btn.setAccessibleName('Steuerzentrale ein- oder ausblenden')
        self.focus_btn.setCheckable(True)
        self.focus_btn.setToolTip('Steuerzentrale ausblenden (Strg+Umschalt+F)')
        self.focus_btn.clicked.connect(self.toggle_focus_mode)
        th.addWidget(self.focus_btn, 0, Qt.AlignVCenter)
        th.addSpacing(14)
        connection = QVBoxLayout()
        connection.setSpacing(4)
        self.model_name = QLabel('Automatische Auswahl' if self.config.get('model_mode','auto') == 'auto'
                                 else select_chat_model('', self.config)[0])
        self.model_name.setObjectName('muted')
        self.model_name.setAlignment(Qt.AlignRight)
        connection.addWidget(self.model_name)
        self.status_chip = QLabel('KI wird geprüft')
        self.status_chip.setObjectName('statusChip')
        self.status_chip.setAlignment(Qt.AlignCenter)
        connection.addWidget(self.status_chip, 0, Qt.AlignRight)
        th.addLayout(connection)
        c.addWidget(top)
        scroll = QScrollArea()
        scroll.setObjectName('messageScroll')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.msg_container = QWidget()
        self.msg_container.setObjectName('messageSurface')
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setAlignment(Qt.AlignTop)
        self.msg_layout.setSpacing(16)
        self.msg_layout.setContentsMargins(28, 30, 28, 30)
        scroll.setWidget(self.msg_container)
        c.addWidget(scroll, 1)
        self.scroll = scroll
        self.jump_to_latest = QPushButton('↓ Zur neuesten Nachricht')
        self.jump_to_latest.setObjectName('subtle')
        self.jump_to_latest.setAccessibleName('Zur neuesten Nachricht springen')
        self.jump_to_latest.clicked.connect(self.jump_to_latest_message)
        self.jump_to_latest.hide()
        c.addWidget(self.jump_to_latest, 0, Qt.AlignRight)
        self._follow_latest = True
        self._scroll_follow_timer = QTimer(self)
        self._scroll_follow_timer.setSingleShot(True)
        self._scroll_follow_timer.timeout.connect(self._scroll_to_latest_if_following)
        scroll.verticalScrollBar().valueChanged.connect(self._message_scroll_position_changed)
        scroll.verticalScrollBar().rangeChanged.connect(self._message_scroll_range_changed)
        self.empty_widget = None
        self._rendering_history = False

        compose = QFrame()
        compose.setObjectName('composePanel')
        cbox = QVBoxLayout(compose)
        cbox.setContentsMargins(25, 16, 25, 18)
        cbox.setSpacing(12)
        upper = QHBoxLayout()
        upper.setSpacing(12)
        self.model_mode = QComboBox()
        self.model_mode.setObjectName('modelMode')
        self.model_mode.addItem('Automatisch', 'auto')
        self.model_mode.addItem('⚡ Schnellchat', 'fast')
        self.model_mode.addItem('◆ Projekt', 'project')
        self.model_mode.setToolTip('Modell automatisch wählen oder manuell festlegen. Bildschirmsehen ist in jedem Modus möglich.')
        self.model_mode.setAccessibleName('Chat-Modell wählen')
        self.model_mode.setMaximumWidth(165)
        selected = self.model_mode.findData(self.config.get('model_mode', 'auto'))
        self.model_mode.setCurrentIndex(max(0, selected))
        self.model_mode.currentIndexChanged.connect(self._model_mode_changed)
        upper.addWidget(self.model_mode)
        self.mode = QComboBox()
        self.mode.addItems(['Einmal', '1 Stunde arbeiten', '3 Stunden arbeiten', 'Bis fertig'])
        self.mode.setMaximumWidth(192)
        self.mode.setToolTip('Wähle, wie lange SYTOX an deiner Aufgabe arbeiten soll.')
        upper.addWidget(self.mode)
        self.state = QLabel('●  Bereit für deine Aufgabe')
        self.state.setObjectName('muted')
        upper.addWidget(self.state)
        upper.addStretch(1)
        cbox.addLayout(upper)
        input_card = QFrame()
        input_card.setObjectName('inputCard')
        card_row = QHBoxLayout(input_card)
        card_row.setContentsMargins(9, 5, 9, 5)
        card_row.setSpacing(9)
        self.input = InputBox()
        self.input.setObjectName('chatInput')
        self.input.setPlaceholderText('Schreib SYTOX, was er für dich tun soll …')
        self.input.setFixedHeight(76)
        self.input.send.connect(self.send)
        card_row.addWidget(self.input, 1)
        # One horizontal composer toolbar: microphone directly beside Send.
        right_buttons = QHBoxLayout()
        right_buttons.setSpacing(8)
        self.mic_btn = QPushButton()
        self.mic_btn.setObjectName('micButton')
        self.mic_btn.setIcon(microphone_icon())
        self.mic_btn.setIconSize(QSize(26, 26))
        self.mic_btn.setFixedSize(46, 46)
        self.mic_btn.setCheckable(True)
        self.mic_btn.setAccessibleName('Sprachaufnahme starten oder stoppen')
        self.mic_btn.setToolTip('Sprachaufnahme starten')
        self.mic_btn.clicked.connect(self.toggle_memo)
        right_buttons.addWidget(self.mic_btn)
        self.send_btn = QPushButton('Senden')
        self.send_btn.setObjectName('primary')
        self.send_btn.clicked.connect(self.send)
        self.send_btn.setMinimumWidth(106)
        self.send_btn.setMinimumHeight(46)
        right_buttons.addWidget(self.send_btn)
        card_row.addLayout(right_buttons)
        cbox.addWidget(input_card)
        # Animate only the initial appearance, not the typing experience.
        QTimer.singleShot(70, self, lambda: self._animate_appearance(input_card, 220))
        hint = QLabel('ENTER SENDEN   ·   SHIFT + ENTER ZEILENUMBRUCH   ·   STRG + L EINGABE')
        hint.setObjectName('version')
        hint.setWordWrap(True)
        cbox.addWidget(hint)
        c.addWidget(compose)
        splitter.addWidget(center)

        # Right: purpose-built dark cards rather than an endless button list.
        right = QFrame()
        right.setObjectName('right')
        self.utility_panel = right
        right.setMinimumWidth(268)
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(12, 13, 12, 13)
        right_column.setSpacing(0)
        tools_heading = QLabel('STEUERZENTRALE')
        tools_heading.setObjectName('sectionTitle')
        right_column.addWidget(tools_heading)
        right_column.addSpacing(14)
        side_scroll = QScrollArea()
        side_scroll.setWidgetResizable(True)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side_container = QWidget()
        r = QVBoxLayout(side_container)
        r.setContentsMargins(0, 0, 4, 8)
        r.setSpacing(12)

        def new_card():
            card = QFrame()
            card.setObjectName('utilityCard')
            inner = QVBoxLayout(card)
            inner.setContentsMargins(14, 15, 14, 14)
            inner.setSpacing(9)
            return card, inner

        def collapsible_section(title, layout, setting):
            toggle = QPushButton('▸ ' + title)
            toggle.setObjectName('sectionToggle')
            toggle.setCheckable(True)
            toggle.setAccessibleName(title)
            toggle.setToolTip('Bereich ein- oder ausklappen')
            layout.addWidget(toggle)
            body = QWidget(layout.parentWidget())
            contents = QVBoxLayout(body)
            contents.setContentsMargins(0, 3, 0, 0)
            contents.setSpacing(9)
            body.hide()

            def expand(expanded):
                body.setVisible(expanded)
                toggle.setText(('▾ ' if expanded else '▸ ') + title)

            initially_expanded = self.config.get(setting, False) is True
            toggle.setChecked(initially_expanded)
            expand(initially_expanded)
            toggle.toggled.connect(expand)
            toggle.toggled.connect(lambda expanded: self._save_panel_state(setting, expanded))
            return toggle, body, contents

        ollama_card, ollama = new_card()
        ollama_title = QLabel('●  KI-VERBINDUNG')
        ollama_title.setObjectName('sectionTitle')
        ollama.addWidget(ollama_title)
        self.model_status_label = QLabel('Verbindung wird geprüft …')
        self.model_status_label.setObjectName('panelDescription')
        self.model_status_label.setWordWrap(True)
        ollama.addWidget(self.model_status_label)
        status_buttons = QHBoxLayout()
        check_model = QPushButton('Prüfen')
        check_model.clicked.connect(self.check_model_status)
        status_buttons.addWidget(check_model)
        setup_model = QPushButton('Einrichten')
        setup_model.setObjectName('subtle')
        setup_model.clicked.connect(self.show_model_help)
        status_buttons.addWidget(setup_model)
        ollama.addLayout(status_buttons)
        r.addWidget(ollama_card)

        task_card, task = new_card()
        lab = QLabel('AGENT CONTROL')
        lab.setObjectName('sectionTitle')
        task.addWidget(lab)
        self.task_state = QLabel('Keine aktive Aufgabe')
        self.task_state.setObjectName('panelDescription')
        self.task_state.setWordWrap(True)
        task.addWidget(self.task_state)
        self.task_meter = QProgressBar()
        self.task_meter.setObjectName('taskProgressMeter')
        self.task_meter.setRange(0, 100)
        self.task_meter.setValue(0)
        self.task_meter.setTextVisible(False)
        self.task_meter.setAccessibleName('Live-Arbeitsfortschritt')
        self.task_meter.hide()
        task.addWidget(self.task_meter)
        self.task_details = QLabel('Noch keine Arbeitsschritte protokolliert.')
        self.task_details.setObjectName('panelDescription')
        self.task_details.setWordWrap(True)
        self.task_details.hide()
        task.addWidget(self.task_details)
        self.task_next = QLabel('')
        self.task_next.setObjectName('panelDescription')
        self.task_next.setWordWrap(True)
        self.task_next.hide()
        task.addWidget(self.task_next)
        self.stopbtn = QPushButton('Aufgabe stoppen')
        self.stopbtn.setEnabled(False)
        self.stopbtn.clicked.connect(self.stop_work)
        task.addWidget(self.stopbtn)
        self.resume = QPushButton('Letzte Aufgabe fortsetzen')
        self.resume.clicked.connect(self.resume_task)
        task.addWidget(self.resume)
        self.parallel_btn = QPushButton('Während der Arbeit chatten')
        self.parallel_btn.setObjectName('subtle')
        self.parallel_btn.setToolTip('Nebenunterhaltung öffnen; laufende Agent-Aufgabe bleibt aktiv')
        self.parallel_btn.clicked.connect(self.show_parallel_chat)
        task.addWidget(self.parallel_btn)
        self.desktop_btn = QPushButton('Windows-Steuerung')
        self.desktop_btn.setObjectName('subtle')
        self.desktop_btn.setToolTip('Fenster anzeigen oder Programme suchen, mit Bestätigung vor jeder Änderung')
        self.desktop_btn.clicked.connect(lambda: self.show_desktop_tools())
        task.addWidget(self.desktop_btn)
        r.addWidget(task_card)

        voice_card, voice = new_card()
        self.voice_panel_toggle, self.voice_panel_body, voice_controls = collapsible_section(
            'SPRACHE & MIKROFON', voice, 'voice_panel_expanded')
        self.voice_state = QLabel('Mikrofon aus')
        self.voice_state.setObjectName('panelDescription')
        voice.addWidget(self.voice_state)
        self.wakebtn = QPushButton('Gesprächsmodus starten')
        self.wakebtn.setObjectName('subtle')
        self.wakebtn.clicked.connect(self.toggle_listener)
        voice_controls.addWidget(self.wakebtn)
        model_button = QPushButton('Sprachmodell laden')
        model_button.clicked.connect(self.install_voice_model)
        voice_controls.addWidget(model_button)
        self.stopvoicebtn = QPushButton('Sprache stoppen')
        self.stopvoicebtn.clicked.connect(self.stop_speech)
        self.stopvoicebtn.setEnabled(False)
        voice_controls.addWidget(self.stopvoicebtn)
        diagnostics_button = QPushButton('Mikrofon / Unterbrechung')
        diagnostics_button.setToolTip('Mikrofon und Unterbrechung testen')
        diagnostics_button.clicked.connect(self.open_voice_diagnostics)
        voice_controls.addWidget(diagnostics_button)
        voice.addWidget(self.voice_panel_body)
        r.addWidget(voice_card)

        activity_card, activity = new_card()
        self.activity_panel_toggle, self.activity_panel_body, activity_controls = collapsible_section(
            'AKTIVITÄTEN', activity, 'activity_panel_expanded')
        self.logs = QPlainTextEdit()
        self.logs.setObjectName('activityLog')
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(250)
        self.logs.setMinimumHeight(125)
        activity_controls.addWidget(self.logs)
        activity.addWidget(self.activity_panel_body)
        memory = QPushButton('Gespeicherte Erinnerungen')
        memory.setObjectName('ghost')
        memory.clicked.connect(self.show_memories)
        activity.addWidget(memory)
        r.addWidget(activity_card)
        r.addStretch(1)
        side_scroll.setWidget(side_container)
        right_column.addWidget(side_scroll, 1)
        splitter.addWidget(right)
        splitter.setSizes([255, 830, 296])
        splitter.setStretchFactor(1, 1)
        self._focus_shortcut = QShortcut(QKeySequence('Ctrl+Shift+F'), self)
        self._focus_shortcut.activated.connect(self.toggle_focus_mode)
        self._search_shortcut = QShortcut(QKeySequence('Ctrl+K'), self)
        self._search_shortcut.activated.connect(self.search.setFocus)
        self._new_chat_shortcut = QShortcut(QKeySequence('Ctrl+N'), self)
        self._new_chat_shortcut.activated.connect(self.create_chat)
        self._input_shortcut = QShortcut(QKeySequence('Ctrl+L'), self)
        self._input_shortcut.activated.connect(self.input.setFocus)
        self.input.setFocus()

    def _save_panel_state(self, setting, expanded):
        self.config[setting] = bool(expanded)
        temporary = self.config_path.with_suffix('.json.tmp')
        try:
            temporary.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(self.config_path)
        except OSError as exc:
            self.log('System', 'Ansicht konnte nicht gespeichert werden: ' + str(exc))

    def _chat_runtime_config(self):
        """Apply the saved model choice of this chat, never the last-used other chat."""
        settings = self.config.copy()
        if self.chat_id:
            settings['model_mode'] = self.store.chat_model_mode(self.chat_id) or 'fast'
        return settings

    def _model_mode_changed(self, _index=None):
        """Persist manual selection for normal chats; Qwen projects stay Qwen."""
        if self.chat_id and self.store.chat_kind(self.chat_id) == 'project':
            return
        route = self.model_mode.currentData()
        if self.chat_id:
            self.store.set_chat_model_mode(self.chat_id, route)
        self.config['model_mode'] = route
        self.config_path.write_text(
            json.dumps(self.config, ensure_ascii=False, indent=2), encoding='utf-8')
        if self.parallel_chat is not None:
            self.parallel_chat.config = dict(self.config, model_mode='fast')
        label = (self.config.get('project_model') if route == 'project'
                 else self.config.get('fast_model') if route == 'fast'
                 else 'Automatische Modellauswahl')
        self.model_name.setText(label or self.config['model'])
        self.check_model_status()

    def toggle_focus_mode(self, checked=None):
        """Give the conversation more room without stopping AI, voice or agent tasks."""
        if checked is None:
            checked = not self.focus_btn.isChecked()
        checked = bool(checked)
        if checked:
            self._utility_last_width = max(268, self.utility_panel.width())
        self.focus_btn.setChecked(checked)
        self.utility_panel.setVisible(not checked)
        self.focus_btn.setText('Steuerzentrale' if checked else 'Fokusmodus')
        self.focus_btn.setToolTip(
            'Steuerzentrale einblenden (Strg+Umschalt+F)' if checked
            else 'Steuerzentrale ausblenden (Strg+Umschalt+F)'
        )
        if not checked:
            sidebar_width = max(218, self.navigation_panel.width())
            panel_width = getattr(self, '_utility_last_width', 296)
            center_width = max(450, self.splitter.width() - sidebar_width - panel_width - 2)
            self.splitter.setSizes([sidebar_width, center_width, panel_width])
        if self.config.get('focus_mode', False) != checked:
            self._save_panel_state('focus_mode', checked)
        self.input.setFocus()

    def _animate_appearance(self, widget, duration=260):
        """A short non-blocking fade; never animate ongoing voice/agent tasks."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b'opacity', widget)
        animation.setDuration(duration)
        animation.setStartValue(0.10)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.start()
        # Animation is owned by its widget; no detached Qt objects or timers.
        widget._intro_animation = animation

    def _use_suggestion(self, prompt):
        self.input.setPlainText(prompt)
        self.input.setFocus()

    def _show_empty_state(self):
        hero = QFrame()
        hero.setObjectName('hero')
        hero.setMaximumWidth(670)
        box = QVBoxLayout(hero)
        box.setContentsMargins(32, 30, 32, 30)
        box.setSpacing(13)
        hero_logo = brand_banner(560)
        if hero_logo is not None:
            box.addWidget(hero_logo)
            box.addSpacing(7)
        eyebrow = QLabel('DEIN PERSÖNLICHER KI-WORKSPACE')
        eyebrow.setObjectName('heroEyebrow')
        box.addWidget(eyebrow)
        title = QLabel('Was bauen wir heute?')
        title.setObjectName('heroTitle')
        title.setWordWrap(True)
        box.addWidget(title)
        subtitle = QLabel('Frag, plane, programmiere oder steuere deinen PC.\nSYTOX unterstützt dich – lokal und mit deiner Freigabe.')
        subtitle.setObjectName('heroCopy')
        subtitle.setWordWrap(True)
        box.addWidget(subtitle)
        box.addSpacing(9)
        suggestions = (
            ('Eine Idee ausarbeiten', 'Hilf mir, eine neue Projektidee Schritt für Schritt auszuarbeiten.'),
            ('Code schreiben', 'Erstelle mit mir eine neue Funktion für mein Projekt.'),
            ('Windows-Aufgabe erledigen', 'Hilf mir, eine Aufgabe auf meinem Windows-PC auszuführen.'),
        )
        for caption, prompt in suggestions:
            button = QPushButton(caption)
            button.setObjectName('suggestion')
            button.clicked.connect(lambda checked=False, p=prompt: self._use_suggestion(p))
            box.addWidget(button)
        self.empty_widget = hero
        outer = QWidget()
        outer_lay = QHBoxLayout(outer)
        outer_lay.setContentsMargins(0, 34, 0, 0)
        outer_lay.addStretch(1)
        outer_lay.addWidget(hero, 10)
        outer_lay.addStretch(1)
        self.msg_layout.addWidget(outer)
        QTimer.singleShot(0, self, lambda: self._animate_appearance(outer) if not self._is_exiting else None)

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():return
        self.tray=QSystemTrayIcon(app_icon(),self)
        menu=QMenu();menu.addAction('SYTOX öffnen',self.show_window)
        menu.addSeparator()
        menu.addAction('SYTOX vollständig beenden',self.exit_app)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip('SYTOX Assistant · Läuft im Hintergrund')
        self.tray.activated.connect(lambda reason:self.show_window() if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def show_window(self):
        self.show();self.showNormal();self.raise_();self.activateWindow()

    def closeEvent(self,event):
        if self.voice_download and self.voice_download.isRunning() and self._is_exiting:
            self.voice_download.cancel_event.set()
            event.ignore()
            return
        # Closing the window should NOT shut down the assistant. Exit through
        # the tray menu (or Windows session shutdown) to quit the background app.
        if self.tray and not self._is_exiting:
            self.hide()
            event.ignore()
            return
        if self.quick_worker is not None:
            self.quick_worker.stop_event.set()
            self._exit_after_quick = True
            event.ignore()
            return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'Auftrag läuft','Bitte den Auftrag zuerst stoppen.')
            event.ignore()
            return
        if self.listener and self.listener.isRunning():
            self.listener.stop_event.set()
            self.listener.wait(3000)
        if self.ollama_probe and self.ollama_probe.isRunning():
            self.ollama_probe.wait(6000)  # bounded 5s HTTP probe must not outlive Qt
        event.accept()

    def exit_app(self):
        if self.quick_worker is not None:
            self.quick_worker.stop_event.set()
            self._exit_after_quick = True
            self.state.setText('Antwort wird beendet …')
            return
        if self._update_download_worker and self._update_download_worker.isRunning():
            QMessageBox.information(self, 'Update läuft',
                                    'Bitte den laufenden Update-Download erst abschließen.')
            return
        if self._update_check_worker and self._update_check_worker.isRunning():
            self._update_check_worker.wait(18000)
        if self.voice_download and self.voice_download.isRunning():
            self.voice_download.cancel_event.set()
            if not self.voice_download.wait(6000):
                QMessageBox.information(self,'Sprachmodell',
                    'Der Download wird noch beendet. Bitte gleich erneut versuchen.')
                return
        self.stop_speech()
        if self.parallel_chat and not self.parallel_chat.stop_reply():
            QMessageBox.information(self, 'Nebenunterhaltung',
                'Die kurze KI-Antwort wird noch beendet. Bitte danach erneut schließen.')
            return
        if self.listener and self.listener.isRunning():
            self.listener.stop_event.set();self.listener.wait(3000)
        if self.recorder and self.recorder.isRunning():
            self.recorder.stop_event.set();self.recorder.wait(3000)
        if self.worker and self.worker.isRunning():
            reply=QMessageBox.question(self,'Auftrag läuft','Auftrag stoppen und beenden?')
            if reply!=QMessageBox.Yes:return
            self.worker.stop_event.set()
            self.worker.wait(5000)
            if self.worker.isRunning():
                QMessageBox.warning(self,'Bitte warten','Der Vorgang beendet noch einen laufenden Aufruf.')
                return
        self._is_exiting=True
        if self.ollama_probe and self.ollama_probe.isRunning():
            self.ollama_probe.wait(6000)
        self.tray.hide() if self.tray else None
        QApplication.quit()

    def reload_chats(self,*args):
        if not hasattr(self, 'chatlist') or not hasattr(self, 'projectlist'):
            return
        search = (self.search.text() if hasattr(self, 'search') else '').strip().casefold()
        content_matches = self.store.matching_chat_ids(search) if search else set()
        self.chatlist.clear()
        self.projectlist.clear()
        for chat in self.store.chats():
            if search not in chat['title'].casefold() and chat['id'] not in content_matches:
                continue
            project = chat['kind'] == 'project'
            widget = self.projectlist if project else self.chatlist
            item = QListWidgetItem(('◆  ' if project else '') + chat['title'])
            item.setData(Qt.UserRole, chat['id'])
            widget.addItem(item)
            if chat['id'] == self.chat_id:
                widget.setCurrentItem(item)

    def create_chat(self):
        if self.quick_worker is not None or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self, 'Auftrag läuft', 'Bitte erst den laufenden Auftrag stoppen.')
            return
        cid = self.store.create_chat(kind='chat')
        self.search.clear()
        self.reload_chats()
        self.select_chat(cid)

    def create_project(self):
        """Create a named, permanent large-model conversation in the sidebar."""
        if self.quick_worker is not None or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self, 'Auftrag läuft', 'Bitte erst den laufenden Auftrag stoppen.')
            return
        title, accepted = QInputDialog.getText(self, 'Neues Qwen-Projekt', 'Projektname:')
        if not accepted or not title.strip():
            return
        cid = self.store.create_chat(title=title.strip(), kind='project')
        self.search.clear()  # Ensure the new project is visible even after a search.
        self.reload_chats()
        self.select_chat(cid)

    def select_chat(self,cid):
        if self.quick_worker is not None and cid == self.chat_id:
            return  # Keep the streaming bubble alive when its list item is clicked.
        if (self.quick_worker is not None or (self.worker and self.worker.isRunning())) and cid!=self.chat_id:
            QMessageBox.information(self,'Auftrag läuft','Während der Ausführung kann der Chat nicht gewechselt werden.')
            return
        current=next((c for c in self.store.chats() if c['id']==cid),None)
        if current is None:
            return
        if cid != self.chat_id:
            if self.chat_id:
                self._chat_drafts[self.chat_id] = self.input.toPlainText()
            self.input.setPlainText(self._chat_drafts.get(cid, ''))
        self.chat_id=cid
        self._follow_latest = True
        project = current['kind'] == 'project'
        selected_mode = self.store.chat_model_mode(cid)
        self.model_mode.blockSignals(True)
        self.model_mode.setCurrentIndex(max(0, self.model_mode.findData(selected_mode)))
        self.model_mode.setEnabled(not project)
        self.model_mode.blockSignals(False)
        self.config['model_mode'] = selected_mode
        self.model_name.setText(select_chat_model('', self._chat_runtime_config())[0])
        self.chat_breadcrumb.setText('WORKSPACE  /  QWEN-PROJEKT' if project
                                     else 'WORKSPACE  /  SCHNELLCHAT')
        self.chat_heading.setText(current['title'])
        self.reload_chats();self.clear_bubbles()
        messages = self.store.messages(cid)
        if not messages:
            self._show_empty_state()
        else:
            self._rendering_history = True
            try:
                for m in messages:
                    self.add_bubble(m['role'],m['content'])
            finally:
                self._rendering_history = False
        tasks=self.store.tasks(cid)
        self.task_state.setText((task_status_text(tasks[0]['status'])+': '+tasks[0]['goal'][:85]) if tasks else 'Keine aktive Aufgabe')

    def rename_chat(self):
        if not self.chat_id:return
        text,ok=QInputDialog.getText(self,'Chat umbenennen','Neuer Titel:')
        if ok and text.strip():
            self.store.rename_chat(self.chat_id,text.strip());self.reload_chats()
            self.chat_heading.setText(text.strip())

    def delete_chat(self):
        if not self.chat_id:return
        if self.quick_worker is not None:return
        if self.worker and self.worker.isRunning():return
        if QMessageBox.question(self,'Chat löschen','Diesen Chat mit allen Nachrichten wirklich löschen?')!=QMessageBox.Yes:return
        self.store.delete_chat(self.chat_id)
        self._chat_drafts.pop(self.chat_id, None)
        self.input.clear()
        self.chat_id=None;self.reload_chats()
        if self.chatlist.count():
            self.select_chat(self.chatlist.item(0).data(Qt.UserRole))
        elif self.projectlist.count():
            self.select_chat(self.projectlist.item(0).data(Qt.UserRole))
        else:
            self.create_chat()

    def clear_bubbles(self):
        self.empty_widget = None
        while self.msg_layout.count():
            item = self.msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _message_scroll_position_changed(self, *_args):
        bar = self.scroll.verticalScrollBar()
        self._follow_latest = bar.maximum() - bar.value() <= 80
        self.jump_to_latest.setVisible(not self._follow_latest)

    def _message_scroll_range_changed(self, *_args):
        if self._follow_latest:
            self._scroll_follow_timer.start(0)
        else:
            self._message_scroll_position_changed()

    def _scroll_to_latest_if_following(self):
        if self._follow_latest:
            self.jump_to_latest_message()

    def jump_to_latest_message(self):
        self._follow_latest = True
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.jump_to_latest.hide()

    def add_bubble(self, role, message):
        if self.empty_widget is not None:
            self.clear_bubbles()
        mine = role == 'user'
        body = QFrame()
        body.setObjectName('bubbleUser' if mine else 'bubbleAssistant')
        b = QVBoxLayout(body)
        b.setContentsMargins(17, 14, 17, 16)
        b.setSpacing(10)
        header = QLabel('DU' if mine else 'SYTOX AI')
        header.setObjectName('bubbleHeadingUser' if mine else 'bubbleHeadingAssistant')
        heading = QHBoxLayout()
        heading.addWidget(header)
        heading.addStretch(1)
        if not mine:
            copy_button = QPushButton('Kopieren')
            copy_button.setObjectName('copyReplyButton')
            copy_button.setAccessibleName('Antwort kopieren')
            copy_button.setToolTip('Sichtbaren Antworttext unverändert kopieren')
            copy_button.clicked.connect(lambda _checked=False: QApplication.clipboard().setText(label.text()))
            heading.addWidget(copy_button)
        b.addLayout(heading)
        label = QLabel(message) if mine else MessageLabel(message)
        label.setObjectName('bubbleContent')
        label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b.addWidget(label)
        if not mine:
            code_actions = QWidget(body)
            code_layout = QVBoxLayout(code_actions)
            code_layout.setContentsMargins(0, 0, 0, 0)
            code_layout.setSpacing(3)
            code_actions.hide()
            code_actions._blocks = []

            def update_code_actions(text):
                blocks = fenced_code_blocks(text)
                if blocks == code_actions._blocks:
                    return
                code_actions._blocks = blocks
                while code_layout.count():
                    old = code_layout.takeAt(0).widget()
                    old.hide()
                    old.setParent(None)
                    old.deleteLater()
                for number, block in enumerate(blocks, 1):
                    language = block['language'][:30]
                    caption = f'Codeblock {number} kopieren' + (f' ({language})' if language else '')
                    button = QPushButton(caption)
                    button.setObjectName('copyCodeButton')
                    button.setAccessibleName(f'Codeblock {number} kopieren')
                    button.clicked.connect(lambda _checked=False, code=block['code']:
                                           QApplication.clipboard().setText(code))
                    code_layout.addWidget(button)
                code_actions.setVisible(bool(blocks))

            label.text_changed.connect(update_code_actions)
            update_code_actions(message)
            b.addWidget(code_actions)
        body.setMaximumWidth(790)
        row = QWidget()
        row.setObjectName('messageRow')
        r = QHBoxLayout(row)
        r.setContentsMargins(0, 0, 0, 0)
        if mine:
            r.addStretch(1)
        r.addWidget(body, 5)
        if not mine:
            r.addStretch(1)
        self.msg_layout.addWidget(row)
        if not self._rendering_history and self.isVisible():
            self._animate_appearance(row, 200)
        if mine or self._rendering_history:
            self._follow_latest = True
        if self._follow_latest:
            self._scroll_follow_timer.start(0)
        return label

    def log(self,kind,text):
        self.logs.appendPlainText(f'{kind}: {text}')
        if kind in ('Status','Aktion'):
            self._agent_last_status = str(text)[:130]
            self.state.setText(('● ' if kind=='Status' else '◆ ')+str(text)[:80])

    def send(self):
        txt=self.input.toPlainText().strip()
        if not txt:return
        intent = work_intent(txt)
        if intent:
            self.input.clear()
            self.handle_work_control(intent, txt, spoken=False)
            return
        if self.quick_worker is not None:
            self.state.setText('Die aktuelle Antwort läuft noch. Mit Stopp abbrechen.')
            return
        if self.worker and self.worker.isRunning():
            self.input.clear()
            if agent_status_intent(txt):
                self.report_agent_status(txt, spoken=False)
            elif is_change_request(txt):
                self.queue_project_change(txt, spoken=False)
            else:
                self.ask_parallel(txt, spoken=False)
            return
        self.stop_speech()
        self.voice_muted.set()
        self.store.add_message(self.chat_id,'user',txt)
        self.add_bubble('user',txt)
        self.input.clear()
        messages=self.store.messages(self.chat_id)
        if (self.store.chat_kind(self.chat_id) != 'project' and
                len([m for m in messages if m['role']=='user']) == 1):
            self.store.rename_chat(self.chat_id,txt[:46]+'…' if len(txt)>46 else txt[:46]);self.reload_chats()
            self.chat_heading.setText(txt[:46])
        mode={'Einmal':'once','1 Stunde arbeiten':'timed','3 Stunden arbeiten':'timed','Bis fertig':'until_done'}[self.mode.currentText()]
        hours=3.0 if self.mode.currentText().startswith('3') else 1.0
        duration=re.search(r'\b(\d+(?:[,.]\d+)?)\s*(?:stunden?|h)\b',txt.lower())
        task_requested = (self.store.chat_kind(self.chat_id) == 'project' or
                          requires_agent(txt) or
                          re.search(r'\b(?:arbeite|arbeiten)\b', txt, re.IGNORECASE))
        if duration and task_requested:
            hours=max(.02,min(float(duration.group(1).replace(',','.')),24.0))
            mode='timed'
        if re.search(r'\bbis (?:es |alles )?fertig\b',txt.lower()):mode='until_done'
        selected, _route = select_chat_model(txt, self._chat_runtime_config(), mode)
        self.model_name.setText(selected)
        if self.store.chat_kind(self.chat_id) == 'project' or requires_agent(txt, mode):
            self.start_worker(mode,hours)
        else:
            self.start_quick_reply(txt)

    def start_quick_reply(self, question):
        """Normal conversation never creates an Agent, Toolkit or task row."""
        memory = ''
        if len(question.strip()) > 8:
            context = self.store.related_context(question, exclude_chat=self.chat_id, limit=3)
            memory = '\n'.join(item['source'] + ': ' + item['content'] for item in context)[:2000]
        worker = ParallelReplyWorker(
            self._chat_runtime_config(), self.store.messages(self.chat_id, limit=12), self,
            standalone=True, memory_context=memory)
        self.quick_worker = worker
        self._quick_turn = {'chat_id': self.chat_id, 'text': '',
                            'label': self.add_bubble('assistant', 'SYTOX antwortet …'),
                            'outcome': 'running', 'answer': ''}
        worker.token.connect(self._quick_token)
        worker.metrics.connect(self._quick_metrics)
        worker.model_selected.connect(self.model_name.setText)
        worker.approval_request.connect(self.handle_approval)
        worker.completed.connect(self._quick_done)
        worker.finished.connect(self._quick_finished)
        self.send_btn.setEnabled(False)
        self.stopbtn.setEnabled(True)
        self.stopbtn.setText('Antwort abbrechen')
        self.model_mode.setEnabled(False)
        self.state.setText('SYTOX antwortet …')
        self.task_state.setText('Gespräch · kein Programmierauftrag')
        worker.start()

    def _quick_token(self, text):
        if self._quick_turn is None:
            return
        self._quick_turn['text'] += text
        if not self._quick_reply_timer.isActive():
            self._quick_reply_timer.start()

    def _flush_quick_tokens(self):
        if self._quick_turn is None or not self._quick_turn['text']:
            return
        self._quick_turn['label'].setText(self._quick_turn['text'])
        if self._follow_latest:
            self._scroll_follow_timer.start(0)

    def _quick_metrics(self, metrics):
        self._last_chat_metrics = dict(metrics)
        parts = []
        for key, title in (('queue_wait_s', 'Wartezeit'), ('load_s', 'Modell laden'),
                           ('time_to_first_token_s', 'Erstes Token'),
                           ('request_s', 'Modellanfrage')):
            value = metrics.get(key)
            if value is not None:
                parts.append(f'{title}: {value:.2f} s')
        speed = metrics.get('tokens_per_second')
        if speed is not None:
            parts.append(f'{speed:.1f} Token/s')
        details = ' · '.join(parts)
        self.model_name.setToolTip(details)
        self.log('Leistung', details)

    def _quick_done(self, answer):
        if self._quick_turn is None:
            return
        self._quick_reply_timer.stop()
        turn = self._quick_turn
        outcome = self.quick_worker.outcome
        # The reply worker marks partial/error output explicitly incomplete.
        turn.update(answer=answer, outcome=outcome)
        turn['label'].setText(answer)
        self.store.add_message(turn['chat_id'], 'assistant', answer)
        self.state.setText({'done': 'Antwort fertig', 'cancelled': 'Antwort abgebrochen',
                            'failed': 'Antwort fehlgeschlagen'}.get(outcome, 'Antwort beendet'))

    def _quick_finished(self):
        worker, turn = self.quick_worker, self._quick_turn
        self.quick_worker = None
        self._quick_turn = None
        self._quick_reply_timer.stop()
        if worker is not None:
            worker.deleteLater()
        self.stopbtn.setEnabled(False)
        self.stopbtn.setText('Aufgabe stoppen')
        self.send_btn.setEnabled(True)
        self.model_mode.setEnabled(self.store.chat_kind(self.chat_id) != 'project')
        if self._exit_after_quick:
            self._exit_after_quick = False
            self.exit_app()
            return
        if (turn and turn['outcome'] == 'done' and turn['answer'] and
                (self.config.get('voice_enabled') or
                 (self.listener and self.listener.isRunning()))):
            self.start_speech(turn['answer'])
        else:
            self._conversation_ready()
        self.input.setFocus()

    def queue_project_change(self, instruction, spoken=False):
        """Accept a new project instruction without stopping or sending a build."""
        if not (self.worker and self.worker.isRunning()):
            return False
        try:
            change_id = self.store.add_task_change(self.chat_id, instruction)
        except (ValueError, RuntimeError) as exc:
            message = 'Änderung konnte nicht vorgemerkt werden: ' + str(exc)
            self.log('Status', message)
            if spoken:
                self.start_speech(message)
            else:
                self.add_bubble('assistant', message)
            return False
        # Only the queue table is written. Never change the original task goal.
        self.add_bubble('user', instruction)
        message = ('Zusatzwunsch ' + str(change_id) +
                   ' vorgemerkt. Ich schließe zuerst die laufende Arbeit ab, '
                   'ergänze danach dein Projekt und melde erst dann fertig.')
        self.log('Status', message)
        if self.parallel_chat is not None and self.parallel_chat.isVisible():
            self.parallel_chat.transcript.appendPlainText(
                'DU: ' + instruction + '\\nSYTOX: ' + message + '\\n')
        else:
            self.add_bubble('assistant', message)
        self.refresh_live_progress()
        if spoken:
            self.start_speech(message)
        return True

    def refresh_live_progress(self):
        """Read live task checkpoints; never ask the busy coding model."""
        if not hasattr(self, 'task_meter') or not self.chat_id:
            return
        active = bool(self.worker and self.worker.isRunning())
        for widget in (self.task_meter, self.task_details, self.task_next):
            widget.setVisible(active)
        entries = self.store.tasks(self.chat_id)
        task = next((item for item in entries if item['status'] == 'running'), None)
        if active and task is None:
            self.task_meter.setRange(0, 0)
            self.task_details.setText('Auftrag wird vorbereitet …')
            self.task_next.setText('')
            return
        if active and task:
            try:
                cp = json.loads(task.get('checkpoint') or '{}')
            except (ValueError, TypeError):
                cp = {}
            steps = max(0, int(cp.get('steps', 0)))
            writes = max(0, int(cp.get('writes', 0)))
            checks = max(0, int(cp.get('passed_checks', 0)))
            changes = self.store.task_changes(task['id'])
            self.task_meter.setRange(0, 0)  # Activity, not a fictitious percent.
            self.task_details.setText(
                f'{steps} Schritte · {writes} Dateiänderungen · '
                f'{checks} Prüfungen · {len(changes)} vorgemerkte Änderungen')
            recent = str(cp.get('last_result') or '')[:135]
            if not recent:
                notes = cp.get('progress_notes', [])
                if isinstance(notes, list):
                    recent = str((notes[-1] if notes and isinstance(notes[-1], dict)
                                  else {}).get('next_step') or '')[:135]
            eta = task_eta(task)
            if eta['state'] == 'estimated':
                label = ('Restzeit: ca. ' + str(eta['low_minutes']) + '–'
                         + str(eta['high_minutes']) + ' Minuten. ')
            else:
                label = 'Restzeit noch nicht zuverlässig abschätzbar. '
            self.task_next.setText(label + ('Zuletzt: ' + recent if recent else ''))
        else:
            self.task_meter.setRange(0, 100)
            self.task_meter.setValue(0)
            if entries and entries[0]['status'] == 'done':
                self.task_details.setText('Aufgabe abgeschlossen.')
            elif entries and entries[0]['status'] == 'paused':
                self.task_details.setText('Aufgabe pausiert; gespeicherter Stand verfügbar.')
            else:
                self.task_details.setText('Kein laufender Programmierauftrag.')
            self.task_next.setText('')

    def start_worker(self,mode='once',hours=1.0,task_id=None):
        # The Agent runs in its own thread. Listening for follow-up questions
        # must remain available while it writes code in that thread.
        if self.listener and self.listener.isRunning() and not self._speaking:
            self.voice_muted.clear()
        else:
            self.voice_muted.set()
        self._agent_last_status='Auftrag gestartet; noch kein konkreter Fortschritt gemeldet.'
        self.worker=Worker(self.store,self.chat_id,self._chat_runtime_config(),mode,hours,task_id)
        self.worker.log_line.connect(self.log)
        self.worker.approval_request.connect(self.handle_approval)
        self.worker.completed.connect(self.worker_done)
        self.worker.finished.connect(self._agent_thread_finished)
        self.stopbtn.setEnabled(True)
        # Sending during work routes to the separate, tool-free conversation.
        self.send_btn.setEnabled(True)
        self.task_state.setText('Aufgabe läuft' if mode == 'once' else
                               'Arbeitet bis zum Abschluss' if mode == 'until_done' else
                               f'Arbeitet bis zu {hours:g} Stunden')
        self.task_meter.setRange(0, 0)
        self.task_details.setText('Auftrag wird vorbereitet …')
        self.task_next.setText('')
        for widget in (self.task_meter, self.task_details, self.task_next):
            widget.show()
        self.worker.start()

    def stop_work(self):
        if self.quick_worker is not None:
            self.quick_worker.stop_event.set()
            self.state.setText('Antwort wird abgebrochen …')
            return
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set();self.log('Status','Stopp angefordert …')


    def _agent_thread_finished(self):
        """A resume requested during shutdown waits for the old QThread to exit."""
        if not self._resume_after_pause:
            return
        self._resume_after_pause = False
        candidates = [task for task in self.store.tasks(self.chat_id)
                      if task['status'] == 'paused']
        if candidates:
            self.resume_task()

    def handle_work_control(self, intent, original='', spoken=False):
        """Interpret conversational task controls without altering side questions."""
        if self.quick_worker is not None and intent == 'pause':
            self.stop_work()
            return 'Ich breche die aktuelle Antwort ab.'
        active = bool(self.worker and self.worker.isRunning())
        stopping = bool(active and self.worker.stop_event.is_set())
        if intent == 'silence':
            self.stop_speech()
            message = 'Okay, ich bin still. Der Programmierauftrag bleibt unverändert.'
        elif intent == 'pause':
            self._resume_after_pause = False
            if active and not stopping:
                self.stop_work()
                message = ('Okay, ich pausiere die Arbeit nach dem aktuellen Schritt. '
                           'Der gespeicherte Zwischenstand bleibt erhalten.')
            elif stopping:
                message = 'Die Pause wurde bereits angefordert.'
            else:
                message = 'Gerade läuft kein Auftrag, den ich pausieren könnte.'
        elif intent == 'resume':
            if active and stopping:
                self._resume_after_pause = True
                message = ('Ich mache weiter, sobald der laufende Schritt '
                           'beendet und die Pause gespeichert ist.')
            elif active:
                message = 'Ich arbeite bereits weiter an deinem Auftrag.'
            else:
                candidates = [task for task in self.store.tasks(self.chat_id)
                              if task['status'] in ('paused', 'failed', 'time_elapsed')]
                if candidates:
                    self.resume_task()
                    message = 'Ich setze den letzten unterbrochenen Auftrag fort.'
                else:
                    message = 'Ich habe gerade keinen pausierten Auftrag zum Fortsetzen.'
        else:
            return
        self.log('Stimme' if spoken else 'System', 'Auftragssteuerung: ' + message)
        if self.parallel_chat is not None:
            self.parallel_chat.transcript.appendPlainText(
                'DU: ' + str(original or '') + '\nSYTOX: ' + message + '\n'
            )
        if spoken and self.listener and self.listener.isRunning():
            self.start_speech(message)
        else:
            self._conversation_ready()
        return message

    def handle_approval(self,label,desc,payload):
        if not self.isVisible():
            self.show_window()  # Do not hide sensitive action approvals in the tray.
        dialog=QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle('Freigabe erforderlich')
        dialog.setText(label)
        dialog.setInformativeText(desc[:600]+'\n\nNur erlauben, wenn du der Aktion vertraust.')
        dialog.setStandardButtons(QMessageBox.Yes|QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        # An unattended run must not wait for a hidden permission dialog forever.
        # Lack of an answer is denial, never implicit consent.
        QTimer.singleShot(60000, dialog.reject)
        payload['allowed']=(dialog.exec()==QMessageBox.Yes)
        payload['gate'].set()
        self.log('Freigabe','Erlaubt' if payload['allowed'] else 'Abgelehnt')

    def worker_done(self,result):
        self.stopbtn.setEnabled(False);self.send_btn.setEnabled(True)
        self.task_state.setText(task_status_text(result.get('status')))
        for widget in (self.task_meter, self.task_details, self.task_next):
            widget.hide()
        answer = result.get('content','')
        self.add_bubble('assistant',answer)
        self.log('Status','Aufgabe: '+result.get('status','unbekannt'))
        if result.get('status')=='failed' and ('Ollama' in answer or 'Modell' in answer):
            self.check_model_status()
        side_busy = (self.parallel_chat is not None and
                     self.parallel_chat.reply_worker is not None and
                     self.parallel_chat.reply_worker.isRunning())
        if side_busy or self._speaking:
            # Do not interrupt a side-chat answer just because the Agent finished.
            self.log('System','Der Hauptauftrag ist beendet; Ergebnis im Hauptchat.')
        elif (self.config.get('voice_enabled') or
              (self.listener and self.listener.isRunning())) and answer:
            self.start_speech(answer)
        else:
            self._conversation_ready()
        self.input.setFocus()

    def _conversation_ready(self):
        self.voice_muted.clear()
        if self.listener and self.listener.isRunning():
            self.listener.allow_follow_up()
            self.voice_state.setText('🎙 Bereit für deine Anschlussfrage')

    def start_speech(self, text):
        self.stop_speech()
        self.voice_muted.set()
        self.voice_speaking.set()
        self._speaking=True
        self._voice_generation+=1
        generation=self._voice_generation
        self.stopvoicebtn.setEnabled(True)
        self.voice_state.setText('🔊 SYTOX spricht …')
        mode=self.config.get('speech_engine','windows')
        if mode=='windows':
            speaker=Speaker(text)
            self.active_speaker=speaker
            self.speakers.append(speaker)
            speaker.error.connect(lambda error:self.log('Sprache',error))
            speaker.finished.connect(lambda sp=speaker,g=generation:self._speaker_finished(sp,g))
            speaker.start()
            return
        job=SpeechSynthesizer(text,self.config.copy())
        self.voice_jobs.append(job)
        job.audio_ready.connect(lambda path,g=generation:self._audio_ready(path,g))
        job.error.connect(lambda error,g=generation:self._speech_error(error,g))
        job.finished.connect(lambda j=job:self.voice_jobs.remove(j) if j in self.voice_jobs else None)
        job.start()

    def _speaker_finished(self,speaker,generation):
        if speaker in self.speakers:self.speakers.remove(speaker)
        if self.active_speaker is speaker:self.active_speaker=None
        if generation==self._voice_generation:self._finish_voice()

    def _audio_ready(self,path,generation):
        if generation!=self._voice_generation or not self._speaking:
            Path(path).unlink(missing_ok=True)
            return
        self._audio_path=Path(path)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()

    def _speech_error(self,error,generation):
        if generation==self._voice_generation:
            self.log('Fehler',error)
            self._finish_voice()

    def _media_status(self,status):
        if status==QMediaPlayer.MediaStatus.EndOfMedia and self._speaking:
            self._finish_voice()
        elif status==QMediaPlayer.MediaStatus.InvalidMedia and self._speaking:
            self.log('Fehler','Audioformat konnte nicht wiedergegeben werden.')
            self._finish_voice()

    def _media_error(self,error,detail):
        if error!=QMediaPlayer.Error.NoError and self._speaking:
            self.log('Fehler','Audio: '+str(detail))
            self._finish_voice()

    def _finish_voice(self):
        self.voice_speaking.clear()
        self._speaking=False
        self.stopvoicebtn.setEnabled(False)
        self.player.stop()
        self.player.setSource(QUrl())
        if self._audio_path:
            self._audio_path.unlink(missing_ok=True)
            self._audio_path=None
        self._conversation_ready()

    def stop_speech(self):
        self._voice_generation+=1
        for job in self.voice_jobs:
            job.stop_event.set()
        if self.active_speaker:
            self.active_speaker.stop_event.set()
        if self._speaking:
            self._finish_voice()


    def resume_task(self):
        if self.quick_worker is not None:return
        if self.worker and self.worker.isRunning():return
        tasks=[t for t in self.store.tasks(self.chat_id) if t['status'] in ('paused','failed','time_elapsed')]
        if not tasks:
            QMessageBox.information(self,'Keine Aufgabe','Keine pausierte oder fehlgeschlagene Aufgabe vorhanden.')
            return
        task=tasks[0]
        self.log('Status','Setze Auftrag fort: '+task['goal'][:90])
        self.start_worker(task['mode'],task_id=task['id'])

    def show_memories(self):
        """Review, correct, disable or delete local user memories."""
        dialog=QDialog(self)
        dialog.setWindowTitle('SYTOX · Langzeitgedächtnis')
        dialog.resize(760,520)
        lay=QVBoxLayout(dialog)

        enabled=QCheckBox('Wichtige Nutzerangaben automatisch lokal merken')
        enabled.setChecked(self.store.auto_memory_enabled())
        enabled.toggled.connect(self.store.set_auto_memory_enabled)
        lay.addWidget(enabled)

        note=QLabel(
            'Nur geeignete Aussagen aus deinen Nachrichten werden gespeichert. '
            'Keine Passwörter, Tokens oder erkannten sensiblen Angaben. '
            'Du kannst Erinnerungen hier bearbeiten oder löschen. '
            'Chatverläufe und Projektaufträge bleiben unabhängig davon gespeichert.'
        )
        note.setWordWrap(True)
        lay.addWidget(note)

        items=QListWidget()
        for m in self.store.list_memories():
            item=QListWidgetItem('[Manuell]  '+m['content'])
            item.setData(Qt.UserRole,('manual',m['id']))
            items.addItem(item)
        for m in self.store.list_memory_facts():
            label='[Automatisch · '+m['scope']+']  '+m['content']
            item=QListWidgetItem(label)
            item.setData(Qt.UserRole,('auto',m['id']))
            items.addItem(item)
        lay.addWidget(items,1)

        row=QHBoxLayout()
        editbtn=QPushButton('Automatische Erinnerung bearbeiten')
        editbtn.setObjectName('ghost')
        def edit_memory():
            item=items.currentItem()
            if not item:return
            origin,mid=item.data(Qt.UserRole)
            if origin!='auto':
                QMessageBox.information(dialog,'Manuelle Erinnerung',
                    'Manuelle Erinnerungen lassen sich über den Chat erneut speichern.')
                return
            old=item.text().split(']  ',1)[-1]
            new,accepted=QInputDialog.getMultiLineText(
                dialog,'Erinnerung korrigieren','Neuer Inhalt:',old)
            if not accepted or not new.strip():return
            self.store.update_memory_fact(mid,new)
            scope=item.text().split(']  ',1)[0]+']  '
            item.setText(scope+new.strip()[:350])
        editbtn.clicked.connect(edit_memory)
        row.addWidget(editbtn)

        delbtn=QPushButton('Ausgewählte Erinnerung löschen')
        def delete_memory():
            item=items.currentItem()
            if not item:return
            if QMessageBox.question(dialog,'Löschen',
                    'Diese Erinnerung aus dem Gedächtnis löschen? '
                    'Der ursprüngliche Chatverlauf wird dabei nicht gelöscht.'
                    )!=QMessageBox.Yes:
                return
            origin,mid=item.data(Qt.UserRole)
            if origin=='auto':
                self.store.delete_memory_fact(mid)
            else:
                self.store.delete_memory(mid)
            items.takeItem(items.row(item))
        delbtn.clicked.connect(delete_memory)
        row.addWidget(delbtn)
        lay.addLayout(row)
        dialog.exec()

    def _preferred_status_model(self):
        """Check the model saved for the selected conversation."""
        return select_chat_model('', self._chat_runtime_config())[0]

    def check_model_status(self):
        """Check the selected chat model without blocking mouse/keyboard UI."""
        if self.ollama_probe and self.ollama_probe.isRunning():
            self._probe_again = True
            return
        self.status_chip.setText('KI wird geprüft')
        self.model_status_label.setText('Verbindung wird geprüft …')
        self.ollama_probe = OllamaProbe(self.config['ollama_url'], self._preferred_status_model())
        self.ollama_probe.checked.connect(self._model_status_checked)
        self.ollama_probe.finished.connect(self._model_probe_finished)
        self.ollama_probe.start()

    def _model_status_checked(self, status: OllamaStatus):
        if self.ollama_probe and (self.ollama_probe.url != self.config['ollama_url'] or
                                  self.ollama_probe.model != self._preferred_status_model()):
            self._probe_again = True
        else:
            self.ollama_status = status
            self.model_status_label.setText(status.details)
            self.model_status_label.setToolTip(status.details)
            if status.ready:
                self.status_chip.setText('●  KI bereit')
                self.status_chip.setStyleSheet('color:#86E1BD;background:#173027;'
                    'border:1px solid #316049;border-radius:11px;padding:5px 11px;')
            else:
                self.status_chip.setText('●  ' + status.title)
                self.status_chip.setStyleSheet('color:#F3BB95;background:#30231F;'
                    'border:1px solid #6A4235;border-radius:11px;padding:5px 11px;')
                self.log('System', status.details)
    def _model_probe_finished(self):
        if self._probe_again:
            self._probe_again = False
            QTimer.singleShot(0, self.check_model_status)

    def show_model_help(self):
        dialog = OllamaHelpDialog(self._preferred_status_model(), self.ollama_status, self)
        if dialog.exec() == QDialog.Accepted and dialog.installed_model:
            key = ('project_model' if self.config.get('model_mode') == 'project'
                   else 'fast_model')
            self.config[key] = dialog.installed_model
            self.config_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
            self.model_name.setText(self._preferred_status_model())
            self.log('System', 'Ollama eingerichtet: ' + dialog.installed_model)
        self.check_model_status()

    def edit_settings(self):
        dialog=SettingsDialog(self.config,self)
        if dialog.exec()==QDialog.Accepted:
            self.config=dialog.values()
            self.config['model_mode'] = self.model_mode.currentData()
            self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')
            self.model_name.setText(
                'Automatische Auswahl' if self.config.get('model_mode') == 'auto'
                else self._preferred_status_model())
            if self.parallel_chat is not None:
                self.parallel_chat.config = dict(self.config, model_mode='fast')
            self.log('System','Einstellungen gespeichert.')
            self.check_model_status()

    def _show_pending_update_result(self):
        """Show a one-time update or rollback result from the detached helper."""
        from .updater import update_cache_dir
        result_file = update_cache_dir() / 'last_portable_update.json'
        if not result_file.is_file():
            return
        try:
            data = json.loads(result_file.read_text(encoding='utf-8'))
            result_file.unlink(missing_ok=True)
        except (OSError, ValueError):
            return
        status = data.get('status') if isinstance(data, dict) else None
        message = str(data.get('message') or '')[:500] if isinstance(data, dict) else ''
        if status == 'rolled_back':
            self.log('Update', message)
            QMessageBox.warning(self, 'SYTOX Update wiederhergestellt',
                                message or 'Das Update wurde zurückgesetzt.')
        elif status == 'success':
            self.log('Update', message or 'SYTOX wurde erfolgreich aktualisiert.')
        elif status == 'failed':
            self.log('Update', message)
            QMessageBox.warning(self, 'SYTOX Update fehlgeschlagen',
                                message or 'Das Update wurde nicht abgeschlossen.')

    def check_for_updates(self, manual=False):
        """Only query release metadata on a worker; never block the Qt interface."""
        if self._update_check_worker and self._update_check_worker.isRunning():
            return
        if self._update_download_worker and self._update_download_worker.isRunning():
            return
        if manual:
            self.update_button.setText('Prüfe GitHub …')
            self.update_button.setEnabled(False)
        worker = UpdateCheckWorker()
        self._update_check_worker = worker
        worker.result_ready.connect(lambda info, error: self._update_checked(info, error, manual))
        worker.start()

    def _update_checked(self, info, error, manual):
        self.update_button.setText('Nach Updates suchen')
        self.update_button.setEnabled(True)
        if error:
            self.log('Update', 'Suche fehlgeschlagen: ' + error)
            if manual:
                QMessageBox.warning(self, 'SYTOX Update', error)
            return
        if info is None:
            if manual:
                QMessageBox.information(self, 'SYTOX Update', 'Keine neuere veröffentlichte Version verfügbar.')
            return
        self.log('Update', 'Neue Version ' + info.version + ' auf GitHub verfügbar.')
        if not is_installed_app():
            QMessageBox.information(
                self, 'SYTOX Update',
                'Version ' + info.version + ' ist verfügbar. Automatische Installation '
                'ist nur mit dem Windows-Installer möglich.\n' + info.release_url)
            return
        if QMessageBox.question(
                self, 'SYTOX Update ' + info.version,
                'SYTOX ' + info.version + ' ist verfügbar.\n'
                + ('Geprüftes Direkt-Update herunterladen und danach ohne Installer aktualisieren?\n'
                   if info.has_portable else
                   'Geprüftes Update herunterladen? Diese ältere Release-Version benötigt noch einmal den integrierten Installer.\n')
                + 'Die Aktualisierung startet erst nach deiner zweiten Bestätigung.',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.update_button.setEnabled(False)
        self.update_button.setText('Update wird geladen …')
        worker = UpdateDownloadWorker(info)
        self._update_download_worker = worker
        worker.progress.connect(lambda pct: self.update_button.setText('Update: ' + str(pct) + '%'))
        worker.result_ready.connect(self._update_downloaded)
        worker.start()

    def _update_downloaded(self, path, error):
        # The completion signal is emitted just before QThread.run returns.
        # Ensure shutdown does not mistake a completed download for an active one.
        if self._update_download_worker:
            self._update_download_worker.wait(2000)
        self.update_button.setEnabled(True)
        self.update_button.setText('Nach Updates suchen')
        if error:
            QMessageBox.warning(self, 'SYTOX Update', 'Download abgebrochen: ' + error)
            return
        package = (self._update_download_worker.update
                   if self._update_download_worker else None)
        direct = bool(package and package.has_portable)
        self.log('Update', ('Direkt-Update vorbereitet' if direct else 'Installer heruntergeladen')
                 + ' und SHA-256 geprüft.')
        if self.quick_worker is not None or (self.worker and self.worker.isRunning()):
            QMessageBox.information(self, 'Auftrag läuft',
                'Update sicher heruntergeladen. Bitte zuerst den laufenden Auftrag '
                'abschließen oder stoppen und dann erneut nach Updates suchen.')
            return
        if QMessageBox.question(
                self, 'SYTOX aktualisieren',
                ('Das geprüfte Direkt-Update ist vorbereitet.\n'
                 'SYTOX jetzt beenden, automatisch aktualisieren und neu starten?\n'
                 'Bei einem Startfehler wird die vorige Version wiederhergestellt.\n'
                 if direct else
                 'Das geprüfte Legacy-Update wurde heruntergeladen.\n'
                 'SYTOX jetzt beenden und den integrierten Installer starten?\n')
                + 'Deine Chats, Projekte und Einstellungen bleiben gespeichert.',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            if direct:
                schedule_portable_update(path)
            else:
                schedule_installer(path)
        except Exception as exc:
            QMessageBox.warning(self, 'SYTOX Update', str(exc))
            return
        self.exit_app()

    def install_voice_model(self):
        """Download an optional offline speech model only after explicit consent."""
        if self.voice_download and self.voice_download.isRunning():
            return
        if QMessageBox.question(
            self, 'Spracherkennung einrichten',
            'Deutsches Vosk-Sprachmodell herunterladen (ca. 45 MB)?\n'
            'Das Mikrofon bleibt lokal; für den Download wird Internet benötigt.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        dialog=QDialog(self)
        dialog.setWindowTitle('Deutsche Spracherkennung')
        dialog.setMinimumWidth(420)
        box=QVBoxLayout(dialog)
        message=QLabel('Download wird vorbereitet …')
        box.addWidget(message)
        bar=QProgressBar();bar.setRange(0,100);box.addWidget(bar)
        cancel=QPushButton('Download abbrechen');box.addWidget(cancel)
        worker=VoiceModelDownload()
        self.voice_download=worker
        self.voice_download_dialog=dialog

        def request_cancel():
            worker.cancel_event.set()
            cancel.setEnabled(False)
            message.setText('Download wird abgebrochen …')

        def downloaded(path):
            self.config['vosk_model']=path
            self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')
            self.log('Sprache','Deutsches Sprachmodell eingerichtet.')
            self.voice_state.setText('Sprachmodell bereit – Gesprächsmodus starten')
            dialog.accept()

        def download_error(text):
            self.log('Sprache',text)
            dialog.reject()
            QMessageBox.warning(self,'Sprachmodell',text)

        worker.progress_update.connect(lambda pct,msg: (bar.setValue(pct),message.setText(msg)))
        worker.installed.connect(downloaded)
        worker.error.connect(download_error)
        cancel.clicked.connect(request_cancel)
        dialog.rejected.connect(request_cancel)
        worker.finished.connect(lambda: setattr(self,'voice_download',None))
        worker.finished.connect(lambda: setattr(self,'voice_download_dialog',None))
        worker.finished.connect(dialog.deleteLater)
        dialog.show()
        worker.start()

    def show_parallel_chat(self):
        """Show temporary conversational context, never the agent's workspace."""
        if self.parallel_chat is None:
            self.parallel_chat = ParallelChatDialog(dict(self.config, model_mode='fast'), self)
            self.parallel_chat.answer_ready.connect(self._parallel_answer_ready)
            self.parallel_chat.control_requested.connect(self.handle_work_control)
            self.parallel_chat.status_requested.connect(self.report_agent_status)
            self.parallel_chat.change_requested.connect(self.queue_project_change)
            # Reuse the same explicit, user-visible approval dialog as the Agent.
            self.parallel_chat.approval_request.connect(self.handle_approval)
        self.parallel_chat.show()
        self.parallel_chat.raise_()
        self.parallel_chat.activateWindow()
        return self.parallel_chat

    def ask_parallel(self, question, spoken=False):
        dialog = self.show_parallel_chat()
        if not dialog.ask(question, spoken=spoken):
            self.log('Stimme' if spoken else 'System',
                     'Nebenunterhaltung ist gerade beschäftigt.')
            if spoken:
                self._conversation_ready()

    def _parallel_answer_ready(self, answer, spoken):
        # The main Worker and its stop_event are never touched here.
        if spoken and self.listener and self.listener.isRunning():
            self.start_speech(answer)
        else:
            self._conversation_ready()

    def report_agent_status(self, question='', spoken=False):
        """Answer status and ETA from live checkpoints without stopping the Agent."""
        active = bool(self.worker and self.worker.isRunning() and
                      not self.worker.stop_event.is_set())
        stopping = bool(self.worker and self.worker.isRunning() and
                        self.worker.stop_event.is_set())
        intent = agent_status_intent(question)
        if active and intent == 'eta':
            task = next((t for t in self.store.tasks(self.chat_id)
                         if t['status'] == 'running'), None)
            message = task_eta(task)['text']
        elif active:
            message = ('Der Programmierauftrag läuft weiter. Zuletzt gemeldet: '
                       + self._agent_last_status)
        elif stopping:
            message = 'Das Stoppen wurde angefordert; der Auftrag beendet gerade den laufenden Schritt.'
        else:
            message = 'Derzeit läuft kein Programmierauftrag.'
        dialog = self.show_parallel_chat()
        dialog.transcript.appendPlainText('DU: ' + question + '\\nSYTOX: ' + message + '\\n')
        if spoken and self.listener and self.listener.isRunning():
            self.start_speech(message)
        else:
            self._conversation_ready()
        return message

    def show_desktop_tools(self, query='', list_windows=False):
        """Open local desktop discovery; a separate approval precedes every action."""
        if self.desktop_tools_dialog is None:
            self.desktop_tools_dialog = DesktopControlDialog(parent=self)
        dialog = self.desktop_tools_dialog
        if list_windows:
            dialog.refresh_windows()
        if query:
            dialog.app_query.setText(str(query))
            dialog.search_apps()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def open_voice_diagnostics(self):
        if self.listener and self.listener.isRunning():
            QMessageBox.information(self,'Mikrofon belegt',
                'Bitte zuerst den Gesprächsmodus stoppen. Der Test benötigt das Mikrofon allein.')
            return
        if self.recorder and self.recorder.isRunning():
            QMessageBox.information(self,'Mikrofon belegt',
                'Bitte zuerst die laufende Sprachmemo beenden.')
            return
        dialog = VoiceDiagnosticsDialog(self.config.get('vosk_model',''), self)
        self.voice_diagnostic_dialog = dialog
        try:
            dialog.exec()
        finally:
            self.voice_diagnostic_dialog = None

    def toggle_listener(self, auto=False):
        if self.listener and self.listener.isRunning():
            self.listener.stop_event.set()
            self.voice_muted.clear()
            self.wakebtn.setText('Gesprächsmodus starten')
            self.voice_state.setText('Mikrofon aus')
            self.log('Sprache','Gesprächsmodus wird beendet.')
            return
        model_value = self.config.get('vosk_model','')
        model=Path(model_value)
        if not model_value or not model.is_dir() or not (model/'conf').is_dir():
            if auto:
                self.log('Sprache', 'Auto-Zuhören nicht gestartet: deutsches Vosk-Modell fehlt.')
                self.voice_state.setText('Sprachmodell fehlt – Einstellungen öffnen')
                return
            QMessageBox.information(self,'Sprachmodell fehlt',
                'Bitte erst Setup_Sprache.ps1 ausführen oder in den Einstellungen '
                'den Ordner eines deutschen Vosk-Sprachmodells eintragen.')
            return
        if self.recorder and self.recorder.isRunning():
            QMessageBox.information(self,'Mikrofon belegt','Bitte die Sprachmemo zuerst stoppen.')
            return
        require_wake=not self.config.get('voice_no_wake',False)
        self.listener=WakeListener(str(model), require_wake,
                                   self.config.get('voice_followup_seconds',25), self.voice_muted,
                                   self.voice_speaking,
                                   self.config.get('voice_interruptible', True))
        self.listener.wake_command.connect(self.received_voice_command)
        self.listener.interrupted.connect(self._voice_interrupted)
        self.listener.error.connect(lambda error:self.log('Fehler',error))
        self.listener.finished.connect(self._listener_finished)
        self.listener.start()
        self.wakebtn.setText('■  Gesprächsmodus stoppen')
        self.voice_state.setText('🎙 Zuhören …' if not require_wake else '🎙 Warte auf „Hey Sytox“')
        self.log('Sprache','Gesprächsmodus aktiv; Spracherkennung läuft lokal.')

    def _listener_finished(self):
        self.voice_muted.clear()
        self.wakebtn.setText('Gesprächsmodus starten')
        self.voice_state.setText('Mikrofon aus')

    def _voice_interrupted(self, next_command):
        """A wake phrase interrupts TTS; the resulting command uses normal approvals."""
        self.stop_speech()
        if next_command.strip():
            self.received_voice_command(next_command)
        else:
            self._conversation_ready()

    def received_voice_command(self,text):
        self.log('Stimme','Befehl gehört: '+text[:120])
        intent = work_intent(text)
        if intent:
            self.handle_work_control(intent, text, spoken=True)
            return
        if agent_status_intent(text):
            self.report_agent_status(text, spoken=True)
            return
        intent = desktop_voice_intent(text)
        if intent:
            kind, argument = intent
            if kind == 'stop_listening':
                if self.listener and self.listener.isRunning():
                    self.toggle_listener()
                self.voice_muted.clear()
                self.log('Sprache', 'Sprachmodus per Sprachbefehl beendet.')
                return
            self.show_desktop_tools(query=argument if kind == 'apps' else '',
                                    list_windows=kind == 'windows')
            self.log('Stimme', 'Windows-Steuerzentrale geöffnet; keine PC-Aktion ausgeführt.')
            self._conversation_ready()
            return
        if self.worker and self.worker.isRunning():
            if is_change_request(text):
                self.queue_project_change(text, spoken=True)
            else:
                self.ask_parallel(text, spoken=True)
            return
        self.input.setPlainText(text)
        self.send()

    def toggle_memo(self):
        if self.listener and self.listener.isRunning():
            self.mic_btn.setChecked(False)
            QMessageBox.information(self,'Mikrofon belegt','Bitte Gesprächsmodus zuerst stoppen.')
            return
        if self.recorder and self.recorder.isRunning():
            self.recorder.stop_event.set();self.mic_btn.setEnabled(False)
            self.mic_btn.setToolTip('Aufnahme wird verarbeitet …')
            self.log('Sprache','Aufnahme wird gespeichert/transkribiert …')
            return
        self.recorder=VoiceRecorder(self.config.get('vosk_model',''))
        self.recorder.finished_note.connect(self.memo_ready)
        self.recorder.start()
        self.mic_btn.setChecked(True)
        self.mic_btn.setToolTip('Aufnahme stoppen')
        self.log('Sprache','Aufnahme gestartet (Mikrofon).')

    def memo_ready(self,path,text):
        self.mic_btn.setChecked(False)
        self.mic_btn.setToolTip('Sprachaufnahme starten')
        self.mic_btn.setEnabled(True)
        if not path:
            QMessageBox.warning(self,'Mikrofon',text);return
        if text.startswith('[Spracherkennung fehlgeschlagen'):
            QMessageBox.warning(self,'Spracherkennung',text)
        if text and not text.startswith('['):
            self.input.setPlainText(text)
            self.log('Sprache','Transkription eingefügt: '+text[:120])
        else:
            self.log('Sprache','Sprachmemo gespeichert: '+path+' – Vosk-Modell erforderlich zur Transkription.')
            QMessageBox.information(self,'Memo gespeichert',
                'Aufgenommen: '+path+'\nZum Verstehen bitte unter Einstellungen den lokalen Vosk-Modellordner eintragen.')
