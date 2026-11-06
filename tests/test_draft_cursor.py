"""Chat draft selections preserve Qt's UTF-16 positions and selection direction."""
import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication
from sytox.ui import MainWindow


class DraftCursorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-draft-cursor-test'])

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

    def select_text(self, anchor, position):
        cursor = self.window.input.textCursor()
        cursor.setPosition(anchor)
        cursor.setPosition(position, QTextCursor.KeepAnchor)
        self.window.input.setTextCursor(cursor)
        return cursor.position(), cursor.anchor(), cursor.selectedText()

    def selection(self):
        cursor = self.window.input.textCursor()
        return cursor.position(), cursor.anchor(), cursor.selectedText()

    def test_each_chat_restores_its_own_utf16_cursor_and_reverse_selection(self):
        first = self.window.chat_id
        second = self.window.store.create_chat('Zweiter Entwurf')
        first_text = 'Grüße 👋\nzweite Zeile'
        self.window.input.setPlainText(first_text)
        first_selection = self.select_text(16, 6)
        self.assertLess(first_selection[0], first_selection[1])
        self.window.select_chat(second)
        second_text = 'Entwurf B 👀\nNoch ein Satz'
        self.window.input.setPlainText(second_text)
        second_selection = self.select_text(2, 13)
        self.window.select_chat(first)
        self.assertEqual(self.window.input.toPlainText(), first_text)
        self.assertEqual(self.selection(), first_selection)
        self.window.select_chat(second)
        self.assertEqual(self.window.input.toPlainText(), second_text)
        self.assertEqual(self.selection(), second_selection)
        self.assertEqual(self.window.store.messages(first), [])
        self.assertEqual(self.window.store.messages(second), [])

    def test_selecting_current_chat_keeps_unsubmitted_text_and_selection(self):
        text = '\nHallo 👋\nbleibt hier'
        self.window.input.setPlainText(text)
        selected = self.select_text(15, 7)
        self.window.select_chat(self.window.chat_id)
        self.assertEqual(self.window.input.toPlainText(), text)
        self.assertEqual(self.selection(), selected)


if __name__ == '__main__':
    unittest.main()
