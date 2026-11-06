"""Exports include the complete selected chat, without private adjacent data."""
import tempfile
import unittest
from pathlib import Path

from sytox.storage import Store


class ChatExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.directory.name) / 'assistant.db')
        self.chat = self.store.create_chat('Mein Gespräch 👋')

    def tearDown(self):
        self.directory.cleanup()

    def test_complete_history_exceeds_default_200_message_window(self):
        for index in range(205):
            self.store.add_message(self.chat, 'user' if index % 2 == 0 else 'assistant',
                                   f'Nachricht Nummer {index:03d}')
        exported = self.store.chat_export_text(self.chat)
        positions = [exported.index(f'Nachricht Nummer {index:03d}') for index in range(205)]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(exported.count('Nachricht Nummer '), 205)
        self.assertIn('Du:\nNachricht Nummer 000', exported)
        self.assertIn('SYTOX:\nNachricht Nummer 001', exported)

    def test_unicode_and_code_are_verbatim_and_export_does_not_write(self):
        text = 'Grüße 👋\n```python\n\tprint("äöüß")\n```\n'
        self.store.add_message(self.chat, 'assistant', text)
        before = self.store.messages(self.chat)
        exported = self.store.chat_export_text(self.chat)
        self.assertIn('Titel: Mein Gespräch 👋', exported)
        self.assertIn(text, exported)
        self.assertEqual(exported.encode('utf-8').decode('utf-8'), exported)
        self.assertEqual(self.store.messages(self.chat), before)

    def test_other_chats_memories_tasks_and_logs_are_excluded(self):
        other = self.store.create_chat('Anderer geheimer Titel')
        self.store.add_message(other, 'user', 'Andere private Nachricht')
        self.store.add_memory('Private Erinnerung')
        self.store.create_task(self.chat, 'Privater Aufgabenauftrag')
        self.store.log('System', 'Privater Protokolleintrag', self.chat)
        exported = self.store.chat_export_text(self.chat)
        for private in ('Anderer geheimer Titel', 'Andere private Nachricht',
                        'Private Erinnerung', 'Privater Aufgabenauftrag', 'Privater Protokolleintrag'):
            self.assertNotIn(private, exported)

    def test_empty_chat_has_header_and_unknown_chat_is_rejected(self):
        self.assertIn('Titel: Mein Gespräch 👋', self.store.chat_export_text(self.chat))
        with self.assertRaisesRegex(ValueError, 'Unbekannter Chat'):
            self.store.chat_export_text('unknown-id')


if __name__ == '__main__':
    unittest.main()
