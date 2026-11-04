"""Consent tests for the native Windows desk panel; never touch a real desktop."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
    from sytox.desktop_ui import DesktopControlDialog
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


class FakeDesktop:
    def __init__(self, path):
        self.shortcut = path
        self.opened = []
        self.focused = []

    def windows(self):
        return [{'id': 42, 'title': 'Notepad - Test', 'active': False,
                 'rect': [0, 0, 500, 400]}]

    def window(self, window_id):
        if window_id != 42:
            raise LookupError('Das Fenster wurde geschlossen.')
        return self.windows()[0]

    def activate(self, window_id):
        self.focused.append(window_id)

    def find_apps(self, query):
        if len(query) < 2:
            raise ValueError('Bitte einen Programmnamen eingeben.')
        return [{'name': 'Test Editor', 'path': str(self.shortcut)}]

    def open_app(self, path):
        self.opened.append(Path(path))


@unittest.skipUnless(QT_AVAILABLE, 'PySide6 is not installed')
class DesktopControlDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-desktop-test'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / 'test-app.lnk'
        path.write_bytes(b'test-shortcut-not-executed')
        self.desktop = FakeDesktop(path)
        self.dialog = DesktopControlDialog(desktop=self.desktop)

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def test_lists_windows_without_changing_focus(self):
        self.assertEqual(self.dialog.window_list.count(), 1)
        self.assertEqual(self.desktop.focused, [])
        self.assertEqual(self.desktop.opened, [])

    def test_voice_style_app_search_never_autostarts_program(self):
        self.dialog.app_query.setText('Editor')
        self.dialog.search_apps()
        self.assertEqual(self.dialog.app_list.count(), 1)
        self.assertEqual(self.desktop.opened, [])

    def test_declined_app_start_does_nothing(self):
        self.dialog.app_query.setText('Editor')
        self.dialog.search_apps()
        self.dialog.app_list.setCurrentRow(0)
        with patch('sytox.desktop_ui.QMessageBox.question',
                   return_value=QMessageBox.No):
            self.dialog.launch_app()
        self.assertEqual(self.desktop.opened, [])

    def test_approved_app_start_uses_only_discovered_shortcut(self):
        self.dialog.app_query.setText('Editor')
        self.dialog.search_apps()
        self.dialog.app_list.setCurrentRow(0)
        with patch('sytox.desktop_ui.QMessageBox.question',
                   return_value=QMessageBox.Yes):
            self.dialog.launch_app()
        self.assertEqual(self.desktop.opened, [self.desktop.shortcut])

    def test_window_activation_requires_approval(self):
        self.dialog.window_list.setCurrentRow(0)
        with patch('sytox.desktop_ui.QMessageBox.question',
                   return_value=QMessageBox.No):
            self.dialog.focus_window()
        self.assertEqual(self.desktop.focused, [])
        with patch('sytox.desktop_ui.QMessageBox.question',
                   return_value=QMessageBox.Yes):
            self.dialog.focus_window()
        self.assertEqual(self.desktop.focused, [42])


if __name__ == '__main__':
    unittest.main()
