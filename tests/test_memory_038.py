"""Regression tests for long-term memory, data controls and project continuity."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sytox.storage import Store
from sytox.memory_engine import extract_facts, is_continuation_request
from sytox.agent import Agent


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "assistant.db"
        self.store = Store(self.db_path)
        self.chat = self.store.create_chat("Programmierung")

    def test_auto_pref_and_cross_chat_recall(self):
        self.store.add_message(self.chat, 'user',
                               'Ich bevorzuge ein dunkles Farbschema mit roten Akzenten.')
        facts = self.store.list_memory_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['fact_key'], 'theme')
        other = self.store.create_chat('Neue Unterhaltung')
        result = self.store.related_context('Welche Designfarbe bevorzuge ich?', exclude_chat=other)
        self.assertTrue(any('roten Akzenten' in entry['content'] for entry in result))
        self.assertTrue(any('Langzeitgedächtnis' in entry['source'] for entry in result))

    def test_newer_correction_replaces_old_same_topic(self):
        first = 'Ich bevorzuge ein blaues Farbschema für meine Apps.'
        second = 'Ab jetzt bevorzuge ich ein rotes Farbschema für meine Apps.'
        self.store.add_message(self.chat, 'user', first)
        self.store.add_message(self.chat, 'user', second)
        facts = self.store.list_memory_facts()
        self.assertEqual(len(facts), 1)
        self.assertIn('rotes Farbschema', facts[0]['content'])
        self.assertEqual(facts[0]['kind'], 'correction')
        self.assertNotIn('blaues', facts[0]['content'])

    def test_project_scopes_are_independent(self):
        a = 'Für Projekt SYTOX bevorzuge ich eine schwarze Oberfläche.'
        b = 'Für Projekt TMNT bevorzuge ich eine helle Oberfläche.'
        self.store.add_message(self.chat, 'user', a)
        self.store.add_message(self.chat, 'user', b)
        facts = self.store.list_memory_facts()
        self.assertEqual({fact['scope'] for fact in facts},
                         {'project:sytox', 'project:tmnt'})
        match = self.store.related_context('SYTOX Oberfläche', exclude_chat='elsewhere')
        self.assertTrue(any('SYTOX' in e['content'] for e in match))

    def test_explicit_remember_is_stored(self):
        self.store.add_message(self.chat, 'user',
                               'Merke dir: Mein Projekt SYTOX heißt ab jetzt SYTOX AI.')
        facts = self.store.list_memory_facts()
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['scope'], 'project:sytox')
        self.assertIn('SYTOX AI', facts[0]['content'])

    def test_sensitive_input_does_not_generate_new_fact(self):
        sensitive = (
            'Merke dir: Mein Passwort ist supersecret.',
            'Merke dir: Mein API Key ist sk-test-value.',
            'Ich habe die Diagnose Asthma und nutze Medikamente.',
            'Merke dir: Meine E-Mail ist hello@example.org.',
        )
        for sentence in sensitive:
            self.store.add_message(self.chat, 'user', sentence)
        self.assertEqual(self.store.list_memory_facts(), [])

    def test_questions_and_assistant_messages_are_not_facts(self):
        self.store.add_message(self.chat, 'user', 'Wie erstelle ich einen Windows Installer?')
        self.store.add_message(self.chat, 'assistant',
                               'Ich bevorzuge ein rotes Farbschema.')
        self.assertFalse(self.store.list_memory_facts())

    def test_toggle_persists_and_prevents_capture(self):
        self.assertTrue(self.store.auto_memory_enabled())
        self.store.set_auto_memory_enabled(False)
        self.assertFalse(Store(self.db_path).auto_memory_enabled())
        self.store.add_message(self.chat, 'user', 'Ich bevorzuge eine blaue Oberfläche.')
        self.assertFalse(self.store.list_memory_facts())
        self.store.set_auto_memory_enabled(True)
        self.store.add_message(self.chat, 'user', 'Ich bevorzuge eine rote Oberfläche.')
        self.assertEqual(len(self.store.list_memory_facts()), 1)

    def test_edit_delete_and_chat_deletion(self):
        self.store.add_message(self.chat, 'user', 'Ich mag dunkles Design.')
        fact = self.store.list_memory_facts()[0]
        self.store.update_memory_fact(fact['id'], 'Ich bevorzuge schlichte dunkelrote UI.')
        self.assertIn('dunkelrote', self.store.list_memory_facts()[0]['content'])
        self.assertEqual(self.store.list_memory_facts()[0]['kind'], 'edited')
        self.store.delete_memory_fact(fact['id'])
        self.assertEqual(self.store.list_memory_facts(), [])
        self.store.add_message(self.chat, 'user', 'Ich bevorzuge ein schwarzes Farbschema.')
        self.store.delete_chat(self.chat)
        self.assertEqual(self.store.list_memory_facts(), [])

    def test_previous_tasks_can_be_resumed_with_provenance(self):
        self.store.add_message(self.chat, 'user',
                               'Programmiere das SYTOX Desktop Projekt.')
        task_id = self.store.create_task(self.chat, 'Programmiere das SYTOX Desktop Projekt.', 'until_done')
        self.store.update_task(task_id, 'paused', {
            'last_result':'Datei xyz.py geschrieben, noch nicht getestet',
            'progress_notes':[{'completed':'Menü', 'next_step':'Tests ausführen'}],
        })
        next_chat = self.store.create_chat('Spätere Sitzung')
        self.store.add_message(next_chat, 'user',
                               'Mach mit dem letzten Projekt weiter.')
        context = self.store.recent_project_context(
            'Mach mit dem letzten Projekt weiter.')
        self.assertTrue(context)
        self.assertIn('SYTOX Desktop Projekt', context[0]['content'])
        self.assertIn('noch nicht getestet', context[0]['content'])
        agent = Agent(self.store, 'fake', 'http://unused',
                      Path(self.tmp.name) / 'project', lambda *_: True,
                      lambda *_: None)
        agent.client.chat = MagicMock(return_value={
            'role':'assistant','content':'Ich prüfe zunächst die Dateien.'})
        agent.run(next_chat, 'once')
        supplied = agent.client.chat.call_args.args[0]
        self.assertIn('Projektverlauf', supplied[0]['content'])
        self.assertIn('noch nicht getestet', supplied[0]['content'])

    def test_unrelated_queries_do_not_force_project_recall(self):
        self.assertFalse(is_continuation_request('Wie wird das Wetter morgen?'))
        self.assertTrue(is_continuation_request('Wo waren wir beim letzten Projekt?'))
        self.assertEqual(self.store.recent_project_context('Was ist die Hauptstadt?'), [])

    def test_existing_schema_preserves_old_manual_memories(self):
        self.store.add_memory('Frühere bewusst gespeicherte Erinnerung')
        reopened = Store(self.db_path)
        self.assertEqual(len(reopened.list_memories()), 1)
        self.assertEqual(len(reopened.list_memory_facts()), 0)


if __name__ == '__main__':
    unittest.main()
