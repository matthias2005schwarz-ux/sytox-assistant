"""Native, resource-isolated Markdown and exact, read-only code blocks."""
from __future__ import annotations

import re
import math

from PySide6.QtCore import Signal, Qt, QTimer, QUrl, QByteArray, QSize, QEvent
from PySide6.QtGui import QTextDocument, QTextOption, QImage, QFontDatabase, QTextCursor
from PySide6.QtWidgets import (
    QLabel, QWidget, QTextBrowser, QPlainTextEdit, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QSizePolicy, QApplication,
)


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


def message_segments(text: str) -> list[dict]:
    """Split prose and code while a fenced answer is still arriving.

    Raw Markdown remains on MessageContent. Code is never normalized for the
    clipboard; incomplete code is displayable but not offered as a full block.
    """
    segments, prose, code = [], [], []
    opening, language = None, ''
    for line in str(text or '').splitlines(keepends=True):
        candidate = line.rstrip('\r\n')
        if opening is None:
            match = _FENCE.fullmatch(candidate)
            if match and not (match[1][0] == '`' and '`' in match[2]):
                if ''.join(prose).strip():
                    segments.append({'kind': 'prose', 'text': ''.join(prose)})
                prose = []
                opening = match[1]
                language = match[2].strip().split()[0] if match[2].strip() else ''
                code = []
            else:
                prose.append(line)
        elif re.fullmatch(r' {0,3}' + re.escape(opening[0]) +
                          '{' + str(len(opening)) + r',}[ \t]*', candidate):
            segments.append({'kind': 'code', 'text': ''.join(code),
                             'language': language, 'complete': True})
            opening = None
        else:
            code.append(line)
    if opening is not None:
        segments.append({'kind': 'code', 'text': ''.join(code),
                         'language': language, 'complete': False})
    elif ''.join(prose).strip():
        segments.append({'kind': 'prose', 'text': ''.join(prose)})
    return segments


class SafeMarkdownDocument(QTextDocument):
    """Never load images, styles or other resources from model-provided URLs."""

    def loadResource(self, resource_type, name):
        # Do not delegate to QTextDocument: that could read local files too.
        return QImage() if resource_type == QTextDocument.ImageResource else QByteArray()


