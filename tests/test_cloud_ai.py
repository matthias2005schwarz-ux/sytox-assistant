"""Offline cloud-provider regression tests: no API credentials or network needed."""
import json
import threading
import unittest
from unittest.mock import MagicMock, patch

from sytox.actions import Cancelled
from sytox.cloud_ai import (
    CloudChatClient, CloudAIError, _wire_messages, get_api_key,
    save_api_key, API_ENDPOINT, KEY_SERVICE, KEY_ACCOUNT,
)
from sytox.agent import Agent, OllamaClient


def event(delta=None, *, done=False, usage=None):
    if done:
        return b"data: [DONE]"
    data = {"choices": [{"index": 0, "delta": delta or {}}]}
    if usage:
        data["usage"] = usage
    return ("data: " + json.dumps(data, ensure_ascii=False)).encode("utf-8")


class CloudBackendTests(unittest.TestCase):
    def fake_response(self, chunks):
        reply = MagicMock()
        reply.ok = True
        reply.status_code = 200
        reply.iter_lines.return_value = list(chunks)
        return reply

    def test_offline_default_never_needs_a_cloud_key(self):
        with patch("sytox.agent.OllamaClient") as local, \
             patch("sytox.agent.CloudChatClient") as remote:
            Agent(MagicMock(), "qwen3", "http://localhost:11434",
                  ".", lambda *x: False, lambda *x: None)
        self.assertEqual(local.call_count, 2)
        remote.assert_not_called()

    def test_explicit_coding_opt_in_chooses_cloud_but_not_automatically_a_key(self):
        with patch("sytox.agent.OllamaClient") as local, \
             patch("sytox.agent.CloudChatClient") as remote:
            Agent(MagicMock(), "qwen3", "http://localhost:11434",
                  ".", lambda *x: False, lambda *x: None,
                  cloud_config={"cloud_agent_enabled": True,
                                "cloud_coding_model": "gpt-4.1"})
        remote.assert_any_call(model="gpt-4.1")
        self.assertEqual(remote.call_count, 2)
        local.assert_not_called()

    def test_no_key_never_connects_or_silently_falls_back(self):
        with patch("sytox.cloud_ai.get_api_key", return_value=""), \
             patch("sytox.cloud_ai.requests.post") as post:
            with self.assertRaisesRegex(CloudAIError, "API-Schlüssel"):
                CloudChatClient().chat([{"role": "user", "content": "Hallo"}])
        post.assert_not_called()

    def test_streamed_chat_is_visible_without_thinking_and_not_stored_by_api(self):
        reply = self.fake_response([
            event({"content": "<thi"}), event({"content": "nk>private reasoning"}),
            event({"content": "</think>Hal"}), event({"content": "lo"}),
            event({}, usage={"completion_tokens": 12}), event(done=True),
        ])
        tokens, metrics = [], []
        with patch("sytox.cloud_ai.requests.post", return_value=reply) as post:
            got = CloudChatClient("gpt-4.1-mini", api_key="example-secret").chat(
                [{"role": "user", "content": "Hi"}],
                interactive=True, think=False,
                on_token=tokens.append, on_metrics=metrics.append)
        self.assertEqual(got, {"role": "assistant", "content": "Hallo"})
        self.assertEqual("".join(tokens), "Hallo")
        kwargs = post.call_args.kwargs
        self.assertEqual(post.call_args.args[0], API_ENDPOINT)
        self.assertEqual(kwargs["json"]["model"], "gpt-4.1-mini")
        self.assertFalse(kwargs["json"]["store"])
        self.assertNotIn("example-secret", json.dumps(kwargs["json"]))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer example-secret")
        self.assertEqual(kwargs["json"]["max_completion_tokens"], 700)
        self.assertTrue(metrics[0]["completed"])
        self.assertEqual(metrics[0]["output_tokens"], 12)
        reply.close.assert_called_once()

    def test_cloud_tools_bridge_and_reply_identifier_survives(self):
        response = self.fake_response([
            event({"tool_calls": [{
                "index": 0, "id": "call_123", "type": "function",
                "function": {"name": "read_file", "arguments": '{"path":'}
            ]}),
            event({"tool_calls": [{
                "index": 0, "function": {"arguments": '"README.md"}'}
            ]}),
            event(done=True),
        ])
        schema = [{"type": "function", "function": {
            "name": "read_file", "description": "Read file",
            "parameters": {"type": "object", "properties": {}}}}]
        with patch("sytox.cloud_ai.requests.post", return_value=response) as post:
            got = CloudChatClient(api_key="key").chat(
                [{"role": "user", "content": "Read README"}], tools=schema)
        self.assertEqual(got["tool_calls"][0]["id"], "call_123")
        self.assertEqual(got["tool_calls"][0]["function"]["arguments"],
                         {"path": "README.md"})
        sent = _wire_messages([
            {"role": "user", "content": "Read README"},
            got,
            {"role": "tool", "tool_name": "read_file", "content": "file contents"},
        ])
        self.assertEqual(sent[1]["tool_calls"][0]["function"]["arguments"],
                         '{"path": "README.md"}')
        self.assertEqual(sent[2], {"role": "tool", "tool_call_id": "call_123",
                                   "content": "file contents"})
        self.assertEqual(post.call_args.kwargs["json"]["tools"], schema)

    def test_401_does_not_reveal_server_response_body_or_key(self):
        response = MagicMock(ok=False, status_code=401, text="API KEY SECRET")
        with patch("sytox.cloud_ai.requests.post", return_value=response):
            with self.assertRaises(CloudAIError) as caught:
                CloudChatClient(api_key="secret").chat([])
        self.assertIn("401", str(caught.exception))
        self.assertNotIn("SECRET", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))

    def test_cancellation_never_sends_to_network(self):
        stop = threading.Event()
        stop.set()
        with patch("sytox.cloud_ai.requests.post") as post:
            with self.assertRaises(Cancelled):
                CloudChatClient(api_key="secret").chat([], stop=stop)
        post.assert_not_called()

    def test_credential_vault_not_application_settings(self):
        with patch("keyring.set_password") as store:
            save_api_key("sk-test-secret")
        store.assert_called_once_with(KEY_SERVICE, KEY_ACCOUNT, "sk-test-secret")
        with patch("keyring.get_password", return_value="sk-test-secret") as read:
            self.assertEqual(get_api_key(), "sk-test-secret")
        read.assert_called_once_with(KEY_SERVICE, KEY_ACCOUNT)

    def test_model_name_rejects_untrusted_path_or_space(self):
        for name in ("", "foo bar", "../secret", "a" * 150):
            with self.subTest(name=name):
                with self.assertRaises(CloudAIError):
                    CloudChatClient(model=name, api_key="secret")


if __name__ == "__main__":
    unittest.main()
