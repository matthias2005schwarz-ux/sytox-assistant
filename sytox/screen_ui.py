"""Voice and chat routing for the opt-in native screen helper."""
import re

from .screen_intents import screen_intent
from .screen_panel import ScreenPanel
from .screen_question import ScreenQuestion
from .screen_state import ScreenState
from .ui import MainWindow, OllamaHelpDialog


class ScreenMainWindow(ScreenPanel, ScreenQuestion, ScreenState, MainWindow):
    def __init__(self):
        super().__init__()
        self.initialize_screen()

    def _screen_command(self, text, spoken=False):
        action = screen_intent(text)
        if action == 'stop':
            self.stop_screen()
            if spoken and self.listener and self.listener.isRunning():
                self.start_speech('Bildschirmhilfe ausgeschaltet.')
            return True
        if action == 'start':
            self.start_screen()
            match = re.search(r'(?i)\b(?:bildschirm|screen)\b[ ,:;.!?-]*(.*)$', text)
            question = match.group(1).strip() if match else ''
            if re.match(r'(?i)^(?:was|wie|warum|wieso|wo|welche|hilf|erklär)', question):
                self.ask_screen(question)
            elif spoken and self.listener and self.listener.isRunning():
                self.start_speech('Bildschirmhilfe aktiv. Was soll ich mir ansehen?')
            return True
        if self.screen_active:
            self.ask_screen(text)
            return True
        return False

    def send(self):
        text = self.input.toPlainText().strip()
        if text and self._screen_command(text):
            self.input.clear()
            return
        super().send()

    def received_voice_command(self, text):
        if self._screen_command(text, spoken=True):
            return
        super().received_voice_command(text)

    def install_screen_model(self):
        """Reuse the existing consent-based local Ollama setup dialog."""
        dialog = OllamaHelpDialog('qwen3-vl:2b', None, self)
        dialog.exec()

    def exit_app(self):
        self.stop_screen()
        super().exit_app()
