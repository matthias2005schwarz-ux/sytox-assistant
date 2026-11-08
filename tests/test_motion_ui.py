"""Native motion stays tied to real UI state, preferences and widget lifetime."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QAbstractAnimation
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea
from shiboken6 import isValid

from sytox.ui import MainWindow, SettingsDialog


class MotionUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-motion-ui'])

    def setUp(self):
        self.profile = tempfile.TemporaryDirectory()
        self.addCleanup(self.profile.cleanup)
        for context in (patch.dict(os.environ, {'APPDATA': self.profile.name}),
                        patch.object(MainWindow, 'check_model_status'),
                        patch.object(MainWindow, 'check_for_updates')):
            context.start()
            self.addCleanup(context.stop)
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.worker = None
        self.window._is_exiting = True
        if self.window.tray:
            self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_saved_reduced_motion_preserves_panel_preferences_and_applies_immediately(self):
        self.window.config.update(focus_mode=True, voice_panel_expanded=True)
        dialog = SettingsDialog(self.window.config, self.window)
        dialog.reduce_motion.setChecked(True)
        with patch('sytox.ui.SettingsDialog', return_value=dialog), \
             patch.object(dialog, 'exec', return_value=SettingsDialog.Accepted):
            self.window.edit_settings()
        saved = json.loads(self.window.config_path.read_text(encoding='utf-8'))
        self.assertTrue(saved['reduced_motion'])
        self.assertTrue(saved['focus_mode'])
        self.assertTrue(saved['voice_panel_expanded'])
        self.assertTrue(self.window.motion.reduced_motion)
        self.window._set_response_activity(True)
        self.assertEqual(self.window.activity_indicator._animation.state(), QAbstractAnimation.Stopped)
        reply = self.window.add_bubble('assistant', 'Eine neue Antwort ohne Übergang.')
        self.assertIsNone(reply.parentWidget().graphicsEffect())
        self.assertIsNone(reply.parentWidget().parentWidget().graphicsEffect())
        self.assertTrue(self.window.load_settings()['reduced_motion'])
        dialog.deleteLater()

    def test_focus_feedback_follows_the_input_without_stealing_keyboard_focus(self):
        self.window.input.setFocus()
        self.app.processEvents()
        self.assertTrue(self.window.input_card.property('composing'))
        self.window.search.setFocus()
        self.app.processEvents()
        self.assertFalse(self.window.input_card.property('composing'))
        self.assertTrue(self.window.search.hasFocus())

    def test_streamed_code_button_gets_motion_and_copy_feedback_keeps_raw_text(self):
        original = '**Grüße**\n\n```python\nprint("👋")\n'
        reply = self.window.add_bubble('assistant', original)
        self.app.processEvents()
        reply.setText(original + '```')
        self.app.processEvents()
        code = reply.findChild(QPushButton, 'copyCodeButton')
        self.assertIsNotNone(getattr(code, '_sytox_motion', None))
        answer = self.window.findChild(QPushButton, 'copyReplyButton')
        answer.click()
        self.assertEqual(answer.text(), 'Kopiert')
        self.assertEqual(self.app.clipboard().text(), original + '```')
        reply.setText(original + '```\nWeitere Erklärung.')
        answer.click()
        self.assertEqual(self.app.clipboard().text(), reply.text())
        self.assertTrue(answer._copy_feedback.isActive())
        self.window.clear_bubbles()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(isValid(answer))
        self.assertFalse(isValid(code))

    def test_worker_completion_stops_activity_before_its_thread_finishes(self):
        with patch('sytox.ui.Worker'):
            self.window.start_worker()
        self.assertTrue(self.window.activity_indicator._active)
        self.window.worker_done({'status': 'done', 'content': 'Tatsächlich abgeschlossen.'})
        self.assertFalse(self.window.activity_indicator._active)
        self.assertEqual(self.window.activity_indicator._animation.state(), QAbstractAnimation.Stopped)

    def test_settings_save_stays_visible_in_a_small_dialog_while_fields_scroll(self):
        dialog = SettingsDialog(self.window.config, self.window)
        dialog.resize(660, 460)
        dialog.show()
        self.app.processEvents()
        scroll = dialog.findChild(QScrollArea, 'settingsScroll')
        save = next(button for button in dialog.findChildren(QPushButton) if button.text() == 'Speichern')
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertTrue(dialog.rect().contains(save.geometry()))
        self.assertIs(save.parentWidget(), dialog)
        scroll.ensureWidgetVisible(dialog.reduce_motion)
        self.app.processEvents()
        self.assertTrue(dialog.reduce_motion.isVisible())
        dialog.close()
        dialog.deleteLater()

    def test_accepting_close_stops_activity_fades_and_progress_refresh(self):
        self.window._set_response_activity(True)
        self.window.add_bubble('assistant', 'Gerade eingeblendet.')
        self.assertTrue(self.window._progress_refresh.isActive())
        self.window._is_exiting = True
        self.window.close()
        self.assertFalse(self.window._progress_refresh.isActive())
        self.assertFalse(self.window.activity_indicator._active)
        self.assertEqual(self.window.motion._fades, {})


if __name__ == '__main__':
    unittest.main()
