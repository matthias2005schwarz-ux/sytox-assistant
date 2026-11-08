"""Small local syntax highlighter for read-only chat code, never an executor."""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


COLORS = {'keyword': '#F78DA7', 'string': '#A8D5B0',
          'comment': '#8D99A8', 'number': '#F0BF84'}
_PYTHON = set(('False None True and as assert async await break class continue def del '
               'elif else except finally for from global if import in is lambda nonlocal '
               'not or pass raise return try while with yield match case').split())
_COMMON = set(('if else for while do break continue return switch case default class '
               'struct enum public private protected static const void new this super '
               'try catch finally throw throws import package namespace using true false '
               'null int float double char bool boolean string long short unsigned signed '
               'abstract final interface extends implements override virtual').split())
_JS = set(('let var function async await of in export from typeof instanceof delete '
           'undefined yield debugger constructor get set type keyof declare readonly '
           'as any unknown never number symbol').split())
_GO_RUST = set(('fn mut let impl trait pub use mod crate self Self match loop move ref '
                'where dyn unsafe extern async await type typealias func go defer range '
                'select chan map make interface nil fallthrough var const').split())
_WORD = re.compile(r'[^\W\d]\w*', re.UNICODE)
_NUMBER = re.compile(r'(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|'
                     r'(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?)[uUlLfF]*')


class CodeHighlighter(QSyntaxHighlighter):
    """Color lexical tokens while leaving the original document unchanged.

    Supported languages share a deliberately small vocabulary, not a compiler
    parser. Unknown languages receive conservative string/number formatting.
    Block states: 1/2 Python triple strings, 3 C-style comment, 4 JS template.
    """

    def __init__(self, document, language=''):
        super().__init__(document)
        self._configure_language(language)
        self.formats = {}
        for kind, color in COLORS.items():
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            if kind == 'keyword':
                style.setFontWeight(QFont.DemiBold)
            if kind == 'comment':
                style.setFontItalic(True)
            self.formats[kind] = style

    def _configure_language(self, language):
        self.language = str(language or '').strip().casefold()
        self.python = self.language in ('python', 'py', 'python3', 'py3')
        self.javascript = self.language in ('javascript', 'js', 'jsx', 'typescript', 'ts', 'tsx')
        self.slash_comments = self.javascript or self.language in (
            'c', 'cpp', 'c++', 'cc', 'cxx', 'cs', 'c#', 'csharp', 'java', 'go', 'golang', 'rust', 'rs')
        self.keywords = (_PYTHON if self.python else
                         _COMMON | (_JS if self.javascript else _GO_RUST)
                         if self.slash_comments else
                         {'true', 'false', 'null'} if self.language == 'json' else set())
    def set_language(self, language):
        """Recolor an evolving streamed fence without replacing its document."""
        self._configure_language(language)
        self.rehighlight()

    @staticmethod
    def _closing(text, delimiter, start):
        """Find a closing quote that is not preceded by an odd escape count."""
        position = text.find(delimiter, start)
        while position >= 0:
            preceding = position - 1
            while preceding >= 0 and text[preceding] == '\\':
                preceding -= 1
            if (position - preceding - 1) % 2 == 0:
                return position
            position = text.find(delimiter, position + 1)
        return -1

    def _color(self, text, start, end, kind):
        # QTextDocument indexes UTF-16 code units; Python indexes Unicode points.
        offset = self._utf16_offsets[start]
        length = self._utf16_offsets[end] - offset
        self.setFormat(offset, length, self.formats[kind])

    def highlightBlock(self, text):
        self.setCurrentBlockState(0)
        self._utf16_offsets = [0]
        for character in text:
            self._utf16_offsets.append(self._utf16_offsets[-1] + (2 if ord(character) > 0xFFFF else 1))
        position = 0
        state = self.previousBlockState()
        if state in (1, 2, 3, 4):
            delimiter = {1: "'''", 2: '"""', 3: '*/', 4: '`'}[state]
            closing = text.find(delimiter) if state == 3 else self._closing(text, delimiter, 0)
            end = closing + len(delimiter) if closing >= 0 else len(text)
            self._color(text, 0, end, 'comment' if state == 3 else 'string')
            if closing < 0:
                self.setCurrentBlockState(state)
                return
            position = end
        while position < len(text):
            if ((self.python and text[position] == '#') or
                    (self.slash_comments and text.startswith('//', position))):
                self._color(text, position, len(text), 'comment')
                return
            if self.slash_comments and text.startswith('/*', position):
                closing = text.find('*/', position + 2)
                end = closing + 2 if closing >= 0 else len(text)
                self._color(text, position, end, 'comment')
                if closing < 0:
                    self.setCurrentBlockState(3)
                    return
                position = end
                continue
            quote = text[position]
            if quote in ('"', "'") or (self.javascript and quote == '`'):
                delimiter = quote * 3 if self.python and text.startswith(quote * 3, position) else quote
                closing = self._closing(text, delimiter, position + len(delimiter))
                end = closing + len(delimiter) if closing >= 0 else len(text)
                self._color(text, position, end, 'string')
                if closing < 0 and (len(delimiter) == 3 or quote == '`'):
                    self.setCurrentBlockState(1 if delimiter == "'''" else 2 if delimiter == '"""' else 4)
                    return
                position = end
                continue
            word = _WORD.match(text, position)
            if word:
                if word.group() in self.keywords:
                    self._color(text, position, word.end(), 'keyword')
                position = word.end()
                continue
            number = _NUMBER.match(text, position)
            if number:
                self._color(text, position, number.end(), 'number')
                position = number.end()
                continue
            position += 1
