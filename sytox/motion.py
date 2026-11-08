"""Small native motion accents that leave layout and input handling untouched."""
from __future__ import annotations

import math
import weakref

from PySide6.QtCore import QObject, QEvent, Qt, QVariantAnimation, QPropertyAnimation, QEasingCurve, QSize, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QGraphicsOpacityEffect
from shiboken6 import isValid


def _alive(obj):
    return obj is not None and isValid(obj)


class _ButtonOverlay(QWidget):
    """Paint over a button without taking its focus, clicks or geometry."""

    def __init__(self, button):
        super().__init__(button)
        self.setObjectName('motionAccent')
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet('QWidget#motionAccent { background: transparent; border: none; }')
        self.level = 0.0
        self.setGeometry(button.rect())
        self.hide()

    def paintEvent(self, event):
        if self.level <= .001:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor('#F37683')
        color.setAlpha(round(20 * self.level))
        painter.setBrush(color)
        edge = QColor('#FA8791')
        edge.setAlpha(round(130 * self.level))
        painter.setPen(QPen(edge, 1.1))
        radius = 14 if self.parentWidget().objectName() == 'micButton' else 9
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), radius, radius)


class _ButtonMotion(QObject):
    def __init__(self, button, reduced_motion):
        super().__init__(button)
        self.button = button
        self.overlay = _ButtonOverlay(button)
        self.reduced_motion = bool(reduced_motion)
        self.hovered = False
        self.focused = button.hasFocus()
        self.pressed = False
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(145)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._set_level)
        button.installEventFilter(self)
        self._update(immediate=True)

    def _set_level(self, value):
        if not _alive(self.overlay):
            return
        self.overlay.level = float(value)
        if self.overlay.level > .001 and self.button.isVisible() and self.button.isEnabled():
            self.overlay.show()
            self.overlay.raise_()
        else:
            self.overlay.hide()
        self.overlay.update()

    def _target(self):
        if not self.button.isEnabled() or not self.button.isVisible():
            return 0.0
        if self.pressed:
            return 1.0
        if self.hovered:
            return .78
        return .48 if self.focused else 0.0

    def _update(self, *, immediate=False):
        target = self._target()
        self.animation.stop()
        if immediate or self.reduced_motion or abs(self.overlay.level - target) < .002:
            self._set_level(target)
            return
        self.animation.setStartValue(self.overlay.level)
        self.animation.setEndValue(target)
        self.animation.start()

    def set_reduced_motion(self, reduced):
        self.reduced_motion = bool(reduced)
        self._update(immediate=True)

    def stop(self):
        self.animation.stop()
        self.hovered = self.pressed = False
        self._set_level(0.0)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.Enter:
            self.hovered = True
        elif kind == QEvent.Leave:
            self.hovered = self.pressed = False
        elif kind == QEvent.FocusIn:
            self.focused = True
        elif kind == QEvent.FocusOut:
            self.focused = self.pressed = False
        elif kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self.pressed = True
        elif kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.pressed = False
        elif kind in (QEvent.KeyPress, QEvent.KeyRelease) and event.key() == Qt.Key_Space:
            self.pressed = kind == QEvent.KeyPress
        elif kind == QEvent.Resize:
            self.overlay.setGeometry(self.button.rect())
            return False
        elif kind in (QEvent.Hide, QEvent.Close):
            self.stop()
            return False
        elif kind == QEvent.EnabledChange:
            self.pressed = False
            self.hovered = self.button.underMouse() if self.button.isEnabled() else False
            self._update(immediate=True)
            return False
        elif kind == QEvent.Show:
            self._update(immediate=True)
            return False
        else:
            return False
        self._update()
        return False  # Native button activation and keyboard behavior stay intact.


