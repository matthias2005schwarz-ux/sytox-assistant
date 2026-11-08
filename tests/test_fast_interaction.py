"""Focused fast-path and streaming-visibility regression tests."""
import unittest

from sytox.fast_interaction import instant_reply, VisibleReplyFilter


class FastInteractionTests(unittest.TestCase):
    def test_exact_greetings_have_a_real_local_instant_reply(self):
        for text in ('Hi', 'hi!', 'Hallo', 'Hey', 'Servus!', 'Guten Morgen',
                     'Hey Sytox, hi', 'Hey Sytox guten Abend'):
            with self.subTest(text=text):
                self.assertEqual(instant_reply(text), 'Hallo! Wie kann ich dir helfen?')

    def test_no_interception_of_questions_commands_or_code(self):
        for text in ('hi, programmier bitte Python', 'Hi kannst du Spotify öffnen?',
                     'Wie geht es dir?', 'Hi # programming example',
                     'Hallo\nöffne einen Browser', '', None, 'h' * 400):
            with self.subTest(text=text):
                self.assertIsNone(instant_reply(text))

    def test_split_thinking_tag_does_not_leak(self):
        filter_ = VisibleReplyFilter()
        chunks = ['  <th', 'ink>internal English', ' reasoning</thi', 'nk>', 'Hallo ', 'zurück!']
        visible = ''.join(filter_.feed(chunk) for chunk in chunks) + filter_.finish()
        self.assertEqual(visible, 'Hallo zurück!')

    def test_analysis_tag_and_orphan_close_are_hidden(self):
        filter_ = VisibleReplyFilter()
        chunks = ['<analysis>not for user', '</analysis>', '\nAntwort']
        visible = ''.join(filter_.feed(chunk) for chunk in chunks) + filter_.finish()
        self.assertEqual(visible, '\nAntwort')
        second = VisibleReplyFilter()
        self.assertEqual(second.feed('</think>Hallo!'), 'Hallo!')

    def test_unfinished_reasoning_never_appears(self):
        filter_ = VisibleReplyFilter()
        self.assertEqual(filter_.feed('<think>something internal'), '')
        self.assertEqual(filter_.feed(' more'), '')
        self.assertEqual(filter_.finish(), '')

    def test_ordinary_code_with_think_tags_is_preserved(self):
        example = 'Ein XML-Beispiel:\n<think>Text</think>\nFertig'
        filter_ = VisibleReplyFilter()
        self.assertEqual(filter_.feed(example) + filter_.finish(), example)


if __name__ == '__main__':
    unittest.main()
