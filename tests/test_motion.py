"""Real native motion behavior, input preservation and animation lifetimes."""
import unittest

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QVariantAnimation
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QGraphicsDropShadowEffect
from shiboken6 import isValid

from sytox.motion import ActivityIndicator, MotionManager
from sytox.theme import STYLE


class NativeMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-motion-tests'])

    def setUp(self):
        self.window = QWidget()
        self.window.setStyleSheet(STYLE)
        self.layout = QVBoxLayout(self.window)
        self.button = QPushButton('Native Aktion')
        self.layout.addWidget(self.button)
        self.indicator = ActivityIndicator()
        self.layout.addWidget(self.indicator)
        self.motion = MotionManager(self.window)
        self.window.resize(250, 100)
        self.window.show()
        self.settle(20)
        self.driver = self.motion.attach_button(self.button)

    def tearDown(self):
        self.motion.stop_all()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def settle(self, duration=20):
        QTest.qWait(duration)
        self.app.processEvents()

    def test_button_hover_is_interpolated_without_moving_or_consuming_clicks(self):
        self.button.clearFocus()
        QCoreApplication.sendEvent(self.button, QEvent(QEvent.Leave))
        self.settle(170)
        before = self.button.geometry()
        QCoreApplication.sendEvent(self.button, QEvent(QEvent.Enter))
        self.settle(40)
        self.assertGreater(self.driver.overlay.level, 0)
        self.assertLess(self.driver.overlay.level, .78)
        self.assertEqual(self.button.geometry(), before)
        self.assertTrue(self.driver.overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
        clicked = []
        self.button.clicked.connect(lambda: clicked.append(True))
        QTest.mouseClick(self.button, Qt.LeftButton)
        self.assertEqual(clicked, [True])
        self.assertIsNone(self.button.graphicsEffect())

    def test_reduced_motion_settles_current_hover_and_future_changes_immediately(self):
        self.button.clearFocus()
        QCoreApplication.sendEvent(self.button, QEvent(QEvent.Enter))
        self.motion.set_reduced_motion(True)
        self.assertEqual(self.driver.animation.state(), QVariantAnimation.Stopped)
        self.assertAlmostEqual(self.driver.overlay.level, .78)
        QCoreApplication.sendEvent(self.button, QEvent(QEvent.Leave))
        self.assertEqual(self.driver.overlay.level, 0)
        self.assertEqual(self.driver.animation.state(), QVariantAnimation.Stopped)

    def test_disabled_or_hidden_buttons_leave_no_running_highlight(self):
        QCoreApplication.sendEvent(self.button, QEvent(QEvent.Enter))
        self.button.setEnabled(False)
        self.assertEqual(self.driver.overlay.level, 0)
        self.assertEqual(self.driver.animation.state(), QVariantAnimation.Stopped)
        self.button.setEnabled(True)
        QCoreApplication.sendEvent(self.button, QEvent(QEvent.Enter))
        self.button.hide()
        self.assertEqual(self.driver.overlay.level, 0)
        self.assertEqual(self.driver.animation.state(), QVariantAnimation.Stopped)

    def test_dynamic_buttons_attach_once_and_keep_keyboard_toggle_behavior(self):
        button = QPushButton('Später hinzugefügt')
        button.setCheckable(True)
        self.layout.addWidget(button)
        self.settle()
        self.assertTrue(hasattr(button, '_sytox_motion'))
        self.assertIs(self.motion.attach_button(button), button._sytox_motion)
        self.assertEqual(len(button.findChildren(QWidget, 'motionAccent')), 1)
        button.setFocus()
        QTest.keyClick(button, Qt.Key_Space)
        self.assertTrue(button.isChecked())

    def test_fade_finishes_with_no_graphics_effect_or_animation_left(self):
        widget = QWidget(self.window)
        widget.resize(30, 30)
        widget.show()
        animation = self.motion.fade_in(widget, 40)
        self.assertIsNotNone(widget.graphicsEffect())
        self.settle(90)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertIsNone(widget.graphicsEffect())
        self.assertEqual(self.motion._fades, {})
        self.assertFalse(isValid(animation))

    def test_fade_respects_shadow_and_repeated_calls_do_not_restart_or_leak(self):
        shadow = QGraphicsDropShadowEffect(self.button)
        self.button.setGraphicsEffect(shadow)
        self.assertIsNone(self.motion.fade_in(self.button))
        self.assertIs(self.button.graphicsEffect(), shadow)
        widget = QWidget(self.window)
        widget.show()
        animation = self.motion.fade_in(widget, 200)
        self.assertIs(self.motion.fade_in(widget, 200), animation)
        self.assertEqual(len(self.motion._fades), 1)
        self.motion.set_reduced_motion(True)
        self.assertIsNone(widget.graphicsEffect())
        self.assertEqual(self.motion._fades, {})

    def test_repeated_fades_disconnect_destroy_callbacks_and_deletion_is_safe(self):
        widget = QWidget(self.window)
        widget.show()
        # QObject.receivers is native signal metadata, not a mirrored counter.
        initial = widget.receivers('destroyed(QObject*)')
        for _ in range(5):
            self.motion.fade_in(widget, 1)
            self.settle(35)
        self.assertEqual(widget.receivers('destroyed(QObject*)'), initial)
        self.motion.fade_in(widget, 200)
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(self.motion._fades, {})
        self.motion.stop_all()

    def test_active_indicator_runs_only_while_visible_and_not_reduced(self):
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Stopped)
        self.indicator.set_active(True)
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Running)
        self.settle(40)
        self.assertGreater(self.indicator._phase, 0)
        self.indicator.hide()
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Stopped)
        self.indicator.show()
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Running)
        self.indicator.set_reduced_motion(True)
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Stopped)
        self.assertTrue(self.indicator._active)
        self.indicator.set_reduced_motion(False)
        self.indicator.set_active(False)
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Stopped)

    def test_minimized_parent_pauses_indicator_and_restore_resumes(self):
        self.indicator.set_active(True)
        self.window.showMinimized()
        self.settle()
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Stopped)
        self.window.showNormal()
        self.settle()
        self.assertEqual(self.indicator._animation.state(), QVariantAnimation.Running)


if __name__ == '__main__':
    unittest.main()
