"""Message search uses existing local data without interpreting query operators."""
import tempfile
import unittest
from pathlib import Path

from sytox.storage import Store


class ChatContentSearchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'assistant.db')
        self.first = self.store.create_chat('Nur Titel: Geheimnis')
        self.second = self.store.create_chat('Anderer Chat', kind='project')

    def tearDown(self):
        self.directory.cleanup()

    def add(self, chat, text, role='user'):
        self.store.add_message(chat, role, text)

    def test_user_and_assistant_messages_support_unicode_prefixes(self):
        self.add(self.first, 'Grüße aus Österreich')
        self.add(self.second, 'Projektbeschreibung verfügbar', 'assistant')
        self.assertEqual(self.store.matching_chat_ids('GRÜ'), {self.first})
        self.assertEqual(self.store.matching_chat_ids('Projektbeschr'), {self.second})

    def test_multiple_prefix_terms_are_combined_with_and(self):
        self.add(self.first, 'Projekt Blau wird optimiert')
        self.add(self.second, 'Projekt Rot wird geplant')
        self.assertEqual(self.store.matching_chat_ids('proje optim'), {self.first})
        self.assertEqual(self.store.matching_chat_ids('proje unbekannt'), set())

    def test_titles_are_not_message_content(self):
        self.assertEqual(self.store.matching_chat_ids('Geheimnis'), set())

    def test_deleted_or_orphaned_chat_index_entries_are_excluded(self):
        self.add(self.first, 'Nur hier steht Suchwort')
        self.store.delete_chat(self.first)
        with self.store._connect() as db:
            db.execute('INSERT INTO message_search(content,chat_id) VALUES(?,?)',
                       ('Suchwort', 'nonexistent-chat'))
        self.assertEqual(self.store.matching_chat_ids('Suchwort'), set())

    def test_missing_fts_falls_back_to_literal_substring(self):
        self.add(self.first, r'100% sicher, a_b, C:\Tools')
        self.add(self.second, '1000 sicher, acb, andere Tools')
        with self.store._connect() as db:
            db.execute('DROP TABLE message_search')
        for query in ('100%', 'a_b', r'C:\Tools'):
            with self.subTest(query=query):
                self.assertEqual(self.store.matching_chat_ids(query), {self.first})

    def test_punctuation_only_queries_use_literal_matching_even_with_fts(self):
        self.add(self.first, 'Ein Prozentzeichen: %')
        self.add(self.second, 'Eine gewöhnliche Nachricht')
        self.assertEqual(self.store.matching_chat_ids('%'), {self.first})
        self.assertEqual(self.store.matching_chat_ids('_'), set())

    def test_quotes_and_operators_cannot_broaden_the_search(self):
        self.add(self.first, 'secret value')
        self.add(self.second, 'ordinary public message')
        for query in ('secret OR *', '"secret" NEAR(ignored)', "'--"):
            with self.subTest(query=query):
                self.assertEqual(self.store.matching_chat_ids(query), set())
        self.assertEqual(self.store.matching_chat_ids('"secret"'), {self.first})
        # OR is an ordinary prefix term here, not an operator matching every chat.
        self.assertEqual(self.store.matching_chat_ids('" OR *'), {self.second})

    def test_empty_query_has_no_content_matches(self):
        self.add(self.first, 'Nachricht')
        for query in ('', '  ', None):
            self.assertEqual(self.store.matching_chat_ids(query), set())


if __name__ == '__main__':
    unittest.main()
