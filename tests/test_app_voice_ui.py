"""Voice and typed app commands use native discovery, never the language model."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sytox.ui import MainWindow
from sytox.voice_features import VoiceTurnRouter


class LocalDesktop:
    def __init__(self, shortcut):
        self.shortcut = shortcut
        self.apps = [{'name': shortcut.stem, 'path': str(shortcut)}]
        self.opened = []
        self.focused = []
        self.release = None
        self.entered = threading.Event()

    def find_app_windows(self, query):
        return []

    def find_apps(self, query):
        self.entered.set()
        if self.release is not None:
            self.release.wait(3)
        return [dict(app) for app in self.apps if query.casefold() in app['name'].casefold()]

    def open_app(self, path):
        self.opened.append(path)

    def activate(self, window_id):
        self.focused.append(window_id)


class AppVoiceUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-app-voice'])

    def setUp(self):
        self.profile = tempfile.TemporaryDirectory()
        self.addCleanup(self.profile.cleanup)
        path = Path(self.profile.name) / 'Spotify.lnk'
        path.write_bytes(b'local-test-shortcut-never-executed')
        self.desktop = LocalDesktop(path)
        for context in (patch.dict(os.environ, {'APPDATA': self.profile.name}),
                        patch.object(MainWindow, 'check_model_status'),
                        patch.object(MainWindow, 'check_for_updates'),
                        patch('sytox.app_launch_ui.WindowsDesktop', return_value=self.desktop)):
            context.start()
            self.addCleanup(context.stop)
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        if self.desktop.release:
            self.desktop.release.set()
        dialog = self.window.app_launch_dialog
        if dialog:
            self.wait_for(lambda: not dialog.lookup_running)
            dialog.prepare_close()
        self.window.worker = None
        self.window._is_exiting = True
        if self.window.tray:
            self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(5)
        self.assertTrue(predicate(), 'Native app lookup did not settle')
        self.app.processEvents()

    def ready_dialog(self):
        dialog = self.window.app_launch_dialog
        self.assertIsNotNone(dialog)
        self.wait_for(lambda: dialog._lookup_worker is None)
        return dialog

    def test_wake_command_opens_the_unique_program_without_click_model_or_agent(self):
        command = VoiceTurnRouter().command_for('Hey Sytox, öffne Spotify')
        with patch.object(self.window, 'send') as send, \
             patch.object(self.window, 'start_worker') as agent, \
             patch.object(self.window, 'start_quick_reply') as quick:
            self.window.received_voice_command(command)
            dialog = self.ready_dialog()
        send.assert_not_called()
        agent.assert_not_called()
        quick.assert_not_called()
        self.assertEqual(self.desktop.opened, [self.desktop.shortcut])
        self.assertFalse(dialog.isVisible())
        self.assertTrue(dialog._closed)
        self.assertFalse(dialog.pending_choice)

    def test_an_arbitrary_program_name_uses_the_same_automatic_voice_path(self):
        shortcut = Path(self.profile.name) / 'Meine Musikzentrale.lnk'
        shortcut.write_bytes(b'another local inert shortcut')
        self.desktop.apps = [{'name': 'Meine Musikzentrale', 'path': str(shortcut)}]
        command = VoiceTurnRouter().command_for('Hey Sytox, öffne Meine Musikzentrale')
        with patch.object(self.window, 'send') as send, \
             patch.object(self.window, 'start_worker') as agent, \
             patch.object(self.window, 'start_quick_reply') as quick:
            self.window.received_voice_command(command)
            dialog = self.ready_dialog()
        send.assert_not_called()
        agent.assert_not_called()
        quick.assert_not_called()
        self.assertEqual(self.desktop.opened, [shortcut])
        self.assertFalse(dialog.isVisible())

    def test_typed_open_while_coding_does_not_modify_or_stop_the_task(self):
        running = MagicMock()
        running.isRunning.return_value = True
        self.window.worker = running
        self.window.input.setPlainText('Öffne Spotify')
        with patch.object(self.window, 'ask_parallel') as parallel, \
             patch.object(self.window, 'queue_project_change') as amendment:
            self.window.send()
            dialog = self.ready_dialog()
        parallel.assert_not_called()
        amendment.assert_not_called()
        running.stop_event.set.assert_not_called()
        self.assertIs(self.window.worker, running)
        self.assertFalse(dialog.pending_choice)
        self.assertEqual(self.window.store.tasks(self.window.chat_id), [])
        self.assertEqual(self.desktop.opened, [self.desktop.shortcut])
        self.assertFalse(dialog.isVisible())

    def test_explicit_app_search_keeps_the_existing_readonly_panel(self):
        with patch.object(self.window, 'show_desktop_tools') as panel, \
             patch.object(self.window, 'show_app_request') as direct:
            self.window.received_voice_command('Suche Programm Firefox')
        panel.assert_called_once_with(query='Firefox', list_windows=False)
        direct.assert_not_called()

    def test_pending_multiple_choice_is_not_retargeted_by_a_second_request(self):
        other = Path(self.profile.name) / 'Other Spotify.lnk'
        other.write_bytes(b'other local inert shortcut')
        self.desktop.apps.append({'name': 'Spotify', 'path': str(other)})
        self.window.received_voice_command('Öffne Spotify')
        first = self.ready_dialog()
        self.assertTrue(first.pending_choice)
        self.assertTrue(first.isVisible())
        self.window.received_voice_command('Öffne Discord')
        self.assertIs(self.window.app_launch_dialog, first)
        self.assertEqual(first.query, 'Spotify')
        self.assertEqual(self.desktop.opened, [])

    def test_successful_request_can_be_followed_by_another_without_manual_close(self):
        self.window.received_voice_command('Öffne Spotify')
        first = self.ready_dialog()
        self.assertEqual(self.desktop.opened, [self.desktop.shortcut])
        self.window.received_voice_command('Öffne Spotify')
        second = self.ready_dialog()
        self.assertIsNot(second, first)
        self.assertEqual(self.desktop.opened, [self.desktop.shortcut, self.desktop.shortcut])
        self.assertFalse(second.pending_choice)
        self.assertFalse(second.isVisible())

    def test_close_waits_for_lookup_and_discards_its_result(self):
        self.desktop.release = threading.Event()
        self.window.received_voice_command('Öffne Spotify')
        self.wait_for(self.desktop.entered.is_set)
        dialog = self.window.app_launch_dialog
        self.window._is_exiting = True
        self.window.close()
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.window._pending_app_exit, 'close')
        self.desktop.release.set()
        self.wait_for(lambda: not self.window.isVisible())
        self.assertFalse(dialog.lookup_running)
        self.assertFalse(dialog.pending_choice)
        self.assertEqual(self.desktop.opened, [])


if __name__ == '__main__':
    unittest.main()
