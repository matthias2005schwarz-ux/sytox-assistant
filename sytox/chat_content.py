"""Plain-text chat helpers; fenced code is copied without interpreting it."""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel


_FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)$')


def fenced_code_blocks(text: str) -> list[dict[str, str]]:
    """Return complete fenced blocks, preserving their code byte-for-character.

    Opening/closing fences occupy their own lines. A longer outer fence can
    contain shorter fences; unfinished streamed blocks are deliberately absent.
    """
    blocks = []
    opening = None
    language = ''
    content = []
    for line in str(text or '').splitlines(keepends=True):
        candidate = line.rstrip('\r\n')
        if opening is None:
            match = _FENCE.fullmatch(candidate)
            if not match:
                continue
            fence, info = match.groups()
            if fence[0] == '`' and '`' in info:
                continue
            opening = fence
            language = info.strip().split()[0] if info.strip() else ''
            content = []
        elif re.fullmatch(r' {0,3}' + re.escape(opening[0]) +
                          '{' + str(len(opening)) + r',}[ \t]*', candidate):
            blocks.append({'language': language, 'code': ''.join(content)})
            opening = None
        else:
            content.append(line)
    return blocks


class MessageLabel(QLabel):
    """Retain QLabel's plain-text API while notifying code-copy controls."""

    text_changed = Signal(str)

    def setText(self, text):
        super().setText(text)
        self.text_changed.emit(self.text())
