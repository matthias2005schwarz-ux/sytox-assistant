"""Run an in-memory screenshot question on a daemon worker thread."""
import threading

from .screen_capture import screenshot_png
from .screen_vision import analyze_screenshot, DEFAULT_VISION_MODEL


class ScreenQuestion:
    def ask_screen(self, question):
        if not self.screen_active:
            return
        if self.screen_busy:
            self.log('Bildschirm', 'Vorherige Bildanalyse läuft noch.')
            return
        try:
            frame = screenshot_png()
        except Exception as exc:
            self._screen_error(self.screen_generation, str(exc))
            return
        generation = self.screen_generation
        stop = threading.Event()
        self.screen_cancel = stop
        self.screen_busy = True
        self.screen_state.setText('Aktiv · Screenshot wird lokal analysiert …')
        self.store.add_message(self.chat_id, 'user', question)
        self.add_bubble('user', question)
        self.log('Bildschirm', 'Ein Bild für diese Frage erfasst, nicht gespeichert.')

        def work():
            try:
                # The configured vision model is independent of the coding model.
                response = analyze_screenshot(
                    frame, question,
                    self.config.get('ollama_url', 'http://localhost:11434'),
                    self.config.get('vision_model', DEFAULT_VISION_MODEL),
                    cancel=stop)
                self.screen_signals.answer.emit(generation, response)
            except Exception as exc:
                self.screen_signals.error.emit(
                    generation, type(exc).__name__ + ': ' + str(exc)[:240])

        threading.Thread(target=work, daemon=True,
                         name='sytox-screen-question').start()
