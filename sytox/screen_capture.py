"""Capture the foreground desktop only for an explicit user question."""
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtWidgets import QApplication


def screenshot_png():
    screen = QApplication.primaryScreen()
    if screen is None:
        raise RuntimeError('Kein Monitor erkannt.')
    picture = screen.grabWindow(0)
    if picture.isNull():
        raise RuntimeError('Screenshot nicht verfügbar.')
    if picture.width() > 1800 or picture.height() > 1100:
        picture = picture.scaled(1800, 1100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise RuntimeError('Screenshot kann nicht gespeichert werden.')
    if not picture.save(buffer, 'PNG'):
        raise RuntimeError('PNG-Erstellung fehlgeschlagen.')
    data = bytes(buffer.data())
    buffer.close()
    return data
