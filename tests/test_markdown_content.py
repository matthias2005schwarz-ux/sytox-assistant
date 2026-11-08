"""Native rendering, exact code copying and inert model-provided resources."""
import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QUrl
from PySide6.QtGui import QFont, QFontInfo, QImage, QTextDocument, QTextTable, QTextCursor
from PySide6.QtWidgets import QApplication, QPushButton

from sytox.chat_content import (
    MessageContent, MarkdownPane, CodePane, SafeMarkdownDocument, message_segments,
)


class MarkdownContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-markdown-tests'])

    def setUp(self):
        self.content = MessageContent()
        self.content.resize(460, 300)
        self.content.show()

    def tearDown(self):
        self.content.close()
        self.content.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def settle(self):
        deadline = time.monotonic() + .05
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.001)

    def test_markdown_formats_headings_bold_lists_and_tables(self):
        self.content.setText('# Übersicht\n\n**Kräftig** und *schräg*.\n\n'
                             '- eins\n- zwei\n\n| Name | Wert |\n| --- | --- |\n| A | 7 |')
        self.settle()
        pane = self.content.findChild(MarkdownPane)
        doc = pane.document()
        self.assertIn('Übersicht', doc.toPlainText())
        self.assertNotIn('**', doc.toPlainText())
        self.assertGreaterEqual(doc.find('Kräftig').charFormat().fontWeight(), QFont.Bold)
        self.assertTrue(doc.find('schräg').charFormat().fontItalic())
        self.assertIsNotNone(doc.find('eins').block().textList())
        self.assertTrue(any(isinstance(frame, QTextTable) for frame in doc.rootFrame().childFrames()))
        self.assertGreater(pane.height(), 100)

    def test_stream_updates_code_in_place_and_copies_only_when_complete(self):
        source = 'Antwort\r\n```python\r\n\tprint("Grüße 👋")'
        self.content.setText(source)
        card = self.content.findChild(CodePane)
        editor = card.editor
        self.assertIn('wird ergänzt', card.language_label.text())
        self.assertEqual(self.content.findChildren(QPushButton, 'copyCodeButton'), [])
        self.content.setText(source + '\r\n\r\n')
        self.assertIs(self.content.findChild(CodePane).editor, editor)
        complete = source + '\r\n\r\n```\r\nFertig.'
        self.content.setText(complete)
        self.settle()
        self.assertIs(self.content.findChild(CodePane).editor, editor)
        self.assertTrue(editor.isReadOnly())
        self.assertIn('print', editor.toPlainText())
        button = self.content.findChild(QPushButton, 'copyCodeButton')
        self.assertEqual(button.accessibleName(), 'Codeblock 1 kopieren')
        self.assertNotIn('wird ergänzt', card.language_label.text())
        button.click()
        self.assertEqual(button.text(), 'Kopiert')
        self.assertEqual(self.app.clipboard().text(), '\tprint("Grüße 👋")\r\n\r\n')
        self.assertEqual(self.content.text(), complete)
        self.assertTrue(editor.document().firstBlock().layout().formats())
        card._copy_feedback_timer.timeout.emit()
        self.assertEqual(button.text(), 'Code kopieren')

    def test_local_and_remote_images_never_load_and_html_is_inert(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private.png'
            image = QImage(2, 2, QImage.Format_ARGB32)
            image.fill(0xff00ff00)
            image.save(str(path))
            local = QUrl.fromLocalFile(str(path))
            self.content.setText(f'![local]({local.toString()})\n\n'
                                 '![remote](https://example.invalid/track.png)\n\n'
                                 '<script>alert("x")</script>')
            self.settle()
            doc = self.content.findChild(MarkdownPane).document()
            self.assertIsInstance(doc, SafeMarkdownDocument)
            for url in (local, QUrl('https://example.invalid/track.png')):
                loaded = doc.resource(QTextDocument.ImageResource, url)
                self.assertIsInstance(loaded, QImage)
                self.assertTrue(loaded.isNull())
            self.assertNotIn('<script>', doc.toHtml())

    def test_only_explicit_http_links_emit_requests(self):
        self.content.setText('[Quelle](https://example.org/source)')
        pane = self.content.findChild(MarkdownPane)
        requested = []
        self.content.url_requested.connect(lambda url: requested.append(url.toString()))
        self.assertFalse(pane.openLinks())
        self.assertFalse(pane.openExternalLinks())
        self.assertEqual(requested, [])
        for url in ('file:///tmp/private', 'javascript:alert(1)', 'data:text/html,unsafe',
                    'https://user:password@example.org/'):
            pane.anchorClicked.emit(QUrl(url))
        self.assertEqual(requested, [])
        pane.anchorClicked.emit(QUrl('https://example.org/source'))
        self.assertEqual(requested, ['https://example.org/source'])

    def test_narrow_prose_reflows_and_long_code_stays_bounded(self):
        self.content.setText(('Lesbarer Text mit **Formatierung**. ' * 35) +
                             '\n\n```python\n' + ('print("' + 'x' * 500 + '")\n') * 80 + '```')
        self.content.resize(460, 500)
        self.settle()
        pane = self.content.findChild(MarkdownPane)
        wide = pane.height()
        self.content.resize(230, 500)
        self.settle()
        self.assertGreater(pane.height(), wide)
        card = self.content.findChild(CodePane)
        self.assertLessEqual(card.editor.height(), 440)
        self.assertLessEqual(card.width(), self.content.width())
        self.assertEqual(pane.verticalScrollBar().maximum(), 0)
        self.assertGreater(card.editor.horizontalScrollBar().maximum(), 0)

    def test_global_app_theme_cannot_override_code_font_or_clip_short_blocks(self):
        from sytox.theme import STYLE
        self.content.setStyleSheet(STYLE)
        self.content.setText('```python\n' + '\n'.join(f'print({n})' for n in range(11)) + '\n```')
        self.settle()
        editor = self.content.findChild(CodePane).editor
        resolved = QFontInfo(editor.font())
        self.assertTrue(resolved.fixedPitch(),
                        f'editor QFont={editor.font().family()}; resolved={resolved.family()}; '
                        f'widget QSS={editor.styleSheet()[:180]}')
        self.assertTrue(QFontInfo(editor.document().defaultFont()).fixedPitch())
        self.assertEqual(editor.fontMetrics().horizontalAdvance('M'),
                         editor.fontMetrics().horizontalAdvance('i'))
        self.assertEqual(editor.verticalScrollBar().maximum(), 0)
        # Re-polishing after a theme/font change must recompute viewport chrome.
        self.content.setStyleSheet(STYLE + '\nQPlainTextEdit#codeEditor { padding: 17px 12px; }')
        self.settle()
        self.assertEqual(editor.verticalScrollBar().maximum(), 0)
        self.assertTrue(QFontInfo(editor.font()).fixedPitch())

    def test_long_streamed_code_follows_the_end_when_reader_is_at_bottom(self):
        text = '```python\n' + ''.join(f'print({n})\n' for n in range(90))
        self.content.setText(text)
        self.settle()
        editor = self.content.findChild(CodePane).editor
        bar = editor.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        # A saved long block opens at the beginning, then the reader follows.
        self.assertEqual(bar.value(), 0)
        bar.setValue(bar.maximum())
        self.content.setText(text + 'print("new token")\n')
        self.settle()
        self.assertEqual(bar.value(), bar.maximum())

    def test_long_code_append_preserves_reading_position_and_selection(self):
        text = '```python\n' + ''.join(f'print({n})\n' for n in range(90))
        self.content.setText(text)
        self.settle()
        editor = self.content.findChild(CodePane).editor
        selection = editor.textCursor()
        selection.setPosition(9)
        selection.setPosition(2, QTextCursor.KeepAnchor)
        editor.setTextCursor(selection)
        editor.verticalScrollBar().setValue(0)
        self.content.setText(text + 'print("new token")\n')
        self.settle()
        self.assertEqual(editor.verticalScrollBar().value(), 0)
        self.assertEqual(editor.textCursor().position(), 2)
        self.assertEqual(editor.textCursor().anchor(), 9)
        self.assertEqual(editor.textCursor().selectedText(), selection.selectedText())

    def test_split_windows_line_ending_is_displayed_once_and_copied_exactly(self):
        self.content.setText('```python\r\nx = 1\r')
        editor = self.content.findChild(CodePane).editor
        self.content.setText('```python\r\nx = 1\r\n')
        self.content.setText('```python\r\nx = 1\r\n```')
        self.settle()
        self.assertEqual(editor.toPlainText(), 'x = 1\n')
        self.content.findChild(QPushButton, 'copyCodeButton').click()
        self.assertEqual(self.app.clipboard().text(), 'x = 1\r\n')

    def test_split_closing_fence_preserves_bottom_follow_and_reader_selection(self):
        source = '```python\n' + ''.join(f'print({n})\n' for n in range(90))
        for following in (True, False):
            with self.subTest(following=following):
                self.content.setText(source)
                self.settle()
                editor = self.content.findChild(CodePane).editor
                bar = editor.verticalScrollBar()
                if not following:
                    cursor = editor.textCursor()
                    cursor.setPosition(9)
                    cursor.setPosition(2, QTextCursor.KeepAnchor)
                    editor.setTextCursor(cursor)
                bar.setValue(bar.maximum() if following else 0)
                self.content.setText(source + '``')
                self.settle()
                self.content.setText(source + '```')
                self.settle()
                self.assertEqual(bar.value(), bar.maximum() if following else 0)
                self.assertEqual(editor.toPlainText(), source.split('\n', 1)[1])
                if not following:
                    self.assertEqual((editor.textCursor().position(), editor.textCursor().anchor()), (2, 9))

    def test_tilde_and_long_fences_preserve_segments_and_raw_text(self):
        text = 'Intro\n````markdown\n```py\na\n```\n````\nTail\n~~~js\nlet a=1;'
        segments = message_segments(text)
        self.assertEqual([part['kind'] for part in segments], ['prose', 'code', 'prose', 'code'])
        self.assertEqual(segments[1]['text'], '```py\na\n```\n')
        self.assertTrue(segments[1]['complete'])
        self.assertFalse(segments[-1]['complete'])
        self.content.setText(text)
        self.assertEqual(self.content.text(), text)
        self.assertEqual(len(self.content.findChildren(QPushButton, 'copyCodeButton')), 1)


if __name__ == '__main__':
    unittest.main()
