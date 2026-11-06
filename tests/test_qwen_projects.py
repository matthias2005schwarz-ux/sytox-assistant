"""Persistent Qwen project conversations and migration, including Qt navigation."""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.storage import Store
from sytox.model_router import select_chat_model

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from sytox.ui import MainWindow
    HAS_QT = True
except ImportError:
    HAS_QT = False


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = Path(self.directory.name) / 'assistant.db'

    def tearDown(self):
        self.directory.cleanup()

    def test_projects_and_fast_chats_survive_database_reopen(self):
        store = Store(self.db)
        cid = store.create_chat('Alltag')
        pid = store.create_chat('Meine Minecraft-Entwicklung', kind='project')
        store.add_message(pid, 'user', 'Bitte codiere ein Plugin')
        self.assertEqual(store.chat_model_mode(cid), 'fast')
        self.assertEqual(store.chat_model_mode(pid), 'project')
        self.assertEqual({item['kind'] for item in store.chats()}, {'chat', 'project'})
        store = Store(self.db)
        self.assertEqual(store.chat_kind(pid), 'project')
        self.assertEqual(store.chat_model_mode(pid), 'project')
        self.assertEqual(store.messages(pid)[0]['content'], 'Bitte codiere ein Plugin')

    def test_legacy_database_migration_preserves_chat_and_messages(self):
        with sqlite3.connect(str(self.db)) as db:
            db.execute('CREATE TABLE chats(id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
            db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL)')
            db.execute("INSERT INTO chats VALUES('legacy','Älterer Chat','2025-01-01','2025-01-01')")
            db.execute("INSERT INTO messages(chat_id,role,content,created_at) VALUES('legacy','user','Meine alte Nachricht','2025-01-01')")
        db.close()  # Windows keeps assistant.db locked until the sqlite handle is closed.
        store = Store(self.db)
        self.assertEqual(store.chat_kind('legacy'), 'chat')
        self.assertEqual(store.chat_model_mode('legacy'), 'fast')
        self.assertEqual(store.messages('legacy')[0]['content'], 'Meine alte Nachricht')
        second = Store(self.db)
        self.assertEqual(second.chat_kind('legacy'), 'chat')
        project = second.create_chat('Neues Projekt', kind='project')
        self.assertEqual(second.chat_model_mode(project), 'project')

    def test_per_chat_manual_choice_is_not_shared_or_overridden_in_projects(self):
        store = Store(self.db)
        chat_a = store.create_chat('A')
        chat_b = store.create_chat('B')
        project = store.create_chat('Qwen', kind='project')
        store.set_chat_model_mode(chat_a, 'auto')
        store.set_chat_model_mode(project, 'fast')
        self.assertEqual(store.chat_model_mode(chat_a), 'auto')
        self.assertEqual(store.chat_model_mode(chat_b), 'fast')
        self.assertEqual(store.chat_model_mode(project), 'project')

    def test_project_rename_and_delete_do_not_touch_other_chats(self):
        store = Store(self.db)
        standard = store.create_chat('Normal')
        project = store.create_chat('Projektname', kind='project')
        store.rename_chat(project, 'Neuer Projektname')
        self.assertEqual(store.chat_kind(project), 'project')
        self.assertEqual(next(c['title'] for c in store.chats() if c['id'] == project), 'Neuer Projektname')
        store.delete_chat(project)
        self.assertIsNone(store.chat_kind(project))
        self.assertEqual(store.chat_kind(standard), 'chat')

    def test_invalid_chat_modes_are_rejected(self):
        store = Store(self.db)
        with self.assertRaises(ValueError):
            store.create_chat('X', kind='other')
        with self.assertRaises(ValueError):
            store.create_chat('X', model_mode='other')


