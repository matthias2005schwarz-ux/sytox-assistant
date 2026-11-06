"""Selection and explicit visual-intent rules (no network/UI required)."""
import unittest
from sytox.model_router import select_chat_model, wants_screen, requires_agent


class AutomaticModelTests(unittest.TestCase):
    def setUp(self):
        self.settings = {'model': 'fallback', 'fast_model':'qwen3:4b',
                         'project_model':'qwen3-coder:30b', 'model_mode':'auto'}

    def test_quick_conversation_uses_fast_model(self):
        self.assertEqual(select_chat_model('Wie geht es dir?', self.settings),
                         ('qwen3:4b', 'fast'))

    def test_greetings_and_technical_explanations_do_not_start_project(self):
        for question in (
            'Hallo', 'Was ist Python?', 'Kannst du programmieren?',
            'Erkläre mir diesen Code', 'Wie programmiere ich eine Schleife?',
            'Was bedeutet API?', 'Ich lerne gerade Rust.',
            'Warum startet mein Java-Programm nicht?',
            'Programmiere nicht, sag nur Hallo.',
            'Erkläre mir das Design einer App', 'Was ist ein Button?',
            'Wie füge ich einen Button hinzu?',
            'Füge bitte keinen Button hinzu',
        ):
            with self.subTest(question=question):
                self.assertEqual(select_chat_model(question, self.settings),
                                 ('qwen3:4b', 'fast'))
                self.assertFalse(requires_agent(question))

    def test_development_actions_still_select_project(self):
        for question in (
            'Schreibe mir eine Python-Funktion',
            'Behebe den Fehler in meinem Code',
            'Implementiere das bitte', 'Analysiere dieses Repository',
            'Erweitere mein Plugin um eine Suche', 'Refactor my code',
            'Fix this function', 'Mach mit meinem letzten Projekt weiter',
            'Bearbeite main.py',
            'Verbessere meinen Python-Code', 'Baue mir eine Website',
            'Füge meinem Projekt eine Suchfunktion hinzu',
        ):
            with self.subTest(question=question):
                self.assertEqual(select_chat_model(question, self.settings),
                                 ('qwen3-coder:30b', 'project'))
                self.assertTrue(requires_agent(question))

    def test_explicit_interface_changes_remain_project_work(self):
        for question in (
            'Füge einen Button hinzu', 'Ändere das Design meiner App',
            'Entferne die Animation', 'Baue ein Menü ein',
            'Erweitere das Interface', 'Verbessere das Layout',
            'Kannst du die Oberfläche optimieren?',
        ):
            with self.subTest(question=question):
                self.assertTrue(requires_agent(question))
                self.assertEqual(select_chat_model(question, self.settings),
                                 ('qwen3-coder:30b', 'project'))
                # Explicitly choosing the small model must retain tool access.
                self.assertEqual(select_chat_model(
                    question, dict(self.settings, model_mode='fast')),
                    ('qwen3:4b', 'fast'))

    def test_explicit_tools_keep_agent_independent_of_small_model(self):
        for question in (
            'Öffne Notepad', 'Lies die Datei README.md',
            'Liste Dateien im Projektordner auf',
            'Öffne die Webseite https://example.org',
            'Klicke auf den Button', 'Sende eine E-Mail an Max',
            'Merke dir, ich mag dunkelrot',
            'Erstelle README.md',
        ):
            with self.subTest(question=question):
                self.assertTrue(requires_agent(question))
                self.assertEqual(select_chat_model(
                    question, dict(self.settings, model_mode='fast'))[0], 'qwen3:4b')
        self.assertTrue(requires_agent('Schreibe Code'))
        self.assertTrue(requires_agent('Mach weiter', 'timed'))
        self.assertFalse(requires_agent('Wie öffne ich eine Datei?'))
        self.assertFalse(requires_agent('Schau auf meinen Bildschirm'))

    def test_empty_settings_use_dedicated_route_defaults(self):
        self.assertEqual(select_chat_model('Hallo', {}), ('qwen3:4b', 'fast'))
        self.assertEqual(select_chat_model('Schreibe Code', {}),
                         ('qwen3-coder:30b', 'project'))
        self.assertEqual(select_chat_model('Hallo', {'model': 'qwen2.5-coder:7b'}),
                         ('qwen3:4b', 'fast'))
        self.assertEqual(select_chat_model('Hallo', {'fast_model': '  '}),
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
