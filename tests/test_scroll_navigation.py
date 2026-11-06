"""Reading older messages is stable while new assistant output arrives."""
import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from sytox.ui import MainWindow


class ScrollNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-scroll-tests'])

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
        for index in range(16):
            self.window.add_bubble('assistant',
                                   f'Antwort {index}\n' + 'Längerer Chattext zum Lesen. ' * 35)
        self.settle()
        self.bar = self.window.scroll.verticalScrollBar()
        self.assertGreater(self.bar.maximum(), 80)
        self.bar.setValue(0)
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

    def settle(self):
        self.app.processEvents()
        QTest.qWait(180)  # Deliver the bubble's deferred layout/scroll callbacks.
        self.app.processEvents()

    def test_assistant_output_keeps_reading_position_and_jump_returns_to_latest(self):
        self.window.add_bubble('assistant', 'Eine neue Antwort am Gesprächsende.')
        self.settle()
        self.assertEqual(self.bar.value(), 0)
        self.assertTrue(self.window.jump_to_latest.isVisible())
        self.window.jump_to_latest.click()
        self.app.processEvents()
        self.assertEqual(self.bar.value(), self.bar.maximum())
        self.assertFalse(self.window.jump_to_latest.isVisible())

    def test_new_user_message_follows_the_conversation_end(self):
        self.window.add_bubble('user', 'Meine neue Frage soll wieder unten sichtbar sein.')
        self.settle()
        self.assertEqual(self.bar.value(), self.bar.maximum())
        self.assertFalse(self.window.jump_to_latest.isVisible())


if __name__ == '__main__':
    unittest.main()