class MotionManager(QObject):
    """Own brief transitions; never hold a permanent compositing effect."""

    def __init__(self, parent, reduced_motion=False):
        super().__init__(parent)
        self._root = weakref.ref(parent)
        self.reduced_motion = bool(reduced_motion)
        self._buttons = weakref.WeakSet()
        self._fades = {}
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)

    def attach_button(self, button):
        if not _alive(button) or not isinstance(button, QPushButton):
            return None
        current = getattr(button, '_sytox_motion', None)
        if _alive(current):
            return current
        driver = _ButtonMotion(button, self.reduced_motion)
        button._sytox_motion = driver
        self._buttons.add(driver)
        return driver

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Hide, QEvent.Close) and id(watched) in self._fades:
            self._finish_fade(id(watched))
        if kind in (QEvent.ChildPolished, QEvent.Show, QEvent.ParentChange):
            candidate = event.child() if kind == QEvent.ChildPolished else watched
            root = self._root()
            if (_alive(root) and _alive(candidate) and isinstance(candidate, QPushButton)
                    and root.isAncestorOf(candidate)):
                self.attach_button(candidate)
        return False

    def fade_in(self, widget, duration=180):
        """Fade once, respecting existing shadows and normal Qt ownership."""
        if not _alive(widget) or self.reduced_motion or not widget.isVisible():
            return None
        key = id(widget)
        if key in self._fades:
            return self._fades[key]['animation']
        if widget.graphicsEffect() is not None:
            return None
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(.08)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b'opacity', widget)
        animation.setDuration(max(1, min(int(duration), 400)))
        animation.setStartValue(.08)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._fades[key] = {'widget': weakref.ref(widget), 'effect': effect, 'animation': animation}
        manager = weakref.ref(self)

        def finish(*_):
            owner = manager()
            if _alive(owner):
                owner._finish_fade(key)

        animation.finished.connect(finish)
        self._fades[key]['destroy_connection'] = widget.destroyed.connect(finish)
        animation.start()
        return animation

    def _finish_fade(self, key):
        record = self._fades.pop(key, None)
        if record is None:
            return
        animation, effect = record['animation'], record['effect']
        if _alive(animation):
            animation.stop()
        widget = record['widget']()
        if _alive(widget) and record.get('destroy_connection') is not None:
            QObject.disconnect(record['destroy_connection'])
        if _alive(widget) and _alive(effect) and widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
        if _alive(animation):
            animation.deleteLater()

    def set_reduced_motion(self, reduced):
        self.reduced_motion = bool(reduced)
        for driver in list(self._buttons):
            if _alive(driver):
                driver.set_reduced_motion(reduced)
        if self.reduced_motion:
            for key in list(self._fades):
                self._finish_fade(key)

    def stop_all(self):
        for driver in list(self._buttons):
            if _alive(driver):
                driver.stop()
        for key in list(self._fades):
            self._finish_fade(key)


class ActivityIndicator(QWidget):
    """Three quiet dots while working; no animation when hidden or idle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('activityIndicator')
        self.setFixedSize(38, 16)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet('QWidget#activityIndicator { background: transparent; border: none; }')
        self.setAccessibleName('Aktivität')
        self._active = False
        self._reduced_motion = False
        self._phase = 0.0
        self._watched_window = None
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(math.tau)
        self._animation.setDuration(1600)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._set_phase)

    def sizeHint(self):
        return QSize(38, 16)

    def _set_phase(self, phase):
        self._phase = float(phase)
        self.update()

    def set_active(self, active):
        self._active = bool(active)
        self.setAccessibleDescription('SYTOX arbeitet' if active else 'Keine laufende Antwort')
        self._sync()

    def set_reduced_motion(self, reduced):
        self._reduced_motion = bool(reduced)
        self._sync()

    def _sync(self):
        moving = (self._active and not self._reduced_motion and self.isVisible()
                  and not self.window().isMinimized())
        if moving and self._animation.state() != QVariantAnimation.Running:
            self._animation.start()
        elif not moving:
            self._animation.stop()
            self._phase = 0.0
        self.update()

    def _watch_window(self):
        window = self.window()
        if window is self._watched_window:
            return
        if _alive(self._watched_window):
            self._watched_window.removeEventFilter(self)
        self._watched_window = window
        if window is not self:
            window.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.WindowStateChange, QEvent.Show, QEvent.Hide):
            self._sync()
        return False

    def showEvent(self, event):
        super().showEvent(event)
        self._watch_window()
        self._sync()

    def hideEvent(self, event):
        self._animation.stop()
        self._phase = 0.0
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        if not self._active:
            painter.setBrush(QColor('#77606A'))
            painter.drawEllipse(self.rect().center(), 2, 2)
            return
        for index in range(3):
            pulse = .6 if self._reduced_motion else (.5 + .5 * math.sin(self._phase - index * .8))
            color = QColor('#F0808C')
            color.setAlpha(round(100 + pulse * 140))
            painter.setBrush(color)
            radius = 2.0 + pulse * .35
            painter.drawEllipse(QRectF(9.0 + 10 * index - radius, 8.0 - radius, radius * 2, radius * 2))
