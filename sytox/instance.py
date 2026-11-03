"""Single-instance Qt local IPC, plus Win32 mutex used by Inno Setup on upgrades.

The existing foreground process receives an open request from a desktop shortcut;
a background login launch never opens an existing foreground app.
"""
from __future__ import annotations
import hashlib
import sys

MUTEX_NAME = r'Local\SYTOX_Assistant_8B5756C1'


def socket_name(data_dir):
    """Keep unrelated Windows profiles and test APPDATA directories separate."""
    canonical = str(data_dir.expanduser().resolve()).casefold()
    return 'SYTOX_Assistant_' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]


def hold_windows_mutex():
    """Keep the handle alive for the whole application lifetime. Inno checks it."""
    if sys.platform != 'win32':
        return None
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


class InstanceBridge:
    """Local-only Qt IPC (Windows: named pipe, POSIX: domain socket)."""
    def __init__(self, data_dir):
        from PySide6.QtNetwork import QLocalServer
        self.name = socket_name(data_dir)
        self.server = QLocalServer()
        self.on_open = None
        self.server.newConnection.connect(self._accept)
        self.mutex_handle = None

    def _signal_existing(self, show):
        from PySide6.QtNetwork import QLocalSocket
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(450):
            return False
        try:
            socket.write(b'OPEN\n' if show else b'BACKGROUND\n')
            socket.waitForBytesWritten(450)
        finally:
            socket.disconnectFromServer()
        return True

    def listen_or_signal(self, show):
        """True: first process should run. False: request sent to live process."""
        from PySide6.QtNetwork import QLocalServer
        if self._signal_existing(show):
            return False
        if not self.server.listen(self.name):
            # Only remove a stale endpoint after a failed connection.
            if self._signal_existing(show):
                return False
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                if self._signal_existing(show):
                    return False
                raise RuntimeError('SYTOX-Instanzverbindung nicht verfügbar: ' + self.server.errorString())
        self.mutex_handle = hold_windows_mutex()
        return True

    def _accept(self):
        from PySide6.QtCore import QTimer
        while self.server.hasPendingConnections():
            peer = self.server.nextPendingConnection()
            # QLocalSocket may deliver its payload after newConnection; wait up to
            # 300 ms for the small, local message instead of opening unconditionally.
            if not peer.bytesAvailable():
                peer.waitForReadyRead(300)
            command = bytes(peer.readAll()).strip()
            peer.disconnectFromServer()
            peer.deleteLater()
            if command == b'OPEN' and self.on_open:
                QTimer.singleShot(0, self.on_open)

    def close(self):
        if self.server.isListening():
            self.server.close()
        # Windows closes the mutex handle when the process exits; doing so earlier
        # during shutdown could let the installer proceed while files are still open.
