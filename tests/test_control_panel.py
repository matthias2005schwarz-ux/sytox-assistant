"""Native controls keep optional details quiet without changing running work."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QPushButton
from sytox.ui import MainWindow


class ControlPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-control-panel-test'])

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'APPDATA': self.home.name})
        self.environment.start()
        self.probe = patch.object(MainWindow, 'check_model_status')
        self.updates = patch.object(MainWindow, 'check_for_updates')
        self.probe.start()
        self.updates.start()
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
        self.probe.stop()
        self.updates.stop()
        self.environment.stop()
        self.home.cleanup()

    def test_optional_panels_start_collapsed_with_important_controls_available(self):
        for toggle, body in (
            (self.window.voice_panel_toggle, self.window.voice_panel_body),
            (self.window.activity_panel_toggle, self.window.activity_panel_body),
        ):
            self.assertTrue(toggle.isCheckable())
            self.assertFalse(toggle.isChecked())
            self.assertTrue(body.isHidden())
        self.assertTrue(self.window.voice_state.isVisible())
        memory = next(button for button in self.window.findChildren(QPushButton)
                      if button.text() == 'Gespeicherte Erinnerungen')
        self.assertTrue(memory.isVisible())
        self.assertTrue(self.window.stopbtn.isVisible())

    def test_toggling_panels_preserves_logs_and_running_work(self):
        running = MagicMock()
        running.isRunning.return_value = True
        self.window.worker = running
        self.window.log('System', 'Eintrag vor dem Aufklappen')
        for toggle, body in (
            (self.window.voice_panel_toggle, self.window.voice_panel_body),
            (self.window.activity_panel_toggle, self.window.activity_panel_body),
        ):
            toggle.click()
            self.assertFalse(body.isHidden())
            toggle.click()
            self.assertTrue(body.isHidden())
        self.assertIn('Eintrag vor dem Aufklappen', self.window.logs.toPlainText())
        running.stop_event.set.assert_not_called()
        self.assertIs(self.window.worker, running)

    def test_progress_is_hidden_idle_and_visible_before_first_checkpoint(self):
        self.window.refresh_live_progress()
        for control in (self.window.task_meter, self.window.task_details, self.window.task_next):
            self.assertTrue(control.isHidden())
        self.window.worker = MagicMock()
        self.window.worker.isRunning.return_value = True
        self.window.refresh_live_progress()
        self.assertFalse(self.window.task_meter.isHidden())
        task = self.window.store.create_task(self.window.chat_id, 'Code schreiben')
        self.window.store.update_task(task, 'running', {'steps': 2, 'writes': 1})
        self.window.refresh_live_progress()
        self.assertIn('2 Schritte', self.window.task_details.text())
        self.assertFalse(self.window.task_details.isHidden())

    def test_completed_reply_hides_progress_even_before_thread_finished_signal(self):
        self.window.worker = MagicMock()
        self.window.worker.isRunning.return_value = True
        self.window.refresh_live_progress()
        self.window.worker_done({'status': 'done', 'content': 'Erledigt.'})
        for control in (self.window.task_meter, self.window.task_details, self.window.task_next):
            self.assertTrue(control.isHidden())
        self.assertFalse(self.window.stopbtn.isEnabled())


if __name__ == '__main__':
    unittest.main()
