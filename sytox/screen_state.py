"""Screen-sharing state and text-only replies for the native UI."""
from PySide6.QtCore import QObject, Signal


class ScreenSignals(QObject):
    answer = Signal(int, str)
    error = Signal(int, str)


class ScreenState:
    def initialize_screen(self):
        self.screen_active = False
        self.screen_generation = 0
        self.screen_busy = False
        self.screen_cancel = None
        self.screen_signals = ScreenSignals(self)
        self.screen_signals.answer.connect(self._screen_reply)
        self.screen_signals.error.connect(self._screen_error)

    def toggle_screen(self):
        self.stop_screen() if self.screen_active else self.start_screen()

    def start_screen(self):
        if self.screen_active:
            return
        self.screen_active = True
        self.screen_generation += 1
        self.screen_indicator.setText('● BILDSCHIRM AKTIV')
        self.screen_indicator.setStyleSheet('color:#E7505A;font-weight:bold;')
        self.screen_state.setText('Aktiv · nur auf deine Frage wird ein Bild gemacht.')
        self.screen_toggle.setText('■ Bildschirmhilfe beenden')
        self.screen_ask.setEnabled(True)
        self.log('Bildschirm', 'Eingeschaltet. Noch kein Screenshot aufgenommen.')

    def stop_screen(self):
        if not getattr(self, 'screen_active', False):
            return
        self.screen_active = False
        self.screen_generation += 1
        if self.screen_cancel is not None:
            self.screen_cancel.set()
        self.screen_busy = False
        self.screen_indicator.setText('● BILDSCHIRM AUS')
        self.screen_indicator.setStyleSheet('')
        self.screen_state.setText('Aus · Bildschirm wird nicht erfasst.')
        self.screen_toggle.setText('Bildschirmhilfe einschalten')
        self.screen_ask.setEnabled(False)
        self.log('Bildschirm', 'Bildschirmfreigabe beendet.')

    def _screen_reply(self, generation, answer):
        if generation != self.screen_generation or not self.screen_active:
            return
        self.screen_busy = False
        self.screen_cancel = None
        self.screen_state.setText('Aktiv · nur auf deine Frage wird ein Bild gemacht.')
        self.store.add_message(self.chat_id, 'assistant', answer)
        self.add_bubble('assistant', answer)
        if self.listener and self.listener.isRunning():
            self.start_speech(answer)
        else:
            self._conversation_ready()

    def _screen_error(self, generation, error):
        if generation != self.screen_generation or not self.screen_active:
            return
        self.screen_busy = False
        self.screen_cancel = None
        self.screen_state.setText('Aktiv · Analyse fehlgeschlagen')
        text = 'Bildschirmhilfe: ' + str(error)
        self.log('Fehler', text)
        chosen = self.config.get('vision_model', 'qwen3-vl:4b')
        self.add_bubble('assistant', text + '\nBitte lokales Bildmodell prüfen: ' + str(chosen)[:100])
        self._conversation_ready()
