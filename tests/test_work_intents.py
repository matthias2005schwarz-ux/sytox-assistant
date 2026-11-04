"""German natural-language work controls; no real PC or microphone needed."""
import unittest

from sytox.work_intents import work_intent


class WorkIntentTests(unittest.TestCase):
    def test_explicit_pause_variations(self):
        phrases = [
            'Stopp',
            'Hör kurz auf zu programmieren',
            'Hör auf zu arbeiten',
            'Hör auf mit dem Programmieren',
            'Hör mit dem Programmieren auf',
            'Kannst du bitte kurz aufhören zu programmieren?',
            'Mach bitte eine Pause',
            'Mach mal ne Pause',
            'Pausiere den Auftrag',
            'Pausier erstmal die Arbeit',
            'Stopp die Programmierung',
            'Warte kurz mit dem Programmieren',
            'Programmier nicht weiter',
            'Lass das Programmieren erstmal sein',
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(work_intent(phrase), 'pause')

    def test_explicit_resume_variations(self):
        phrases = [
            'Mach weiter',
            'Okay mach wieder weiter',
            'Bitte arbeite weiter',
            'Programmiere weiter',
            'Setz die Arbeit fort',
            'Setze das Projekt fort',
            'Fang wieder an',
            'Fang wieder an zu programmieren',
            'Du kannst wieder weitermachen',
            'Kannst du bitte wieder weitermachen?',
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(work_intent(phrase), 'resume')

    def test_only_audio_silenced(self):
        for phrase in ['Sei still', 'Hör auf zu reden', 'Hör auf zu sprechen', 'Ruhe']:
            with self.subTest(phrase=phrase):
                self.assertEqual(work_intent(phrase), 'silence')

    def test_no_task_change_for_neutral_speech(self):
        phrases = [
            '',
            'Wie weit bist du?',
            'Arbeitest du noch?',
            'Was ist Python?',
            'Warum hörst du auf zu programmieren?',
            'Wenn ich sage hör auf zu programmieren, was passiert dann?',
            'Du sollst nicht aufhören zu programmieren',
            'Hör nicht auf zu programmieren',
            'Hör auf nicht zu programmieren',
            'Du sollst noch weiterarbeiten',
            'Wir könnten später eine Pause machen',
            'Erkläre mir den Befehl „Stopp“',
            'Hör auf zu lachen',
        ]
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertIsNone(work_intent(phrase))


if __name__ == '__main__':
    unittest.main()
