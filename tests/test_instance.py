"""Single-instance behavior without a running Qt/Windows session."""
import tempfile
import types
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.instance import InstanceBridge, socket_name


class FakeSocket:
    def __init__(self, connected=True):
        self.connected = connected
        self.sent = []
        self.closed = False

    def connectToServer(self, name):
        self.name = name

    def waitForConnected(self, delay):
        return self.connected

    def write(self, data):
        self.sent.append(data)

    def waitForBytesWritten(self, delay):
        return True

    def disconnectFromServer(self):
        self.closed = True


class InstanceTests(unittest.TestCase):
    def test_names_different_per_data_directory(self):
        a = socket_name(Path('/tmp/sytox-one'))
        self.assertEqual(a, socket_name(Path('/tmp/sytox-one')))
        self.assertNotEqual(a, socket_name(Path('/tmp/sytox-two')))
        self.assertTrue(a.startswith('SYTOX_Assistant_'))

    def test_signal_existing_wakes_window_only_when_requested(self):
        fake = FakeSocket()
        module = types.ModuleType('PySide6.QtNetwork')
        module.QLocalSocket = lambda: fake
        bridge = object.__new__(InstanceBridge)
        bridge.name = 'test-instance'
        with patch.dict(sys.modules, {'PySide6': types.ModuleType('PySide6'), 'PySide6.QtNetwork': module}):
            self.assertTrue(bridge._signal_existing(True))
        self.assertEqual(fake.sent, [b'OPEN\n'])
        self.assertTrue(fake.closed)

    def test_background_launch_does_not_open_foreground_window(self):
        fake = FakeSocket()
        module = types.ModuleType('PySide6.QtNetwork')
        module.QLocalSocket = lambda: fake
        bridge = object.__new__(InstanceBridge)
        bridge.name = 'test-instance'
        with patch.dict(sys.modules, {'PySide6': types.ModuleType('PySide6'), 'PySide6.QtNetwork': module}):
            self.assertTrue(bridge._signal_existing(False))
        self.assertEqual(fake.sent, [b'BACKGROUND\n'])

    def test_unavailable_socket_does_not_pretend_to_signal(self):
        fake = FakeSocket(connected=False)
        module = types.ModuleType('PySide6.QtNetwork')
        module.QLocalSocket = lambda: fake
        bridge = object.__new__(InstanceBridge)
        bridge.name = 'test-instance'
        with patch.dict(sys.modules, {'PySide6': types.ModuleType('PySide6'), 'PySide6.QtNetwork': module}):
            self.assertFalse(bridge._signal_existing(True))
        self.assertEqual(fake.sent, [])


if __name__ == '__main__':
    unittest.main()
