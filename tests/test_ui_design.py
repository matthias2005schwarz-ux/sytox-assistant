"""Dependency-free visual contracts for the actual native Qt application."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class BlackCrimsonDesignTests(unittest.TestCase):
    def test_pure_black_and_crimson_theme_not_old_rose_palette(self):
        code = (ROOT / 'sytox/theme.py').read_text(encoding='utf-8')
        self.assertIn("BACKGROUND = '#09090C'", code)
        self.assertIn("ACCENT = '#D83B46'", code)
        for old in ('#D34A7B', '#B73565', '#EC8DB5', '#493046'):
            self.assertNotIn(old, code)

    def test_native_layout_cards_and_chat_visuals_are_real_controls(self):
        ui = (ROOT / 'sytox/ui.py').read_text(encoding='utf-8')
        theme = (ROOT / 'sytox/theme.py').read_text(encoding='utf-8')
        self.assertIn('QSplitter(Qt.Horizontal)', ui)
        self.assertIn("setObjectName('sidebar')", ui)
        self.assertIn("setObjectName('topbar')", ui)
        self.assertIn("setObjectName('right')", ui)
        self.assertIn("setObjectName('utilityCard')", ui)
        self.assertIn("setObjectName('bubbleUser' if mine else 'bubbleAssistant')", ui)
        for selector in ('QFrame#utilityCard', 'QFrame#bubbleUser', 'QFrame#bubbleAssistant',
                         'QFrame#hero', 'QPushButton#primary', 'QWidget#messageRow'):
            self.assertIn(selector, theme)
        self.assertIn('label.setTextFormat(Qt.PlainText)', ui)

    def test_empty_state_prompts_do_not_automatically_execute_commands(self):
        ui = (ROOT / 'sytox/ui.py').read_text(encoding='utf-8')
        begin = ui.index('    def _use_suggestion(self, prompt):')
        end = ui.index('    def _show_empty_state(self):', begin)
        suggestion = ui[begin:end]
        self.assertIn('self.input.setPlainText(prompt)', suggestion)
        self.assertNotIn('self.send(', suggestion)
        self.assertIn('QPropertyAnimation(', ui)
        self.assertIn('QGraphicsOpacityEffect(', ui)


    def test_focus_mode_has_native_toggle_and_keyboard_shortcuts(self):
        ui = (ROOT / 'sytox/ui.py').read_text(encoding='utf-8')
        theme = (ROOT / 'sytox/theme.py').read_text(encoding='utf-8')
        self.assertIn("setObjectName('panelToggle')", ui)
        self.assertIn("self.utility_panel.setVisible(not checked)", ui)
        self.assertIn("QShortcut(QKeySequence('Ctrl+Shift+F'), self)", ui)
        self.assertIn("QShortcut(QKeySequence('Ctrl+K'), self)", ui)
        self.assertIn("QShortcut(QKeySequence('Ctrl+N'), self)", ui)
        self.assertIn('QPushButton#panelToggle:checked', theme)
        self.assertIn('QLineEdit#chatSearch:focus', theme)

    def test_ui_version_label_matches_package(self):
        ui = (ROOT / 'sytox/ui.py').read_text(encoding='utf-8')
        version = (ROOT / 'sytox/__init__.py').read_text(encoding='utf-8')
        self.assertIn("__version__='0.3.3'", version)
        self.assertIn('VERSION 0.3.3', ui)


if __name__ == '__main__':
    unittest.main()
