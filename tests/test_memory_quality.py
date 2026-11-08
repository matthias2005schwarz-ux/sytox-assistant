"""Relevance and provenance regressions for local deterministic recall."""
import tempfile
import unittest
from pathlib import Path

from sytox.memory_engine import extract_facts, project_scopes
from sytox.storage import Store


class MemoryQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'assistant.db')
        self.alpha = self.store.create_chat('Unrelated display title', kind='project')
        self.beta = self.store.create_chat('Another display title', kind='project')
        self.normal = self.store.create_chat('Normal')

    def contents(self, entries):
        return '\n'.join(entry['content'] for entry in entries)

    def project_preferences(self):
        self.store.add_message(self.alpha, 'user',
                               'Für Projekt ALPHA bevorzuge ich eine schwarze Oberfläche.')
        self.store.add_message(self.beta, 'user',
                               'Für Projekt BETA bevorzuge ich eine helle Oberfläche.')

    def test_generic_project_question_never_imports_other_project_facts(self):
        self.project_preferences()
        result = self.store.related_context('Welche Oberfläche bevorzuge ich?',
                                           exclude_chat=self.alpha, current_chat_id=self.alpha)
        self.assertIn('ALPHA', self.contents(result))
        self.assertNotIn('BETA', self.contents(result))
        # A normal chat cannot pick a project solely from the shared word.
        self.assertEqual(self.store.related_context('Welche Oberfläche?', exclude_chat=self.normal), [])

    def test_explicit_project_reference_can_recall_a_different_project(self):
        self.project_preferences()
        result = self.store.related_context('Welche Oberfläche hat Projekt BETA?',
                                           exclude_chat=self.alpha, current_chat_id=self.alpha)
        self.assertIn('BETA', self.contents(result))
        self.assertNotIn('ALPHA', self.contents(result))

    def test_explicit_project_comparison_can_recall_both_scopes(self):
        self.project_preferences()
        result = self.store.related_context('Vergleiche Projekt ALPHA und Projekt BETA Oberfläche',
                                           exclude_chat=self.normal)
        self.assertIn('ALPHA', self.contents(result))
        self.assertIn('BETA', self.contents(result))

    def test_project_chat_raw_notes_do_not_leak_on_shared_keywords(self):
        self.store.add_message(self.beta, 'user', 'PostgreSQL Datenbank: Tabellenname beta_only.')
        self.assertEqual(self.store.related_context('Welche PostgreSQL Datenbank?',
                                                   exclude_chat=self.alpha), [])

    def test_latest_correction_prevents_old_user_and_assistant_text_reappearing(self):
        source = self.store.create_chat('Vorlieben')
        self.store.add_message(source, 'user', 'Ich bevorzuge ein blaues Farbschema.')
        self.store.add_message(source, 'assistant', 'Dein Farbschema ist blaues Farbschema.')
        self.store.add_message(source, 'user', 'Ab jetzt bevorzuge ich ein rotes Farbschema.')
        result = self.store.related_context('Welches Farbschema bevorzuge ich?', exclude_chat=self.normal)
        text = self.contents(result)
        self.assertIn('rotes Farbschema', text)
        self.assertNotIn('blaues Farbschema', text)
        self.assertEqual(result[0]['kind'], 'fact')

    def test_ranked_facts_share_strict_limit_with_unrelated_pinned_notes(self):
        source = self.store.create_chat('Vorlieben')
        self.store.add_message(source, 'user', 'Ich bevorzuge ein dunkles Farbschema.')
        for number in range(10):
            self.store.add_memory(f'Unrelated pinned item number {number}')
        result = self.store.related_context('Welche Designfarbe bevorzuge ich?',
                                           exclude_chat=self.normal, limit=1)
        self.assertEqual(len(result), 1)
        self.assertIn('Farbschema', result[0]['content'])
        self.assertEqual(self.store.related_context('Designfarbe', limit=0), [])

    def test_favorite_color_question_matches_current_theme_fact_without_same_words(self):
        source = self.store.create_chat('Vorlieben')
        self.store.add_message(source, 'user', 'Ich bevorzuge ein rotes Farbschema.')
        result = self.store.related_context('Was ist meine Lieblingsfarbe?', exclude_chat=self.normal)
        self.assertIn('rotes Farbschema', self.contents(result))

    def test_assistant_only_claim_is_not_recalled_as_a_user_fact(self):
        self.store.add_message(self.normal, 'assistant', 'Die Datenbank heißt invented_name.')
        self.assertEqual(self.store.related_context('Datenbank', exclude_chat=self.alpha), [])

    def test_old_relevant_manual_memory_is_found_beyond_recent_pinned_notes(self):
        self.store.add_memory('Restic sichert mein Dokumentenarchiv.')
        for number in range(205):
            self.store.add_memory(f'Andere bewusst gespeicherte Notiz {number}')
        result = self.store.related_context('Restic Dokumentenarchiv', limit=1)
        self.assertEqual(len(result), 1)
        self.assertIn('Restic', result[0]['content'])

    def test_raw_user_excerpt_is_labeled_unverified(self):
        self.store.add_message(self.normal, 'user', 'Datenbanklayout: drei Tabellen mit Fremdschlüsseln.')
        result = self.store.related_context('Datenbanklayout', exclude_chat=self.beta)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['kind'], 'excerpt')
        self.assertIn('unbestätigt', result[0]['source'])
        self.assertIn('Nutzerangabe', result[0]['source'])

    def test_without_fts_recall_still_uses_user_notes(self):
        with self.store._connect() as db:
            db.execute('DROP TABLE message_search')
        self.store.add_message(self.normal, 'user', 'Datenbanklayout: lokale Tabellen.')
        result = self.store.related_context('Datenbanklayout', exclude_chat=self.beta)
        self.assertIn('lokale Tabellen', self.contents(result))

    def test_old_current_chat_constraint_is_recalled_beyond_recent_window(self):
        self.store.add_message(self.alpha, 'user',
                               'Bitte nutze beim Parser ausschließlich die Standardbibliothek.')
        for number in range(16):
            self.store.add_message(self.alpha, 'assistant', f'Zwischenstand {number}')
        self.store.add_message(self.beta, 'user', 'Parser braucht eine fremde Spezialbibliothek.')
        result = self.store.current_chat_context('Was gilt für Parser und Standardbibliothek?', self.alpha)
        self.assertEqual(len(result), 1)
        self.assertIn('ausschließlich die Standardbibliothek', result[0]['content'])
        self.assertIn('aktuellen Chat', result[0]['source'])
        self.assertNotIn('Spezialbibliothek', self.contents(result))

    def test_current_recall_excludes_recent_turns_and_assistant_claims(self):
        self.store.add_message(self.alpha, 'assistant', 'Parser braucht fremde Datenbanktreiber.')
        for number in range(16):
            self.store.add_message(self.alpha, 'assistant', f'Zwischenstand {number}')
        self.store.add_message(self.alpha, 'user', 'Parser bitte nur ansehen.')
        self.assertEqual(self.store.current_chat_context('Parser', self.alpha), [])

    def test_old_current_preference_cannot_override_later_correction(self):
        self.store.add_message(self.alpha, 'user', 'Ich bevorzuge ein blaues Farbschema.')
        for number in range(16):
            self.store.add_message(self.alpha, 'assistant', f'Zwischenstand {number}')
        self.store.add_message(self.alpha, 'user', 'Ab jetzt bevorzuge ich ein rotes Farbschema.')
        result = self.store.current_chat_context('Welches Farbschema?', self.alpha)
        self.assertNotIn('blaues Farbschema', self.contents(result))
        current = self.store.related_context('Welches Farbschema?', current_chat_id=self.alpha)
        self.assertIn('rotes Farbschema', self.contents(current))

    def test_independent_font_constraint_survives_a_theme_correction(self):
        self.store.add_message(self.alpha, 'user',
                               'Ich bevorzuge ein rotes Farbschema. '
                               'Die Schrift muss mindestens 18 pt groß sein.')
        for number in range(16):
            self.store.add_message(self.alpha, 'assistant', f'Zwischenstand {number}')
        self.store.add_message(self.alpha, 'user', 'Ab jetzt bevorzuge ich ein grünes Farbschema.')
        result = self.store.current_chat_context('Welche Schriftgröße und welches Farbschema?', self.alpha)
        text = self.contents(result)
        self.assertIn('Die Schrift muss mindestens 18 pt groß sein.', text)
        self.assertNotIn('rotes Farbschema', text)

    def test_cross_chat_recall_keeps_independent_constraint_without_old_fact(self):
        source = self.store.create_chat('Vorlieben')
        self.store.add_message(source, 'user', 'Ich bevorzuge ein rotes Farbschema.\n'
                               'Schriftgröße mindestens 18 pt; Überschriften größer.')
        self.store.add_message(source, 'user', 'Ab jetzt bevorzuge ich ein grünes Farbschema.')
        result = self.store.related_context('Schriftgröße und Farbschema', exclude_chat=self.normal)
        text = self.contents(result)
        self.assertIn('Schriftgröße mindestens 18 pt', text)
        self.assertIn('grünes Farbschema', text)
        self.assertNotIn('rotes Farbschema', text)

    def test_generic_project_wording_does_not_invent_a_project_called_bevorzuge(self):
        self.assertEqual(project_scopes('Für dieses Projekt bevorzuge ich eine dunkle Oberfläche.'), set())
        facts = extract_facts('Merke dir: Für dieses Projekt bevorzuge ich eine dunkle Oberfläche.')
        self.assertTrue(facts)
        self.assertEqual(facts[0]['scope'], 'global')


if __name__ == '__main__':
    unittest.main()