class MarkdownPane(QTextBrowser):
    """Native Markdown without HTML, automatic navigation or resource loading."""

    url_requested = Signal(QUrl)

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setObjectName('markdownProse')
        self.setReadOnly(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setStyleSheet('QTextBrowser { background: transparent; border: none; '
                          'padding: 0; color: #F3EDEF; font-size: 13px; }')
        self.viewport().setAutoFillBackground(False)
        document = SafeMarkdownDocument(self)
        document.setDocumentMargin(0)
        option = document.defaultTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        document.setDefaultTextOption(option)
        document.setDefaultStyleSheet(
            'a { color: #F2808B; } '
            'code { color: #FFC6AD; background-color: #282029; } '
            'td, th { border: 1px solid #49343F; padding: 5px; }')
        self.setDocument(document)
        self._text = None
        self._layout_width = -1
        self._height_timer = QTimer(self)
        self._height_timer.setSingleShot(True)
        self._height_timer.timeout.connect(self._refresh_height)
        document.contentsChanged.connect(lambda: self._height_timer.start(0))
        document.documentLayout().documentSizeChanged.connect(lambda *_: self._height_timer.start(0))
        self.anchorClicked.connect(self._request_link)
        self.set_markdown(text)

    def _request_link(self, url):
        if (url.isValid() and url.scheme().casefold() in ('http', 'https')
                and url.host() and not url.userInfo()):
            self.url_requested.emit(url)

    def set_markdown(self, text):
        if text == self._text:
            return
        self._text = text
        self.document().setMarkdown(text, QTextDocument.MarkdownDialectGitHub |
                                    QTextDocument.MarkdownNoHTML)
        self._height_timer.start(0)

    def _refresh_height(self):
        width = max(20, self.viewport().width())
        if width != self._layout_width:
            self._layout_width = width
            self.document().setTextWidth(width)
        height = max(20, math.ceil(self.document().size().height()) + 3)
        if height != self.height():
            self.setFixedHeight(height)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._height_timer.start(0)

    def minimumSizeHint(self):
        return QSize(0, 20)


class CodePane(QFrame):
    """A stable, selectable editor with a copy action adjacent to its code."""

    def __init__(self, segment, number, parent=None):
        super().__init__(parent)
        from .code_highlighter import CodeHighlighter
        self.setObjectName('codeBlock')
        self.setMinimumWidth(0)
        self._code, self._language = '', None
        self._display_code = ''
        self._complete = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(7)
        header = QHBoxLayout()
        self.language_label = QLabel()
        self.language_label.setObjectName('codeLanguage')
        self.language_label.setTextFormat(Qt.PlainText)
        self.language_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.language_label.setMinimumWidth(0)
        header.addWidget(self.language_label, 1)
        self.header = header
        layout.addLayout(header)
        self.copy_button = None
        self._copy_feedback_timer = QTimer(self)
        self._copy_feedback_timer.setSingleShot(True)
        self._copy_feedback_timer.setInterval(1400)
        self._copy_feedback_timer.timeout.connect(self._reset_copy_caption)
        self.editor = QPlainTextEdit(self)
        self.editor.setObjectName('codeEditor')
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setMinimumWidth(0)
        self.editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.editor.setFixedHeight(72)
        self.editor.setFrameShape(QFrame.NoFrame)
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setPixelSize(13)
        font.setFixedPitch(True)
        self.editor.setFont(font)
        # A global QWidget font rule otherwise overrides setFont, including on
        # the real MainWindow. Keep colors/borders/padding in the theme cascade.
        family = font.family().replace('\\', '\\\\').replace("'", "\\'")
        self.editor.setStyleSheet("QPlainTextEdit#codeEditor { font-family: '" +
                                  family + "'; font-size: 13px; }")
        self.editor.document().setDocumentMargin(0)
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.timeout.connect(self._refresh_editor_height)
        self.editor.installEventFilter(self)
        self.editor.viewport().installEventFilter(self)
        self.editor.document().blockCountChanged.connect(lambda *_: self._size_timer.start(0))
        self.editor.horizontalScrollBar().rangeChanged.connect(lambda *_: self._size_timer.start(0))
        self._highlighter = CodeHighlighter(self.editor.document(), segment['language'])
        layout.addWidget(self.editor)
        self.set_segment(segment, number)

    def set_segment(self, segment, number):
        language, code = segment['language'], segment['text']
        if language != self._language:
            self._language = language
            self._highlighter.set_language(language)
        caption = language[:60] or 'Code'
        if not segment['complete']:
            caption += ' · wird ergänzt …'
        self.language_label.setText(caption)
        if code != self._code:
            self._copy_feedback_timer.stop()
            self._reset_copy_caption()
            # The display normalizes Windows line endings; keep the raw value
            # separately so a CR/LF split across chunks never inserts two lines.
            display_code = code.replace('\r\n', '\n').replace('\r', '\n')
            if display_code != self._display_code:
                appended = bool(self._display_code) and display_code.startswith(self._display_code)
                if appended:
                    vertical, horizontal = self.editor.verticalScrollBar(), self.editor.horizontalScrollBar()
                    old_vertical, old_horizontal = vertical.value(), horizontal.value()
                    follow = vertical.maximum() - old_vertical <= 1
                    selection = self.editor.textCursor()
                    position, anchor = selection.position(), selection.anchor()
                    cursor = QTextCursor(self.editor.document())
                    cursor.movePosition(QTextCursor.End)
                    cursor.insertText(display_code[len(self._display_code):])
                    current = self.editor.textCursor()
                    if (current.position(), current.anchor()) != (position, anchor):
                        current.setPosition(anchor)
                        current.setPosition(position, QTextCursor.KeepAnchor)
                        self.editor.setTextCursor(current)
                    horizontal.setValue(old_horizontal)
                    vertical.setValue(vertical.maximum() if follow else old_vertical)
                else:
                    self._replace_display_code(display_code)
                self._display_code = display_code
            self._code = code
            self._size_timer.start(0)
        self._complete = segment['complete']
        if self._complete and self.copy_button is None:
            self.copy_button = QPushButton('Code kopieren')
            self.copy_button.setObjectName('copyCodeButton')
            self.copy_button.clicked.connect(self.copy_code)
            self.header.addWidget(self.copy_button)
        elif not self._complete and self.copy_button is not None:
            self._copy_feedback_timer.stop()
            self.header.removeWidget(self.copy_button)
            self.copy_button.hide()
            self.copy_button.setParent(None)
            self.copy_button.deleteLater()
            self.copy_button = None
        if self.copy_button is not None:
            self.copy_button.setAccessibleName(f'Codeblock {number} kopieren')
            self.copy_button.setToolTip('Nur den Code unverändert kopieren')

    def _replace_display_code(self, code):
        # A partial closing fence is briefly code, then disappears when it
        # completes. Replacing that fragment must not reset the reader's view.
        if not self._display_code:
            self.editor.setPlainText(code)
            return
        vertical, horizontal = self.editor.verticalScrollBar(), self.editor.horizontalScrollBar()
        old_vertical, old_horizontal = vertical.value(), horizontal.value()
        follow = vertical.maximum() - old_vertical <= 1
        previous = self.editor.textCursor()
        position, anchor = previous.position(), previous.anchor()
        self.editor.setPlainText(code)
        last = max(0, self.editor.document().characterCount() - 1)
        cursor = self.editor.textCursor()
        cursor.setPosition(min(anchor, last))
        cursor.setPosition(min(position, last), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        horizontal.setValue(old_horizontal)
        vertical.setValue(vertical.maximum() if follow else old_vertical)

    def _refresh_editor_height(self):
        self.editor.ensurePolished()
        font = self.editor.font()
        document = self.editor.document()
        if document.defaultFont() != font:
            document.setDefaultFont(font)
        tab_width = self.editor.fontMetrics().horizontalAdvance(' ') * 4
        if self.editor.tabStopDistance() != tab_width:
            self.editor.setTabStopDistance(tab_width)
        # Use the actual styled viewport inset, including the horizontal bar,
        # rather than assuming padding before the global stylesheet is applied.
        chrome = max(0, self.editor.height() - self.editor.viewport().height())
        content = 2 * document.documentMargin() + 4
        block = document.begin()
        while block.isValid():
            # Plain-text layouts round line metrics differently from QFontMetrics
            # and may use taller fallback glyphs. Stop once the capped view fills.
            content += document.documentLayout().blockBoundingRect(block).height()
            if content + chrome >= 440:
                break
            block = block.next()
        height = min(440, max(72, math.ceil(content + chrome)))
        if height != self.editor.height():
            self.editor.setFixedHeight(height)
            self.updateGeometry()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Resize, QEvent.FontChange, QEvent.ApplicationFontChange,
                            QEvent.StyleChange, QEvent.Polish, QEvent.PolishRequest,
                            QEvent.LayoutRequest, QEvent.Show):
            self._size_timer.start(0)
        return super().eventFilter(watched, event)

    def copy_code(self):
        if self._complete:
            QApplication.clipboard().setText(self._code)
            if self.copy_button is not None:
                self.copy_button.setText('Kopiert')
                self._copy_feedback_timer.start()

    def _reset_copy_caption(self):
        if self.copy_button is not None:
            self.copy_button.setText('Code kopieren')


class MessageContent(QWidget):
    """Keep raw text for storage/copying while incrementally rendering the view."""

    text_changed = Signal(str)
    url_requested = Signal(QUrl)

    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignTop)
        self._text = ''
        self._segments = []
        self.setText(text)

    def text(self):
        return self._text

    def setText(self, text):
        text = str(text or '')
        if text == self._text and self._segments:
            return
        self._text = text
        segments = message_segments(text)
        code_number = 0
        for index, segment in enumerate(segments):
            if segment['kind'] == 'code':
                code_number += 1
            if index < len(self._segments) and self._segments[index][0] != segment['kind']:
                self._remove_tail(index)
            if index == len(self._segments):
                if segment['kind'] == 'prose':
                    widget = MarkdownPane(segment['text'], self)
                    widget.url_requested.connect(self.url_requested.emit)
                else:
                    widget = CodePane(segment, code_number, self)
                self._segments.append((segment['kind'], widget))
                self._layout.addWidget(widget)
            else:
                widget = self._segments[index][1]
                if segment['kind'] == 'prose':
                    widget.set_markdown(segment['text'])
                else:
                    widget.set_segment(segment, code_number)
        self._remove_tail(len(segments))
        self.updateGeometry()
        self.text_changed.emit(text)

    def _remove_tail(self, index):
        while len(self._segments) > index:
            _kind, widget = self._segments.pop()
            self._layout.removeWidget(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()

    def minimumSizeHint(self):
        return QSize(0, 20)
