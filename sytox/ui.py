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

from PySide6.QtCore import Qt, QThread, Signal, QSize, QTimer, QUrl
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QKeyEvent, QKeySequence, QTextCursor, QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication,QWidget,QMainWindow,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QTextEdit,QPlainTextEdit,QListWidget,QListWidgetItem,QScrollArea,QSplitter,
    QMessageBox,QFileDialog,QLineEdit,QDialog,QFormLayout,QCheckBox,QComboBox,
    QSystemTrayIcon,QMenu,QInputDialog,QSpinBox,QFrame,QProgressBar
)
from .agent import Agent,OllamaClient
from .storage import Store,default_data_dir
from .voice_features import record_until,transcribe_wav,speak,render_speech_file,VoiceTurnRouter
from .ollama_setup import OllamaStatus, check_ollama_status, model_pull_command, OLLAMA_DOWNLOAD
from .ollama_installer import MODEL_CHOICES, SetupCancelled, setup_local_ollama, valid_local_endpoint

# SYTOX 0.2.5 design system: deep navy, raspberry accents, quiet status elements.
BG='#0B0D13'; PANEL='#121620'; SURFACE='#1B202D'; RED='#D34A7B'; LIGHT='#F4F5FA'; MUTED='#98A0B4'
QSS=f'''
QWidget {{ background: {BG}; color: {LIGHT}; font-family: 'Segoe UI'; font-size: 13px; }}
QToolTip {{ background: #242A39; color: white; border: 1px solid #3B4257; padding: 6px; }}
QFrame#sidebar {{ background: #10141E; border-right: 1px solid #252B3A; }}
QFrame#right {{ background: #10141E; border-left: 1px solid #252B3A; }}
QFrame#topbar {{ background: #121722; border-bottom: 1px solid #292F40; }}
QFrame#statusCard {{ background: #1A1F2C; border: 1px solid #30374B; border-radius: 14px; }}
QFrame#composePanel {{ background: #131824; border-top: 1px solid #272E3F; }}
QLabel#statusChip {{ color: #86E1BD; background: #16372E; border: 1px solid #295B4C;
    border-radius: 11px; padding: 5px 11px; font-weight: 600; font-size: 11px; }}
QLabel#sectionTitle {{ color: #DBE1F0; font-weight: 800; letter-spacing: 1px; font-size: 11px; }}
QPushButton {{ background: #252B3A; border: 1px solid #384054; border-radius: 11px;
    padding: 10px 14px; color: #F0F1F6; font-weight: 600; }}
QPushButton:hover {{ background: #30374B; border-color: #717B93; }}
QPushButton:pressed {{ background: #1B2131; }}
QPushButton:disabled {{ color: #687083; background: #1A1F2B; border-color: #292F3D; }}
QPushButton#primary {{ background: #B73565; border: 1px solid #E05283; color: white; }}
QPushButton#primary:hover {{ background: #CB4072; border-color: #FF85A9; }}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{ background: #1D2331;
    border: 1px solid #394156; border-radius: 11px; padding: 10px;
    color: #F4F5FA; selection-background-color: #A52E60; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{ border: 1px solid #D54C7E; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 9px; padding: 10px 12px; margin: 3px 4px; }}
QListWidget::item:selected {{ background: #493046; color: white; }}
QListWidget::item:hover {{ background: #242A3B; }}
QScrollArea {{ border: 0; }}
QScrollBar:vertical {{ background: #111620; width: 9px; }}
QScrollBar::handle:vertical {{ background: #414B63; border-radius: 4px; min-height: 22px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLabel#muted {{ color: {MUTED}; }}
QMenu {{ background: #202638; border: 1px solid #3A4358; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 25px; }}
QMenu::item:selected {{ background: #644057; }}
'''


