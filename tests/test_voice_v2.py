"""Voice 2.0: safer local wake routing, quick interruption and de-duplication.

Only deterministic inputs; no microphone, network or speech service is used.
"""
import unittest

from sytox.voice_features import (
    VoiceTurnRouter, VoiceCommandDeduplicator,
    fast_silence_candidate, interruption_command,
)


class VoiceRoutingV2Tests(unittest.TestCase):
    def test_common_german_wake_spelling_variants(self):
        clock = lambda: 200.0
        for phrase in ("Hey Sytox", "Hei Seitox", "He Saitox",
                       "hey sei tox", "sai tox", "Sytox"):
            with self.subTest(phrase=phrase):
                router = VoiceTurnRouter(clock=clock)
                self.assertEqual(router.command_for(phrase + ", was ist los?"),
                                 "was ist los")

    def test_no_wake_in_middle_of_unrelated_sentence(self):
        for phrase in ("Es gibt eine Sytox Webseite",
                       "Ich habe Hey Sytox gestern gelesen",
                       "die Sytox Software funktioniert",
                       "Kannst du die Seite hey seitox öffnen"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(VoiceTurnRouter().command_for(phrase))

    def test_bare_wake_arms_followup_but_never_runs_a_command(self):
        clock = [100.0]
        router = VoiceTurnRouter(clock=lambda: clock[0])
        self.assertIsNone(router.command_for("Hey Sytox"))
        clock[0] += 5
        self.assertEqual(router.command_for("Was bedeutet dieser Fehler?"),
                         "Was bedeutet dieser Fehler?")

    def test_fast_partial_only_accepts_standalone_silence(self):
        for phrase in ("Stopp", "Sytox Stopp", "Hey Sytox, stopp!",
                       "Sei still", "Hör auf zu sprechen"):
            with self.subTest(phrase=phrase):
                self.assertTrue(fast_silence_candidate(phrase))
                self.assertEqual(interruption_command(phrase), (True, ""))
        for phrase in ("ich brauche noch einen Stopp",
                       "Stopp den Programmierauftrag",
                       "Hey Sytox öffne den Editor", "öffne Chrome",
                       "Bitte starte die Anwendung"):
            with self.subTest(phrase=phrase):
                self.assertFalse(fast_silence_candidate(phrase))

    def test_no_implicit_hands_free_barge_in_during_tts(self):
        for phrase in ("öffne bitte Chrome", "das ist die Antwort von Sytox",
                       "Windows Computer Neustart"):
            self.assertEqual(interruption_command(phrase, free_listening=True),
                             (False, ""))
        # When speech is NOT playing, explicit hands-free mode still works.
        self.assertEqual(VoiceTurnRouter(require_wake=False).command_for(
            "was kannst du programmieren"), "was kannst du programmieren")
        self.assertEqual(interruption_command("Hey Sytox, öffne Editor",
                                              free_listening=True),
                         (True, "öffne Editor"))

    def test_duplicate_command_only_suppressed_briefly(self):
        clock = [10.0]
        guard = VoiceCommandDeduplicator(clock=lambda: clock[0], seconds=1.2)
        self.assertTrue(guard.allow("Öffne Editor"))
        clock[0] += 0.8
        self.assertFalse(guard.allow("öffne   editor"))
        self.assertTrue(guard.allow("Zeig Fenster"))
        self.assertTrue(guard.allow("Öffne Editor"))
        clock[0] += 1.3
        self.assertTrue(guard.allow("öffne editor"))
        self.assertFalse(guard.allow(""))


if __name__ == "__main__":
    unittest.main()
