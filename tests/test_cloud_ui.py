"""Qt settings and quick-chat integration for optional cloud mode.

Runs offscreen with a mocked API: never sends real secrets or data.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from sytox.ui import SettingsDialog
from sytox.parallel_chat import ParallelReplyWorker


class CloudSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["sytox-cloud-settings-tests"])

    def dialog(self):
        return SettingsDialog({
            "model": "qwen3:4b", "fast_model": "qwen3:4b",
            "project_model": "qwen3-coder:30b",
            "ollama_url": "http://localhost:11434", "workspace": "C:/Projects",
        })

    def test_defaults_remain_fully_local_and_key_is_not_serialized(self):
        d = self.dialog()
        self.assertFalse(d.cloud_chat.isChecked())
        self.assertFalse(d.cloud_agent.isChecked())
        d.cloud_key.setText("sk-private-should-never-be-stored")
        values = d.values()
        self.assertNotIn("sk-private", str(values))
        self.assertNotIn("api_key", values)
        self.assertFalse(values["cloud_chat_enabled"])
        self.assertFalse(values["cloud_agent_enabled"])
        d.close()

    def test_opt_in_cloud_chat_keeps_coding_local(self):
        d = self.dialog()
        d.cloud_chat.setChecked(True)
        d.cloud_key.setText("sk-test-credential")
        with patch("sytox.ui.save_api_key") as vault, \
             patch("sytox.ui.QMessageBox.warning") as warning:
            d.validate_and_save()
        vault.assert_called_once_with("sk-test-credential")
        warning.assert_not_called()
        self.assertEqual(d.result(), QDialog.Accepted)
        settings = d.values()
        self.assertTrue(settings["cloud_chat_enabled"])
        self.assertFalse(settings["cloud_agent_enabled"])
        self.assertNotIn("sk-test-credential", str(settings))

    def test_coding_consent_is_separate_and_uses_stored_key(self):
        d = self.dialog()
        d.cloud_agent.setChecked(True)
        with patch("sytox.ui.get_api_key", return_value="already-saved"), \
             patch("sytox.ui.QMessageBox.warning") as warning:
            d.validate_and_save()
        warning.assert_not_called()
        settings = d.values()
        self.assertTrue(settings["cloud_agent_enabled"])
        self.assertFalse(settings["cloud_chat_enabled"])

    def test_missing_key_blocks_opt_in(self):
        d = self.dialog()
        d.cloud_chat.setChecked(True)
        with patch("sytox.ui.get_api_key", return_value=""), \
             patch("sytox.ui.QMessageBox.warning") as warning:
            d.validate_and_save()
        warning.assert_called_once()
        self.assertNotEqual(d.result(), QDialog.Accepted)
        d.reject()


class CloudQuickChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["sytox-cloud-chat-tests"])

    def test_cloud_enabled_calls_cloud_and_never_local_model(self):
        config = {
            "cloud_chat_enabled": True, "cloud_chat_model": "gpt-4.1-mini",
            "fast_model": "qwen3:4b", "ollama_url": "http://localhost:11434",
        }
        worker = ParallelReplyWorker(
            config, [{"role": "user", "content": "Erkläre mir Photosynthese."}],
            standalone=True)
        with patch("sytox.parallel_chat.CloudChatClient") as remote, \
             patch("sytox.parallel_chat.OllamaClient") as local:
            remote.return_value.chat.return_value = {"content": "Pflanzen nutzen Licht."}
            worker.run()
        remote.assert_called_once_with(model="gpt-4.1-mini")
        local.assert_not_called()
        self.assertEqual(worker.outcome, "done")

    def test_local_mode_does_not_access_cloud_provider(self):
        config = {
            "cloud_chat_enabled": False, "fast_model": "qwen3:4b",
            "ollama_url": "http://localhost:11434",
        }
        worker = ParallelReplyWorker(
            config, [{"role": "user", "content": "Erkläre mir Photosynthese."}],
            standalone=True)
        with patch("sytox.parallel_chat.CloudChatClient") as remote, \
             patch("sytox.parallel_chat.OllamaClient") as local:
            local.return_value.chat.return_value = {"content": "Licht."}
            worker.run()
        remote.assert_not_called()
        local.assert_called_once()
        self.assertEqual(worker.outcome, "done")


if __name__ == "__main__":
    unittest.main()