def app_icon():
    resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    icon_file = resources / 'assets' / 'sytox.ico'
    if icon_file.exists():
        return QIcon(str(icon_file))
    pix=QPixmap(64,64);pix.fill(Qt.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(155,23,59));p.setPen(Qt.NoPen);p.drawRoundedRect(3,3,58,58,15,15)
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
            a=Agent(self.store,self.settings['model'],self.settings['ollama_url'],
                    self.settings['workspace'],self.request_approval,self.log_line.emit,self.stop_event,
                    self.settings.get('gmail_client_secrets',''))
            result=a.run(self.chat_id,self.mode,self.hours,self.task_id)
            self.completed.emit(result)
        except Exception as e:
            self.completed.emit({'status':'failed','content':f'{type(e).__name__}: {e}','task_id':self.task_id})


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
    error = Signal(str)
    hearing = Signal(str)

    def __init__(self, model_path, require_wake=True, follow_up_seconds=25, mute_event=None):
        super().__init__()
        self.model_path = model_path
        self.stop_event = threading.Event()
        self.mute_event = mute_event or threading.Event()
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
                if self.mute_event.is_set():
                    return
                try:
                    audio_queue.put_nowait(bytes(data))
                except queue.Full:
                    pass

            muted_before = False
            with sd.RawInputStream(samplerate=16000, channels=1, dtype='int16',
                                   callback=on_audio, blocksize=4000):
                while not self.stop_event.is_set():
                    if self.mute_event.is_set():
                        muted_before = True
                        while True:
                            try: audio_queue.get_nowait()
                            except queue.Empty: break
                        self.stop_event.wait(.06)
                        continue
                    if muted_before:
                        recognizer.Reset()  # no fragments from the previous utterance
                        muted_before = False
                    try:
                        audio = audio_queue.get(timeout=.25)
                    except queue.Empty:
                        continue
                    if not recognizer.AcceptWaveform(audio):
                        continue
                    phrase = json.loads(recognizer.Result()).get('text', '').strip()
                    command = self.router.command_for(phrase)
                    if command:
                        # Do not capture a second command while Qt is processing this turn.
                        self.mute_event.set()
                        self.wake_command.emit(command)
        except Exception as e:
            self.error.emit(f'Spracherkennung: {type(e).__name__}: {e}')


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
        heading = QLabel('◈  DEINE LOKALE KI EINRICHTEN')
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
        self.no_wake=QCheckBox('Nach Start des Gesprächs ohne „Hey Sytox“ zuhören (Mikrofon bleibt aktiv)')
        self.no_wake.setChecked(settings.get('voice_no_wake',False))
        self.follow_up=QSpinBox()
        self.follow_up.setRange(5,90)
        self.follow_up.setSuffix(' Sekunden')
        self.follow_up.setValue(int(settings.get('voice_followup_seconds',25)))
        form.addRow('Ollama-Modell',self.model)
        form.addRow('Ollama-Adresse',self.url)
        form.addRow('Projektordner',row)
        form.addRow('Vosk-Modellordner (Deutsch)',self.vosk)
        form.addRow('Piper EXE (optional)',self.piperexe)
        form.addRow('Piper Stimmenmodell (.onnx)',self.pipermodel)
        form.addRow('Sprachausgabe',self.speech_engine)
        form.addRow('Neurale Stimme',self.edge_voice)
        form.addRow('',self.edge_consent)
        form.addRow('',self.voice)
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
                'workspace':self.folder.text().strip(), 'vosk_model':self.vosk.text().strip(),
                'piper_exe':self.piperexe.text().strip(),'piper_model':self.pipermodel.text().strip(),
                'voice_enabled':self.voice.isChecked(),
                'speech_engine':self.speech_engine.currentData(),
                'edge_voice':self.edge_voice.currentData(),
                'edge_consent':self.edge_consent.isChecked(),
                'edge_rate':'+8%',
                'voice_no_wake':self.no_wake.isChecked(),
                'voice_followup_seconds':self.follow_up.value(),
                'gmail_client_secrets':self.gmail.text().strip()}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.store=Store();self.store.interrupted_tasks()
        self.config_path=default_data_dir()/'settings.json'
        self.config=self.load_settings()
        self.chat_id=None;self.worker=None;self.recorder=None;self.listener=None;self.speakers=[]
        self.voice_muted=threading.Event()
        self.voice_jobs=[]
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
        self.build_ui();self.setup_tray();self.reload_chats()
        if self.chatlist.count()==0:self.create_chat()
        else:self.select_chat(self.chatlist.item(0).data(Qt.UserRole))
        self.log('System','Bereit. Lokale Daten: '+str(default_data_dir()))
        QTimer.singleShot(700, self.check_model_status)

    def load_settings(self):
        base=default_data_dir();base.mkdir(parents=True,exist_ok=True)
        settings={'model':'qwen2.5-coder:7b','ollama_url':'http://localhost:11434',
                  'workspace':str(base/'projects'/'default'),'vosk_model':'',
                  'piper_exe':'','piper_model':'','voice_enabled':False,
                  'speech_engine':'windows','edge_voice':'de-DE-KatjaNeural','edge_rate':'+8%',
                  'edge_consent':False,'voice_no_wake':False,'voice_followup_seconds':25,
                  'gmail_client_secrets':''}
        default_model=base/'models'/'vosk-model-small-de-0.15'
        if default_model.is_dir(): settings['vosk_model']=str(default_model)
        if self.config_path.exists():
            try:settings.update(json.loads(self.config_path.read_text(encoding='utf-8')))
            except Exception:pass
        return settings

    def build_ui(self):
        central=QWidget();self.setCentralWidget(central)
        layout=QHBoxLayout(central);layout.setContentsMargins(0,0,0,0);layout.setSpacing(0)
        splitter=QSplitter(Qt.Horizontal);splitter.setHandleWidth(1);layout.addWidget(splitter)
        left=QFrame();left.setObjectName('sidebar');left.setMinimumWidth(210)
        l=QVBoxLayout(left);l.setContentsMargins(12,17,12,12)
        title=QLabel('◈  SYTOX  AI');title.setStyleSheet('font-size: 25px; font-weight: 900; color: #F5F5FB; padding: 11px 7px 3px')
        l.addWidget(title)
        subtitle=QLabel('DEIN PERSÖNLICHER ASSISTENT');subtitle.setObjectName('muted')
        subtitle.setStyleSheet('font-size: 10px; letter-spacing: 1px; color:#A0A8BB; padding: 0 8px 18px')
        l.addWidget(subtitle)
        btn_new=QPushButton('＋   Neuer Chat');btn_new.setObjectName('primary')
        btn_new.clicked.connect(self.create_chat);l.addWidget(btn_new)
        self.search=QLineEdit();self.search.setPlaceholderText('Chats suchen …')
        self.search.textChanged.connect(self.reload_chats);l.addWidget(self.search)
        self.chatlist=QListWidget();self.chatlist.itemClicked.connect(lambda it:self.select_chat(it.data(Qt.UserRole)))
        l.addWidget(self.chatlist,1)
        rename=QPushButton('Chat umbenennen');rename.clicked.connect(self.rename_chat);l.addWidget(rename)
        delete=QPushButton('Chat löschen');delete.clicked.connect(self.delete_chat);l.addWidget(delete)
        cfg=QPushButton('⚙  Einstellungen');cfg.clicked.connect(self.edit_settings);l.addWidget(cfg)
        splitter.addWidget(left)

        center=QWidget();c=QVBoxLayout(center);c.setContentsMargins(0,0,0,0);c.setSpacing(0)
        top=QFrame();top.setObjectName('topbar');th=QHBoxLayout(top);th.setContentsMargins(20,13,22,13)
        self.chat_heading=QLabel('SYTOX  /  Chat');self.chat_heading.setStyleSheet('font-size: 18px; font-weight: 750; color: #F2F3F9')
        th.addWidget(self.chat_heading);th.addStretch()
        self.model_name=QLabel(self.config['model']);self.model_name.setObjectName('muted')
        th.addWidget(self.model_name)
        self.status_chip=QLabel('◌  KI wird geprüft')
        self.status_chip.setObjectName('statusChip')
        th.addSpacing(14);th.addWidget(self.status_chip)
        c.addWidget(top)
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        self.msg_container=QWidget();self.msg_layout=QVBoxLayout(self.msg_container)
        self.msg_layout.setAlignment(Qt.AlignTop);self.msg_layout.setSpacing(15)
        self.msg_layout.setContentsMargins(27,20,27,20)
        scroll.setWidget(self.msg_container);c.addWidget(scroll,1);self.scroll=scroll
        compose=QFrame();compose.setObjectName('composePanel')
        cbox=QVBoxLayout(compose);cbox.setContentsMargins(20,12,20,13)
        upper=QHBoxLayout()
        self.mode=QComboBox();self.mode.addItems(['Einmal','1 Stunde arbeiten','3 Stunden arbeiten','Bis fertig'])
        self.mode.setMaximumWidth(220);upper.addWidget(self.mode)
        self.state=QLabel('● Bereit');self.state.setObjectName('muted');upper.addWidget(self.state)
        upper.addStretch();cbox.addLayout(upper)
        row=QHBoxLayout();self.input=InputBox();self.input.setPlaceholderText('Schreib deinem Assistenten …   (Shift+Enter = Zeilenumbruch)')
        self.input.setFixedHeight(85);self.input.send.connect(self.send)
        row.addWidget(self.input,1)
        right_buttons=QVBoxLayout()
        self.send_btn=QPushButton('➤ Senden');self.send_btn.setObjectName('primary');self.send_btn.clicked.connect(self.send)
        self.mic_btn=QPushButton('🎙 Memo');self.mic_btn.clicked.connect(self.toggle_memo)
        right_buttons.addWidget(self.send_btn);right_buttons.addWidget(self.mic_btn)
        row.addLayout(right_buttons);cbox.addLayout(row)
        c.addWidget(compose)
        splitter.addWidget(center)

        right=QFrame();right.setObjectName('right');r=QVBoxLayout(right);r.setContentsMargins(12,16,12,12)
        ollama_title=QLabel('◈  KI-VERBINDUNG');ollama_title.setObjectName('sectionTitle')
        r.addWidget(ollama_title)
        self.model_status_label=QLabel('Verbindung wird geprüft …')
        self.model_status_label.setObjectName('muted')
        self.model_status_label.setWordWrap(True)
        r.addWidget(self.model_status_label)
        status_buttons=QHBoxLayout()
        check_model=QPushButton('↻ Prüfen')
        check_model.clicked.connect(self.check_model_status)
        status_buttons.addWidget(check_model)
        setup_model=QPushButton('Einrichten')
        setup_model.clicked.connect(self.show_model_help)
        status_buttons.addWidget(setup_model)
        r.addLayout(status_buttons)
        lab=QLabel('◈  AGENT CONTROL');lab.setObjectName('sectionTitle')
        r.addWidget(lab)
        self.task_state=QLabel('Keine aktive Aufgabe');self.task_state.setWordWrap(True)
        self.task_state.setObjectName('muted');r.addWidget(self.task_state)
        self.stopbtn=QPushButton('■  Stoppen');self.stopbtn.setEnabled(False)
        self.stopbtn.clicked.connect(self.stop_work);r.addWidget(self.stopbtn)
        self.resume=QPushButton('▶  Letzte Aufgabe fortsetzen');self.resume.clicked.connect(self.resume_task)
        r.addWidget(self.resume)
        self.wakebtn=QPushButton('◉  Gesprächsmodus starten')
        self.wakebtn.clicked.connect(self.toggle_listener);r.addWidget(self.wakebtn)
        self.voice_state=QLabel('Mikrofon aus');self.voice_state.setObjectName('muted');r.addWidget(self.voice_state)
        self.stopvoicebtn=QPushButton('🔇  Sprachausgabe stoppen')
        self.stopvoicebtn.clicked.connect(self.stop_speech)
        self.stopvoicebtn.setEnabled(False);r.addWidget(self.stopvoicebtn)
        logs_title=QLabel('AKTIVITÄTEN');logs_title.setObjectName('sectionTitle');r.addWidget(logs_title)
        self.logs=QPlainTextEdit();self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(250);r.addWidget(self.logs,1)
        memory=QPushButton('Gespeicherte Erinnerungen');memory.clicked.connect(self.show_memories)
        r.addWidget(memory)
        splitter.addWidget(right)
        splitter.setSizes([260,820,280]);splitter.setStretchFactor(1,1)
        self.input.setFocus()

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
        # Closing the window should NOT shut down the assistant. Exit through
        # the tray menu (or Windows session shutdown) to quit the background app.
        if self.tray and not self._is_exiting:
            self.hide()
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
        self.stop_speech()
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
        if not hasattr(self,'chatlist'):return
        search=(self.search.text() if hasattr(self,'search') else '').lower()
        self.chatlist.clear()
        for chat in self.store.chats():
            if search not in chat['title'].lower():continue
            it=QListWidgetItem('◉  '+chat['title']);it.setData(Qt.UserRole,chat['id'])
            self.chatlist.addItem(it)
            if chat['id']==self.chat_id:self.chatlist.setCurrentItem(it)

    def create_chat(self):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'Auftrag läuft','Bitte erst den laufenden Auftrag stoppen.')
            return
        cid=self.store.create_chat();self.reload_chats();self.select_chat(cid)

    def select_chat(self,cid):
        if self.worker and self.worker.isRunning() and cid!=self.chat_id:
            QMessageBox.information(self,'Auftrag läuft','Während der Ausführung kann der Chat nicht gewechselt werden.')
            return
        self.chat_id=cid
        current=next((c for c in self.store.chats() if c['id']==cid),None)
        self.chat_heading.setText(current['title'] if current else 'Chat')
        self.reload_chats();self.clear_bubbles()
        for m in self.store.messages(cid): self.add_bubble(m['role'],m['content'])
        tasks=self.store.tasks(cid)
        self.task_state.setText((tasks[0]['status']+': '+tasks[0]['goal'][:85]) if tasks else 'Keine aktive Aufgabe')

    def rename_chat(self):
        if not self.chat_id:return
        text,ok=QInputDialog.getText(self,'Chat umbenennen','Neuer Titel:')
        if ok and text.strip():
            self.store.rename_chat(self.chat_id,text.strip());self.reload_chats()
            self.chat_heading.setText(text.strip())

    def delete_chat(self):
        if not self.chat_id:return
        if self.worker and self.worker.isRunning():return
        if QMessageBox.question(self,'Chat löschen','Diesen Chat mit allen Nachrichten wirklich löschen?')!=QMessageBox.Yes:return
        self.store.delete_chat(self.chat_id);self.chat_id=None;self.reload_chats()
        if self.chatlist.count():self.select_chat(self.chatlist.item(0).data(Qt.UserRole))
        else:self.create_chat()

    def clear_bubbles(self):
        while self.msg_layout.count():
            item=self.msg_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()

    def add_bubble(self,role,message):
        mine=role=='user'
        body=QFrame()
        body.setStyleSheet(('QFrame {background:#3B283E; border:1px solid #784362; border-radius:16px;}'
                            if mine else 'QFrame {background:#1A202D; border:1px solid #323C53; border-radius:16px;}'))
        b=QVBoxLayout(body);b.setContentsMargins(14,11,14,12);b.setSpacing(8)
        header=QLabel('DU' if mine else '◆  SYTOX AI')
        header.setStyleSheet('border:none;font-weight:800;font-size:11px;color:'+(('#FFC5DB' if mine else '#EC8DB5')))
        b.addWidget(header)
        label=QLabel(message);label.setTextFormat(Qt.PlainText)
        label.setWordWrap(True);label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setStyleSheet('border:none; font-size:13px;line-height:1.5;')
        b.addWidget(label)
        body.setMaximumWidth(750)
        row=QWidget();r=QHBoxLayout(row);r.setContentsMargins(0,0,0,0)
        if mine:r.addStretch(1)
        r.addWidget(body,5)
        if not mine:r.addStretch(1)
        self.msg_layout.addWidget(row)
        QTimer.singleShot(100,lambda:self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))

    def log(self,kind,text):
        self.logs.appendPlainText(f'{kind}: {text}')
        if kind in ('Status','Aktion'):
            self.state.setText(('● ' if kind=='Status' else '◆ ')+str(text)[:80])

    def send(self):
        txt=self.input.toPlainText().strip()
        if not txt:return
        if self.worker and self.worker.isRunning():return
        self.stop_speech()
        self.voice_muted.set()
        self.store.add_message(self.chat_id,'user',txt)
        self.add_bubble('user',txt)
        self.input.clear()
        messages=self.store.messages(self.chat_id)
        if len([m for m in messages if m['role']=='user'])==1:
            self.store.rename_chat(self.chat_id,txt[:46]+'…' if len(txt)>46 else txt[:46]);self.reload_chats()
            self.chat_heading.setText(txt[:46])
        mode={'Einmal':'once','1 Stunde arbeiten':'timed','3 Stunden arbeiten':'timed','Bis fertig':'until_done'}[self.mode.currentText()]
        hours=3.0 if self.mode.currentText().startswith('3') else 1.0
        duration=re.search(r'\b(\d+(?:[,.]\d+)?)\s*(?:stunden?|h)\b',txt.lower())
        if duration:
            hours=max(.02,min(float(duration.group(1).replace(',','.')),24.0))
            mode='timed'
        if re.search(r'\bbis (?:es |alles )?fertig\b',txt.lower()):mode='until_done'
        self.start_worker(mode,hours)

    def start_worker(self,mode='once',hours=1.0,task_id=None):
        self.voice_muted.set()
        self.worker=Worker(self.store,self.chat_id,self.config.copy(),mode,hours,task_id)
        self.worker.log_line.connect(self.log)
        self.worker.approval_request.connect(self.handle_approval)
        self.worker.completed.connect(self.worker_done)
        self.stopbtn.setEnabled(True);self.send_btn.setEnabled(False)
        self.task_state.setText('Läuft: '+(mode if mode!='timed' else f'{hours:g} h'))
        self.worker.start()

    def stop_work(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop_event.set();self.log('Status','Stopp angefordert …')

    def handle_approval(self,label,desc,payload):
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
        self.task_state.setText(result.get('status','unknown'))
        answer = result.get('content','')
        self.add_bubble('assistant',answer)
        self.log('Status','Aufgabe: '+result.get('status','unbekannt'))
        if result.get('status')=='failed' and ('Ollama' in answer or 'Modell' in answer):
            self.check_model_status()
        if (self.config.get('voice_enabled') or (self.listener and self.listener.isRunning())) and answer:
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
        if self.worker and self.worker.isRunning():return
        tasks=[t for t in self.store.tasks(self.chat_id) if t['status'] in ('paused','failed','time_elapsed')]
        if not tasks:
            QMessageBox.information(self,'Keine Aufgabe','Keine pausierte oder fehlgeschlagene Aufgabe vorhanden.')
            return
        task=tasks[0]
        self.log('Status','Setze Auftrag fort: '+task['goal'][:90])
        self.start_worker(task['mode'],task_id=task['id'])

    def show_memories(self):
        memories=self.store.list_memories()
        dialog=QDialog(self);dialog.setWindowTitle('Lokale Erinnerungen');dialog.resize(650,450)
        lay=QVBoxLayout(dialog)
        items=QListWidget()
        for m in memories:
            item=QListWidgetItem(str(m['id'])+'  '+m['content'])
            item.setData(Qt.UserRole,m['id']);items.addItem(item)
        lay.addWidget(items)
        delbtn=QPushButton('Ausgewählte Erinnerung löschen')
        def delete_memory():
            item=items.currentItem()
            if not item:return
            if QMessageBox.question(dialog,'Löschen','Diese Erinnerung löschen?')==QMessageBox.Yes:
                self.store.delete_memory(item.data(Qt.UserRole))
                items.takeItem(items.row(item))
        delbtn.clicked.connect(delete_memory);lay.addWidget(delbtn)
        dialog.exec()

    def check_model_status(self):
        """Check the configured Ollama model without blocking mouse/keyboard UI."""
        if self.ollama_probe and self.ollama_probe.isRunning():
            self._probe_again = True
            return
        self.status_chip.setText('◌  KI wird geprüft')
        self.model_status_label.setText('Verbindung wird geprüft …')
        self.ollama_probe = OllamaProbe(self.config['ollama_url'], self.config['model'])
        self.ollama_probe.checked.connect(self._model_status_checked)
        self.ollama_probe.finished.connect(self._model_probe_finished)
        self.ollama_probe.start()

    def _model_status_checked(self, status: OllamaStatus):
        if self.ollama_probe and (self.ollama_probe.url != self.config['ollama_url'] or
                                  self.ollama_probe.model != self.config['model']):
            self._probe_again = True
        else:
            self.ollama_status = status
            self.model_status_label.setText(status.details)
            self.model_status_label.setToolTip(status.details)
            if status.ready:
                self.status_chip.setText('●  KI bereit')
                self.status_chip.setStyleSheet('color:#86E1BD;background:#16372E;'
                    'border:1px solid #295B4C;border-radius:11px;padding:5px 11px;')
            else:
                self.status_chip.setText('●  ' + status.title)
                self.status_chip.setStyleSheet('color:#FFD7A7;background:#47301C;'
                    'border:1px solid #785332;border-radius:11px;padding:5px 11px;')
                self.log('System', status.details)
    def _model_probe_finished(self):
        if self._probe_again:
            self._probe_again = False
            QTimer.singleShot(0, self.check_model_status)

    def show_model_help(self):
        dialog = OllamaHelpDialog(self.config['model'], self.ollama_status, self)
        if dialog.exec() == QDialog.Accepted and dialog.installed_model:
            self.config['model'] = dialog.installed_model
            self.config_path.write_text(json.dumps(self.config, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
            self.model_name.setText(self.config['model'])
            self.log('System', 'Ollama eingerichtet: ' + self.config['model'])
        self.check_model_status()

    def edit_settings(self):
        dialog=SettingsDialog(self.config,self)
        if dialog.exec()==QDialog.Accepted:
            self.config=dialog.values()
            self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')
            self.model_name.setText(self.config['model'])
            self.log('System','Einstellungen gespeichert.')
            self.check_model_status()

    def toggle_listener(self):
        if self.listener and self.listener.isRunning():
            self.listener.stop_event.set()
            self.wakebtn.setText('◉  Gesprächsmodus starten')
            self.voice_state.setText('Mikrofon aus')
            self.log('Sprache','Gesprächsmodus wird beendet.')
            return
        model=Path(self.config.get('vosk_model',''))
        if not model.is_dir():
            QMessageBox.information(self,'Sprachmodell fehlt',
                'Bitte erst Setup_Sprache.ps1 ausführen oder in den Einstellungen '
                'den Ordner eines deutschen Vosk-Sprachmodells eintragen.')
            return
        if self.recorder and self.recorder.isRunning():
            QMessageBox.information(self,'Mikrofon belegt','Bitte die Sprachmemo zuerst stoppen.')
            return
        require_wake=not self.config.get('voice_no_wake',False)
        self.listener=WakeListener(str(model), require_wake,
                                   self.config.get('voice_followup_seconds',25), self.voice_muted)
        self.listener.wake_command.connect(self.received_voice_command)
        self.listener.error.connect(lambda error:self.log('Fehler',error))
        self.listener.finished.connect(self._listener_finished)
        self.listener.start()
        self.wakebtn.setText('■  Gesprächsmodus stoppen')
        self.voice_state.setText('🎙 Zuhören …' if not require_wake else '🎙 Warte auf „Hey Sytox“')
        self.log('Sprache','Gesprächsmodus aktiv; Spracherkennung läuft lokal.')

    def _listener_finished(self):
        self.wakebtn.setText('◉  Gesprächsmodus starten')
        self.voice_state.setText('Mikrofon aus')

    def received_voice_command(self,text):
        self.log('Stimme','Befehl gehört: '+text[:120])
        if re.fullmatch(r'\s*(?:stopp|stop|anhalten|sei still|ruhe)\s*[.!?]*',text.lower()):
            self.stop_speech()
            self.stop_work()
            self._conversation_ready()
            return
        if self.worker and self.worker.isRunning():
            self.log('Stimme','Noch beschäftigt. Bitte nach dem Auftrag erneut sprechen.')
            self._conversation_ready()
            return
        self.input.setPlainText(text)
        self.send()

    def toggle_memo(self):
        if self.listener and self.listener.isRunning():
            QMessageBox.information(self,'Mikrofon belegt','Bitte Gesprächsmodus zuerst stoppen.')
            return
        if self.recorder and self.recorder.isRunning():
            self.recorder.stop_event.set();self.mic_btn.setEnabled(False)
            self.log('Sprache','Aufnahme wird gespeichert/transkribiert …')
            return
        self.recorder=VoiceRecorder(self.config.get('vosk_model',''))
        self.recorder.finished_note.connect(self.memo_ready)
        self.recorder.start()
        self.mic_btn.setText('■ Aufnahme stoppen')
        self.log('Sprache','Aufnahme gestartet (Mikrofon).')

    def memo_ready(self,path,text):
        self.mic_btn.setText('🎙 Memo');self.mic_btn.setEnabled(True)
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
