"""Native controls keep optional details quiet without changing running work."""
import os
import tempfile
import unittest
from pathlib import Path
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

    def test_copy_reply_preserves_code_unicode_and_current_streamed_text(self):
        text = '```python\nprint("Grüße 👋")\n```\n<script>Nur Text</script>'
        label = self.window.add_bubble('assistant', text)
        button = self.window.findChild(QPushButton, 'copyReplyButton')
        self.assertIsNotNone(button)
        self.assertEqual(button.accessibleName(), 'Antwort kopieren')
        button.click()
        self.assertEqual(self.app.clipboard().text(), text)
        updated = text + '\nNoch ein gestreamter Satz.'
        label.setText(updated)
        button.click()
        self.assertEqual(self.app.clipboard().text(), updated)

    def test_user_bubble_has_no_reply_copy_button(self):
        self.window.add_bubble('user', 'Meine Nachricht')
        self.assertEqual(self.window.findChildren(QPushButton, 'copyReplyButton'), [])

    def test_chat_export_writes_utf8_saved_messages_without_unsent_draft(self):
        self.window.store.add_message(self.window.chat_id, 'user', 'Grüße 👋\n```python\nprint(1)\n```')
        self.window.input.setPlainText('Nicht gesendeter Entwurf')
        destination = Path(self.home.name) / 'Gespräch.txt'
        with patch('sytox.ui.QFileDialog.getSaveFileName', return_value=(str(destination), '')):
            self.window.export_chat()
        text = destination.read_text(encoding='utf-8')
        self.assertIn('Grüße 👋\n```python\nprint(1)\n```', text)
        self.assertNotIn('Nicht gesendeter Entwurf', text)
        self.assertEqual(len(self.window.store.messages(self.window.chat_id)), 1)

    def test_cancelled_export_does_not_read_or_write_the_chat(self):
        with patch('sytox.ui.QFileDialog.getSaveFileName', return_value=('', '')), \
             patch.object(self.window.store, 'chat_export_text') as export:
            self.window.export_chat()
            export.assert_not_called()

    def test_sidebar_search_finds_message_contents_in_chats_and_projects(self):
        chat = self.window.store.create_chat('Alltag')
        project = self.window.store.create_chat('Mein Projekt', kind='project')
        self.window.store.add_message(chat, 'user', 'Mein Kometenbeobachtungsplan')
        self.window.store.add_message(project, 'assistant', 'Kometenbeobachtung vorbereiten')
        self.window.search.setText('kometenbeobachtung')
        self.assertEqual(self.window.chatlist.count(), 1)
        self.assertEqual(self.window.projectlist.count(), 1)
        self.window.search.setText('Mein Projekt')
        self.assertEqual(self.window.chatlist.count(), 0)
        self.assertEqual(self.window.projectlist.count(), 1)

    def test_new_chat_clears_search_so_it_is_visible(self):
        self.window.search.setText('Kein Treffer')
        self.assertEqual(self.window.chatlist.count(), 0)
        self.window.create_chat()
        self.assertEqual(self.window.search.text(), '')
        self.assertEqual(self.window.chatlist.count(), 2)

    def test_code_blocks_are_copied_individually_without_fences_or_explanation(self):
        self.window.add_bubble('assistant', 'Erklärung\n```python\nprint("Grüße")\n```\n'
                               'Dazwischen\n~~~js\nconsole.log(1);\n~~~')
        buttons = self.window.findChildren(QPushButton, 'copyCodeButton')
        self.assertEqual(len(buttons), 2)
        buttons[0].click()
        self.assertEqual(self.app.clipboard().text(), 'print("Grüße")\n')
        buttons[1].click()
        self.assertEqual(self.app.clipboard().text(), 'console.log(1);\n')

    def test_streamed_code_gets_copy_button_only_after_closing_fence(self):
        label = self.window.add_bubble('assistant', '```python\nprint(1)')
        self.assertEqual(self.window.findChildren(QPushButton, 'copyCodeButton'), [])
        label.setText('```python\nprint(1)\n```')
        button = self.window.findChild(QPushButton, 'copyCodeButton')
        self.assertIsNotNone(button)
        button.click()
        self.assertEqual(self.app.clipboard().text(), 'print(1)\n')

    def test_opening_chat_translates_stored_task_status(self):
        task = self.window.store.create_task(self.window.chat_id, 'Code prüfen')
        self.window.store.update_task(task, 'paused')
        self.window.select_chat(self.window.chat_id)
        self.assertIn('Aufgabe pausiert', self.window.task_state.text())
        self.assertNotIn('paused', self.window.task_state.text())
        self.assertEqual(self.window.store.tasks(self.window.chat_id)[0]['status'], 'paused')

    def test_chat_drafts_are_isolated_and_restored_without_saving_messages(self):
        first = self.window.chat_id
        second = self.window.store.create_chat('Zweiter Chat')
        draft = 'Grüße 👋\n```python\nprint("noch nicht senden")\n```'
        self.window.input.setPlainText(draft)
        self.window.select_chat(second)
        self.assertEqual(self.window.input.toPlainText(), '')
        self.window.input.setPlainText('Entwurf für den zweiten Chat')
        self.window.select_chat(first)
        self.assertEqual(self.window.input.toPlainText(), draft)
        self.window.select_chat(second)
        self.assertEqual(self.window.input.toPlainText(), 'Entwurf für den zweiten Chat')
        self.window.select_chat(second)
        self.assertEqual(self.window.input.toPlainText(), 'Entwurf für den zweiten Chat')
        self.assertEqual(self.window.store.messages(first), [])
        self.assertEqual(self.window.store.messages(second), [])

    def test_expanded_and_collapsed_panel_preferences_survive_reopening(self):
        def dispose(window):
            window._is_exiting = True
            if window.tray:
                window.tray.hide()
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()

        self.window.voice_panel_toggle.click()
        self.window.activity_panel_toggle.click()
        reopened = MainWindow()
        try:
            for toggle, body in (
                (reopened.voice_panel_toggle, reopened.voice_panel_body),
                (reopened.activity_panel_toggle, reopened.activity_panel_body),
            ):
                self.assertTrue(toggle.isChecked())
                self.assertFalse(body.isHidden())
                toggle.click()
        finally:
            dispose(reopened)
        collapsed = MainWindow()
        try:
            for toggle, body in (
                (collapsed.voice_panel_toggle, collapsed.voice_panel_body),
                (collapsed.activity_panel_toggle, collapsed.activity_panel_body),
            ):
                self.assertFalse(toggle.isChecked())
                self.assertTrue(body.isHidden())
        finally:
            dispose(collapsed)

    def test_focus_mode_survives_reopening_and_can_be_disabled_again(self):
        self.window.toggle_focus_mode(True)
        reopened = MainWindow()
        try:
            self.assertTrue(reopened.focus_btn.isChecked())
            self.assertTrue(reopened.utility_panel.isHidden())
            reopened.toggle_focus_mode(False)
        finally:
            reopened._is_exiting = True
            if reopened.tray:
                reopened.tray.hide()
            reopened.close()
            reopened.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
        self.assertFalse(self.window.load_settings()['focus_mode'])


if __name__ == '__main__':
    unittest.main()
