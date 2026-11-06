"""Completed Markdown fences delimit exact clipboard text, never executable code."""
import unittest

from sytox.chat_content import fenced_code_blocks


class FencedCodeTests(unittest.TestCase):
    def test_unicode_tabs_and_line_endings_are_preserved(self):
        code = '\tprint("Grüße 👋")\r\n\r\n'
        self.assertEqual(fenced_code_blocks('Text\r\n```python\r\n' + code + '```'),
                         [{'language': 'python', 'code': code}])

    def test_incomplete_stream_and_inline_fences_are_ignored(self):
        for text in ('Inline ```python x```', '```python\nprint(1)',
                     '    ```python\nprint(1)\n    ```'):
            with self.subTest(text=text):
                self.assertEqual(fenced_code_blocks(text), [])

    def test_tilde_and_multiple_blocks(self):
        text = '~~~js\nlet x = 1;\n~~~\nNormal text\n```\nplain\n```\n'
        self.assertEqual(fenced_code_blocks(text), [
            {'language': 'js', 'code': 'let x = 1;\n'},
            {'language': '', 'code': 'plain\n'},
        ])

    def test_closing_fence_must_match_character_and_minimum_length(self):
        text = '````markdown\n```python\nprint(1)\n```\n~~~\n`````\n'
        self.assertEqual(fenced_code_blocks(text), [{
            'language': 'markdown', 'code': '```python\nprint(1)\n```\n~~~\n',
        }])

    def test_indented_fences_do_not_change_inner_indentation(self):
        self.assertEqual(fenced_code_blocks('  ```python\n    pass\n   ```  \n'),
                         [{'language': 'python', 'code': '    pass\n'}])

    def test_a_complete_block_survives_a_later_incomplete_block(self):
        self.assertEqual(fenced_code_blocks('```py\na\n```\n```js\nb'),
                         [{'language': 'py', 'code': 'a\n'}])

    def test_backtick_info_string_cannot_contain_backticks(self):
        self.assertEqual(fenced_code_blocks('```py`bad\na\n```'), [])


if __name__ == '__main__':
    unittest.main()
