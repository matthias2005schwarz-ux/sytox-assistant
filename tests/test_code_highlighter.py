"""Native text layouts prove highlighting without changing executable source."""
import unittest

from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication
from sytox.code_highlighter import CodeHighlighter, COLORS


class CodeHighlighterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-highlighter-tests'])

    def render(self, text, language):
        self.document = QTextDocument()
        self.document.setPlainText(text)
        self.highlighter = CodeHighlighter(self.document, language)
        self.highlighter.rehighlight()
        self.assertEqual(self.document.toPlainText(), text)
        return self.document.firstBlock()

    def color_at(self, block, token, occurrence=0):
        text = block.text()
        position = -1
        for _ in range(occurrence + 1):
            position = text.index(token, position + 1)
        offset = len(text[:position].encode('utf-16-le')) // 2
        for item in block.layout().formats():
            if item.start <= offset < item.start + item.length:
                return item.format.foreground().color().name()
        return None

    def test_python_tokens_and_comments_do_not_overlap_strings(self):
        block = self.render('if value == 42: print("# return") # return 9', 'python')
        for token, kind in (('if', 'keyword'), ('42', 'number'), ('# return', 'string')):
            self.assertEqual(self.color_at(block, token), COLORS[kind].lower())
        self.assertEqual(self.color_at(block, 'return', 1), COLORS['comment'].lower())

    def test_python_triple_string_state_closes_before_later_code(self):
        block = self.render('text = """first\n# return 7\nlast"""; return 3', 'py')
        self.assertEqual(block.userState(), 2)
        middle = block.next()
        self.assertEqual(middle.userState(), 2)
        self.assertEqual(self.color_at(middle, 'return'), COLORS['string'].lower())
        last = middle.next()
        self.assertEqual(last.userState(), 0)
        self.assertEqual(self.color_at(last, 'return'), COLORS['keyword'].lower())
        self.assertEqual(self.color_at(last, '3'), COLORS['number'].lower())

    def test_c_comments_keep_keywords_plain_until_closing(self):
        first = self.render('/* return 1\nclass hidden */ return 2;', 'cpp')
        self.assertEqual(first.userState(), 3)
        second = first.next()
        self.assertEqual(second.userState(), 0)
        self.assertEqual(self.color_at(second, 'class'), COLORS['comment'].lower())
        self.assertEqual(self.color_at(second, 'return'), COLORS['keyword'].lower())

    def test_javascript_urls_templates_and_comments(self):
        first = self.render('const url = "https://example.org"; // if 7\nconst text = `hello\nworld`; let n = 0xFF;', 'ts')
        self.assertEqual(self.color_at(first, '//example'), COLORS['string'].lower())
        self.assertEqual(self.color_at(first, 'if'), COLORS['comment'].lower())
        self.assertEqual(first.next().userState(), 4)
        last = first.next().next()
        self.assertEqual(last.userState(), 0)
        self.assertEqual(self.color_at(last, 'let'), COLORS['keyword'].lower())
        self.assertEqual(self.color_at(last, '0xFF'), COLORS['number'].lower())

    def test_supported_language_aliases_and_unknown_fallback(self):
        for language in ('c++', 'c#', 'java', 'go', 'rust'):
            with self.subTest(language=language):
                block = self.render('if (n == 1) return "ok";', language)
                self.assertEqual(self.color_at(block, 'return'), COLORS['keyword'].lower())
        unknown = self.render('return 42 "safe" # not guessed', 'unfamiliar-language')
        self.assertIsNone(self.color_at(unknown, 'return'))
        self.assertEqual(self.color_at(unknown, '42'), COLORS['number'].lower())

    def test_unicode_offsets_after_emoji_still_target_the_correct_tokens(self):
        block = self.render('label = "Grüße 👋"; return 7', 'python')
        self.assertEqual(self.color_at(block, 'return'), COLORS['keyword'].lower())
        self.assertEqual(self.color_at(block, '7'), COLORS['number'].lower())

    def test_streamed_language_change_recolors_the_existing_document(self):
        first = self.render('# not a JS comment\nconst n = 1;', 'python')
        self.assertEqual(self.color_at(first, '#'), COLORS['comment'].lower())
        self.highlighter.set_language('javascript')
        self.assertIsNone(self.color_at(first, '#'))
        self.assertEqual(self.color_at(first.next(), 'const'), COLORS['keyword'].lower())


if __name__ == '__main__':
    unittest.main()
