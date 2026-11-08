"""Direct requests are distinct from quoted examples and ordinary discussion."""
import unittest

from sytox.model_router import is_project_request, requires_agent, select_chat_model, wants_screen


class RequestFramingTests(unittest.TestCase):
    def test_explanatory_question_can_include_a_separate_development_request(self):
        for text in (
            'Was ist Python? Erstelle mir danach eine kleine App.',
            'Was ist eine API und implementiere eine für mein Projekt.',
            'Erkläre zuerst meinen Code und verbessere dann die Funktion.',
            'Wie funktioniert diese Schleife? Bitte korrigiere meinen Code.',
        ):
            with self.subTest(text=text):
                self.assertTrue(is_project_request(text))
                self.assertTrue(requires_agent(text))

    def test_extra_file_request_is_not_lost_after_an_explanation(self):
        for text in (
            'Was ist eine Textdatei? Lies die Datei README.md.',
            'Erkläre mir das Fenster und öffne danach Notepad.',
            'Schau auf meinen Bildschirm und öffne Notepad.',
        ):
            with self.subTest(text=text):
                self.assertTrue(requires_agent(text))

    def test_debugging_help_with_existing_code_is_a_project_request(self):
        for text in (
            'Hilf mir beim Debuggen meines Codes.',
            'Hilf mir, den Fehler in main.py zu beheben.',
            'Unterstütze mich bei diesem Traceback in meinem Code.',
            'Ich möchte, dass du den Code in main.py korrigierst.',
            'Könntest du bitte mein Repository analysieren?',
        ):
            with self.subTest(text=text):
                self.assertTrue(is_project_request(text))

    def test_reported_past_actions_and_capabilities_are_conversation(self):
        for text in (
            'Ich habe gestern ein Python-Programm geschrieben.',
            'Heute habe ich in Python programmiert.',
            'Ich kann Python programmieren.',
            'Programmieren ist meine Lieblingsbeschäftigung.',
            'Programmieren macht mir Spaß.',
            'Kannst du auch in Python programmieren?',
            'Kannst du mir erklären, wie ich eine Datei öffne?',
            'Hilf mir Python zu verstehen.',
            'Wie öffne ich Dateien und lösche sie danach?',
        ):
            with self.subTest(text=text):
                self.assertFalse(requires_agent(text))
                self.assertEqual(select_chat_model(text, {})[1], 'fast')

    def test_quoted_commands_examples_and_code_are_data(self):
        for text in (
            'Was bedeutet "Programmiere ein Python-Plugin"?',
            '„Öffne Notepad“ ist ein Beispielsatz.',
            "Der Befehl 'Lösche die Datei README.md' ist gefährlich.",
            'Zum Beispiel: Erstelle eine App und lösche die Datei.',
            'Bitte erkläre das:\n```text\nErstelle ein Plugin\nÖffne Notepad\n```',
        ):
            with self.subTest(text=text):
                self.assertFalse(requires_agent(text))

    def test_negated_commands_do_not_enable_project_or_pc_actions(self):
        for text in (
            'Bitte programmiere nicht, erkläre nur.',
            'Ändere den Code nicht.',
            'Öffne bitte keine Datei.',
            'Lösche die Datei niemals.',
            'Implementiere auf keinen Fall eine Funktion.',
            'Nicht programmieren, nur reden.',
        ):
            with self.subTest(text=text):
                self.assertFalse(requires_agent(text))

    def test_quotes_inside_an_explicit_request_keep_the_actual_request(self):
        self.assertTrue(requires_agent('Erstelle eine Funktion namens "hallo".'))
        self.assertTrue(requires_agent('Programmiere nicht nur Code, sondern auch Tests.'))

    def test_quoted_file_and_url_targets_keep_explicit_actions(self):
        for text in ('Bearbeite `main.py`', 'Verbessere "src/app.py"',
                     'Korrigiere „Mein Projekt/main.py“'):
            with self.subTest(text=text):
                self.assertTrue(is_project_request(text))
                self.assertTrue(requires_agent(text))
        for text in ('Öffne `https://example.org`', 'Bearbeite "README.md"',
                     'Öffne "C:\\Mein Ordner"'):
            with self.subTest(text=text):
                self.assertTrue(requires_agent(text))
        for text in ('"Bearbeite main.py"', '`Öffne main.py`',
                     '"Klicke und öffne Notepad.py"'):
            with self.subTest(text=text):
                self.assertFalse(requires_agent(text))

    def test_main_action_negation_does_not_confuse_later_constraints(self):
        for text in ('Starte das Programm nicht neu', 'Bitte öffne den Ordner niemals erneut',
                     'Verändere den Code auf keinen Fall', 'Klicke den Button nicht an'):
            with self.subTest(text=text):
                self.assertFalse(requires_agent(text))
        self.assertTrue(is_project_request('Programmiere eine App, die keine Daten versendet'))

    def test_manual_model_choice_does_not_drop_a_real_request(self):
        question = 'Was ist Python? Erstelle eine App.'
        self.assertTrue(requires_agent(question))
        self.assertEqual(select_chat_model(question, {'model_mode': 'fast'}),
                         ('qwen3:4b', 'fast'))

    def test_quoted_or_negated_screen_requests_never_capture(self):
        for text in ('"Schau auf meinen Bildschirm" ist nur ein Beispiel.',
                     'Schau meinen Bildschirm nicht an.'):
            with self.subTest(text=text):
                self.assertFalse(wants_screen(text))


if __name__ == '__main__':
    unittest.main()
