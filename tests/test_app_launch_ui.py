"""Direct app confirmation against real Qt widgets and fake Windows adapters."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QTimer, QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from sytox.app_launch_ui import AppLaunchDialog


class FakeDesktop:
    def __init__(self, shortcut):
        self.apps = [{'name': 'Spotify', 'path': str(shortcut)}]
        self.app_windows = []
        self.opened = []
        self.focused = []
        self.release = None
        self.search_started = threading.Event()

    def find_app_windows(self, query):
        self.search_started.set()
        if self.release:
            self.release.wait(3)
        return list(self.app_windows)

    def find_apps(self, query):
        return list(self.apps)

    def open_app(self, path):
        self.opened.append(Path(path))

    def activate(self, window_id):
        self.focused.append(window_id)


class AppLaunchDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-app-launch-ui'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.shortcut = Path(self.temp.name) / 'Spotify.lnk'
        self.shortcut.write_bytes(b'never executed in this test')
        self.desktop = FakeDesktop(self.shortcut)
        self.dialogs = []

    def tearDown(self):
        if self.desktop.release:
            self.desktop.release.set()
        for dialog in self.dialogs:
            if not isValid(dialog):
                continue
            dialog.prepare_close()
            if dialog._lookup_worker is not None:
                dialog._lookup_worker.wait(3500)
            self.app.processEvents()
            dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.temp.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        self.app.processEvents()
        self.assertTrue(predicate(), 'Qt lookup did not reach the expected state')

    def dialog(self, *, wait=True):
        dialog = AppLaunchDialog('Spotify', desktop=self.desktop)
        self.dialogs.append(dialog)
        dialog.show()
        if wait:
            self.wait_for(lambda: dialog._lookup_worker is None)
        return dialog

    def test_unique_shortcut_needs_one_explicit_confirmation_and_cannot_launch_twice(self):
        dialog = self.dialog()
        self.assertFalse(dialog.candidate_list.isVisible())
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertIn(str(self.shortcut), dialog.target_detail.text())
        self.assertEqual(self.desktop.opened, [])
        self.assertTrue(dialog.pending_confirmation)
        dialog.confirm_button.click()
        dialog.confirm_selected()
        self.assertEqual(self.desktop.opened, [self.shortcut])
        self.assertIn('an Windows übergeben', dialog.status.text())
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertFalse(dialog.pending_confirmation)

    def test_cancel_and_default_enter_never_launch(self):
        dialog = self.dialog()
        self.assertTrue(dialog.cancel_button.isDefault())
        QTest.keyClick(dialog, Qt.Key_Return)
        self.app.processEvents()
        self.assertTrue(dialog._closed)
        self.assertEqual(self.desktop.opened, [])
        dialog.confirm_selected()
        self.assertEqual(self.desktop.opened, [])

    def test_multiple_shortcuts_require_selection_before_confirmation(self):
        other = Path(self.temp.name) / 'Other Spotify.lnk'
        other.write_bytes(b'another inert shortcut')
        self.desktop.apps.append({'name': 'Spotify', 'path': str(other)})
        dialog = self.dialog()
        self.assertEqual(dialog.candidate_list.count(), 2)
        self.assertEqual(dialog.candidate_list.currentRow(), -1)
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertTrue(dialog.pending_confirmation)
        dialog.confirm_selected()
        self.assertEqual(self.desktop.opened, [])
        dialog.candidate_list.setCurrentRow(1)
        dialog.confirm_button.click()
        self.assertEqual(self.desktop.opened, [other])

    def test_missing_program_has_clear_message_and_retry_without_actions(self):
        self.desktop.apps.clear()
        dialog = self.dialog()
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertTrue(dialog.retry_button.isVisible())
        self.assertFalse(dialog.pending_confirmation)
        self.assertIn('nicht', dialog.status.text().casefold())
        self.assertEqual(self.desktop.opened, [])
        self.desktop.apps.append({'name': 'Spotify', 'path': str(self.shortcut)})
        dialog.retry_button.click()
        self.wait_for(lambda: dialog._lookup_worker is None)
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual(self.desktop.opened, [])

    def test_existing_process_window_is_revalidated_then_focused_without_launch(self):
        self.desktop.app_windows = [{'id': 42, 'title': 'Track title', 'app_name': 'Spotify',
                                     'executable': 'C:/Spotify/Spotify.exe', 'active': False}]
        dialog = self.dialog()
        self.assertEqual(dialog.confirm_button.text(), 'Nach vorne holen')
        self.assertEqual(self.desktop.focused, [])
        dialog.confirm_button.click()
        self.assertEqual(self.desktop.focused, [42])
        self.assertEqual(self.desktop.opened, [])
        self.assertIn('Fenster aktiviert', dialog.status.text())

    def test_changed_process_identity_cannot_focus_or_fall_back_to_launch(self):
        self.desktop.app_windows = [{'id': 42, 'title': 'Spotify', 'app_name': 'Spotify',
                                     'executable': 'C:/Spotify/Spotify.exe'}]
        dialog = self.dialog()
        self.desktop.app_windows[0]['executable'] = 'C:/Other/Other.exe'
        dialog.confirm_button.click()
        self.assertEqual(self.desktop.focused, [])
        self.assertEqual(self.desktop.opened, [])
        self.assertIn('Nicht geöffnet', dialog.status.text())

    def test_changed_or_deleted_shortcut_needs_a_new_search_and_confirmation(self):
        dialog = self.dialog()
        self.shortcut.write_bytes(b'a changed shortcut is a different permission target')
        dialog.confirm_button.click()
        self.assertEqual(self.desktop.opened, [])
        self.assertIn('verändert oder entfernt', dialog.status.text())
        self.assertTrue(dialog.retry_button.isVisible())
        dialog.retry_button.click()
        self.wait_for(lambda: dialog._lookup_worker is None)
        self.shortcut.unlink()
        dialog.confirm_button.click()
        self.assertEqual(self.desktop.opened, [])

    def test_lookup_keeps_gui_responsive_and_cancel_discards_late_result(self):
        self.desktop.release = threading.Event()
        dialog = self.dialog(wait=False)
        self.wait_for(self.desktop.search_started.is_set)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        self.app.processEvents()
        self.assertEqual(heartbeat, [True])
        self.assertTrue(dialog.lookup_running)
        self.assertFalse(dialog.prepare_close())
        self.assertFalse(dialog.isVisible())
        self.assertTrue(isValid(dialog))
        self.desktop.release.set()
        self.wait_for(lambda: dialog._lookup_worker is None)
        self.assertTrue(dialog._closed)
        self.assertFalse(dialog.confirm_button.isEnabled())
        self.assertEqual(self.desktop.opened, [])
        self.assertEqual(self.desktop.focused, [])
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(dialog.findChildren(QThread), [])

    def test_retry_waits_for_the_finished_signal_cleanup_even_after_thread_has_stopped(self):
        dialog = self.dialog(wait=False)
        previous = dialog._lookup_worker
        self.assertIsNotNone(previous)
        self.assertTrue(previous.wait(3000))  # Keep GUI signals queued while the real thread ends.
        self.assertFalse(previous.isRunning())
        dialog.start_lookup()
        self.assertIs(dialog._lookup_worker, previous)
        self.wait_for(lambda: dialog._lookup_worker is None)
        self.assertTrue(dialog.confirm_button.isEnabled())
        self.assertEqual(self.desktop.opened, [])


if __name__ == '__main__':
    unittest.main()
