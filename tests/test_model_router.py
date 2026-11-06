"""Selection and explicit visual-intent rules (no network/UI required)."""
import unittest
from sytox.model_router import select_chat_model, wants_screen


class AutomaticModelTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'model': 'fallback', 'fast_model':'qwen3:4b',
                         'project_model':'qwen3-coder:30b', 'model_mode':'auto'}

    def test_quick_conversation_uses_fast_model(self):
        self.assertEqual(select_chat_model('Wie geht es dir?', self.settings),
                         ('qwen3:4b', 'fast'))

    def test_project_tasks_use_large_model(self):
        self.assertEqual(select_chat_model('Programmiere ein Python Plugin', self.settings),
                         ('qwen3-coder:30b', 'project'))
        self.assertEqual(select_chat_model('Mach weiter', self.settings, 'timed'),
                         ('qwen3-coder:30b', 'project'))

    def test_manual_selection_overrides_classification(self):
        self.assertEqual(select_chat_model('Schreibe Code', dict(self.settings, model_mode='fast')),
                         ('qwen3:4b', 'fast'))
        self.assertEqual(select_chat_model('Hi', dict(self.settings, model_mode='project')),
                         ('qwen3-coder:30b', 'project'))

    def test_legacy_settings_keep_existing_model(self):
        self.assertEqual(select_chat_model('Hallo', {'model':'old:7b'}),
                         ('old:7b', 'fast'))

    def test_windows_program_error_keeps_fast_model(self):
        self.assertEqual(select_chat_model(
            'Bitte behebe den Fehler VCRUNTIME140.dll fehlt beim x64-Programm.',
            self.settings), ('qwen3:4b', 'fast'))
        self.assertEqual(select_chat_model(
            'Windows-Programm startet nicht, Fehlercode 0xc000007b',
            self.settings), ('qwen3:4b', 'fast'))

    def test_explicit_request_to_build_program_uses_project_model(self):
        self.assertEqual(select_chat_model(
            'Erstelle mir ein Programm für Windows', self.settings),
            ('qwen3-coder:30b', 'project'))

    def test_screen_request_works_with_fast_and_project_models(self):
        for question in (
            'Schau bitte auf meinen Bildschirm',
            'Was siehst du auf meinem Screen?',
            'Lies meinen Bildschirm',
            'Analysiere meinen Desktop',
            'Was steht auf meinem Monitor?',
        ):
            with self.subTest(question=question):
                self.assertTrue(wants_screen(question))
                self.assertEqual(select_chat_model(question, self.settings)[1], 'fast')
                self.assertEqual(select_chat_model(
                    question, dict(self.settings, model_mode='project'))[1], 'project')

    def test_no_background_capture_for_discussion_or_negative_request(self):
        for question in (
            'Wie mache ich einen Screenshot?',
            'Wenn ich sage schau auf meinen Bildschirm, was passiert?',
            'Schau nicht auf meinen Bildschirm',
            'Der Screenshot ist leer.',
            'Beschreibe das Wort Bildschirm',
            'Wie kann ich einen Screenshot machen?',
        ):
            with self.subTest(question=question):
                self.assertFalse(wants_screen(question))


if __name__ == '__main__':
    unittest.main()
