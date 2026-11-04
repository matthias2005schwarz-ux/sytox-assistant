"""Separate, read-only conversation while a tool-using Agent keeps working.

This short conversation has its own Qt thread and history. It never receives
the Agent toolkit, approval hooks, or the project workspace, and cannot stop
or mutate the active task. Model inference can still be slower when both
threads share one local Ollama model/GPU.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit,
)

from .agent import OllamaClient


SYSTEM_PROMPT = (
    "Du bist SYTOX im separaten Gesprächsmodus, während ein anderer Agent "
    "im Hintergrund an einer Aufgabe arbeitet. Antworte kurz, freundlich "
    "und ehrlich auf Deutsch. Du hast hier KEINE Werkzeuge und kannst "
    "nichts am PC ausführen. Behaupte niemals, eine Datei geändert oder "
    "den anderen Auftrag gestoppt zu haben. Anweisungen zu Arbeiten am "
    "laufenden Projekt können hier nicht direkt übernommen werden; bitte "
    "den Nutzer, sie nach dem laufenden Auftrag als neuen Auftrag zu schicken."
)


class ParallelReplyWorker(QThread):
    """Tool-free Ollama request; independent of the long-running Agent thread."""

    completed = Signal(str)

    def __init__(self, config, history, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.history = list(history)
        self.stop_event = threading.Event()

    def run(self):
        try:
            client = OllamaClient(
                self.config['ollama_url'], self.config['model']
            )
            reply = client.chat(
                [{'role': 'system', 'content': SYSTEM_PROMPT}] + self.history,
                tools=None, stop=self.stop_event,
            )
            text = str(reply.get('content') or '').strip()
            self.completed.emit(text or 'Dazu habe ich gerade keine Antwort erhalten.')
        except Exception as exc:
            self.completed.emit(
                'Die kurze Antwort ist fehlgeschlagen: '
                + type(exc).__name__ + ': ' + str(exc)
            )


class ParallelChatDialog(QDialog):
    """Temporary chat with its own context, separate from the active task."""

    answer_ready = Signal(str, bool)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.history = []
        self.reply_worker = None
        self._spoken_question = False
        self.setWindowTitle('SYTOX · Nebenunterhaltung')
        self.setMinimumSize(480, 400)
        self.resize(610, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(11)
        heading = QLabel('MIT SYTOX SPRECHEN')
        heading.setObjectName('sectionTitle')
        root.addWidget(heading)
        explanation = QLabel(
            'Der Hauptauftrag arbeitet weiter. Diese Unterhaltung ist getrennt '
            'und darf keine Dateien oder Windows-Programme ändern.'
        )
        explanation.setObjectName('panelDescription')
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        self.transcript = QPlainTextEdit()
        self.transcript.setObjectName('parallelTranscript')
        self.transcript.setAccessibleName('Nebenunterhaltung')
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText('Frag SYTOX etwas, während der Agent arbeitet …')
        root.addWidget(self.transcript, 1)

        input_row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setAccessibleName('Frage an SYTOX')
        self.question.setPlaceholderText('Deine Frage …')
        self.question.returnPressed.connect(self.submit)
        input_row.addWidget(self.question, 1)
        self.send_btn = QPushButton('Fragen')
        self.send_btn.setObjectName('primary')
        self.send_btn.clicked.connect(self.submit)
        input_row.addWidget(self.send_btn)
        root.addLayout(input_row)

        self.status_label = QLabel('Bereit – der Hauptauftrag läuft unabhängig weiter.')
        self.status_label.setObjectName('panelDescription')
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def submit(self):
        text = self.question.text().strip()
        if self.ask(text, spoken=False):
            self.question.clear()

    def ask(self, question, spoken=False):
        """Submit one conversational turn; never touch the main task worker."""
        text = str(question or '').strip()
        if not text:
            return False
        if self.reply_worker is not None and self.reply_worker.isRunning():
            self.status_label.setText('Ich beantworte noch die vorherige Frage.')
            return False
        self._spoken_question = bool(spoken)
        self.transcript.appendPlainText('DU: ' + text + '\n')
        self.history.append({'role': 'user', 'content': text})
        # Cap conversational context without losing its distinct role order.
        context = self.history[-12:]
        self.reply_worker = ParallelReplyWorker(self.config, context, self)
        self.reply_worker.completed.connect(self._reply_done)
        self.reply_worker.start()
        self.status_label.setText('SYTOX antwortet – Hauptauftrag läuft unabhängig.')
        self.send_btn.setEnabled(False)
        return True

    def _reply_done(self, answer):
        self.history.append({'role': 'assistant', 'content': answer})
        self.transcript.appendPlainText('SYTOX: ' + answer + '\n')
        self.status_label.setText('Bereit für eine weitere Frage.')
        self.send_btn.setEnabled(True)
        self.answer_ready.emit(answer, self._spoken_question)

    def closeEvent(self, event):
        # Hiding the side conversation must not cancel the active Agent or
        # destroy a QThread which is still processing a model response.
        if self.reply_worker is not None and self.reply_worker.isRunning():
            self.hide()
            event.ignore()
        else:
            super().closeEvent(event)

    def stop_reply(self):
        if self.reply_worker is not None and self.reply_worker.isRunning():
            self.reply_worker.stop_event.set()
            return self.reply_worker.wait(4500)
        return True