@unittest.skipUnless(HAS_QT, 'PySide6 not installed')
class ProjectSidebarQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(['sytox-project-test'])

    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.patchenv = patch.dict(os.environ, {'APPDATA': self.home.name})
        self.patchenv.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window._is_exiting = True
        if self.window.tray:
            self.window.tray.hide()
        self.window.close()
        self.window.deleteLater()
        self.patchenv.stop()
        self.home.cleanup()

    def test_new_project_button_creates_separate_list_entry(self):
        self.assertEqual(self.window.chatlist.count(), 1)
        self.assertEqual(self.window.projectlist.count(), 0)
        with patch('sytox.ui.QInputDialog.getText', return_value=('Mein Spiel', True)):
            self.window.new_project_btn.click()
        self.assertEqual(self.window.chatlist.count(), 1)
        self.assertEqual(self.window.projectlist.count(), 1)
        self.assertIn('Mein Spiel', self.window.projectlist.item(0).text())
        self.assertEqual(self.window.store.chat_kind(self.window.chat_id), 'project')
        self.assertEqual(self.window.model_mode.currentData(), 'project')
        self.assertFalse(self.window.model_mode.isEnabled())
        self.assertIn('QWEN-PROJEKT', self.window.chat_breadcrumb.text())

    def test_normal_chat_returns_to_fast_model_and_project_remains_large(self):
        normal = self.window.chat_id
        with patch('sytox.ui.QInputDialog.getText', return_value=('Coding', True)):
            self.window.create_project()
        pid = self.window.chat_id
        self.assertEqual(select_chat_model('Hallo', self.window._chat_runtime_config())[0],
                         self.window.config['project_model'])
        self.window.select_chat(normal)
        self.assertEqual(self.window.model_mode.currentData(), 'fast')
        self.assertTrue(self.window.model_mode.isEnabled())
        self.assertEqual(select_chat_model('Bitte schreibe Code', self.window._chat_runtime_config())[0],
                         self.window.config['fast_model'])
        self.window.select_chat(pid)
        self.assertEqual(self.window.model_mode.currentData(), 'project')

    def test_manual_chat_choice_is_kept_after_switching(self):
        first = self.window.chat_id
        self.window.model_mode.setCurrentIndex(self.window.model_mode.findData('auto'))
        self.assertEqual(self.window.store.chat_model_mode(first), 'auto')
        with patch('sytox.ui.QInputDialog.getText', return_value=('Qwen', True)):
            self.window.create_project()
        self.window.select_chat(first)
        self.assertEqual(self.window.model_mode.currentData(), 'auto')

    def test_search_filters_both_lists_without_losing_project_type(self):
        with patch('sytox.ui.QInputDialog.getText', return_value=('Turtle-Coding', True)):
            self.window.create_project()
        self.window.search.setText('Turtle')
        self.assertEqual(self.window.projectlist.count(), 1)
        self.assertEqual(self.window.chatlist.count(), 0)
        self.window.search.clear()
        self.assertEqual(self.window.chatlist.count(), 1)

    def test_parallel_chat_is_always_fast_during_project(self):
        with patch('sytox.ui.QInputDialog.getText', return_value=('Großes Projekt', True)):
            self.window.create_project()
        dialog = self.window.show_parallel_chat()
        self.assertEqual(dialog.config['model_mode'], 'fast')
        self.assertEqual(select_chat_model('Wie geht es dir?', dialog.config)[1], 'fast')
        dialog.close()

    def test_first_project_message_preserves_its_user_chosen_name(self):
        with patch('sytox.ui.QInputDialog.getText', return_value=('Mein festes Projekt', True)):
            self.window.create_project()
        project_id = self.window.chat_id
        self.window.input.setPlainText('Programmiere ein neues Minecraft Plugin')
        with patch.object(self.window, 'start_worker') as start:
            self.window.send()
            start.assert_called_once()
        self.assertEqual(
            next(c['title'] for c in self.window.store.chats() if c['id'] == project_id),
            'Mein festes Projekt')
        self.assertEqual(self.window.store.chat_kind(project_id), 'project')

    def test_cancelled_project_creation_does_not_make_empty_project(self):
        with patch('sytox.ui.QInputDialog.getText', return_value=('', False)):
            self.window.create_project()
        self.assertEqual(self.window.projectlist.count(), 0)


if __name__ == '__main__':
    unittest.main()
