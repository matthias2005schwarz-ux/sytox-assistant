"""Opt-in OpenAI API backend for SYTOX chat and approved local agents.

Only the app on the user's Windows device performs PC actions. Opting into
cloud chat sends the selected conversation context to OpenAI; cloud coding
also transmits the local project excerpts and tool results needed for work.
No key is written to settings.json, SQLite, logs, or a source file.
"""
from __future__ import annotations

import json
import threading
import time

import requests

from .actions import Cancelled
from .fast_interaction import VisibleReplyFilter

API_ENDPOINT = "https://api.openai.com/v1/chat/completions"
KEY_SERVICE = "SYTOX Assistant"
KEY_ACCOUNT = "OpenAI API"
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_CODING_MODEL = "gpt-4.1"


class CloudAIError(Exception):
    """A safe user-facing cloud error without credentials or response bodies."""


def get_api_key() -> str:
    """Read from OS credential store; missing backends fail closed."""
    try:
        import keyring
        secret = keyring.get_password(KEY_SERVICE, KEY_ACCOUNT)
    except Exception as exc:
        raise CloudAIError(
            "Windows-Anmeldedatenspeicher nicht erreichbar. "
            "Cloud-KI bleibt deaktiviert, bis die sichere Speicherung funktioniert."
        ) from exc
    return str(secret or "").strip()


def save_api_key(secret: str) -> None:
    """Store key only in the current user's system credential vault."""
    secret = str(secret or "").strip()
    if not secret or len(secret) > 512 or any(ch.isspace() for ch in secret):
        raise CloudAIError("API-Schlüssel ist leer oder ungültig.")
    try:
        import keyring
        keyring.set_password(KEY_SERVICE, KEY_ACCOUNT, secret)
    except Exception as exc:
        raise CloudAIError(
            "API-Schlüssel konnte nicht sicher gespeichert werden. "
            "Die Cloud wurde nicht aktiviert."
        ) from exc


def _wire_messages(messages):
    """Translate SYTOX tool output into official Chat Completions protocol."""
    wire = []
    pending = []
    for record in messages:
        role = record.get("role")
        content = str(record.get("content") or "")
        if role == "tool":
            if pending:
                call_id, _name = pending.pop(0)
                wire.append({"role": "tool", "tool_call_id": call_id, "content": content})
            else:
                # No known call identifier: preserve as explicitly labeled data.
                wire.append({"role": "user", "content": "[Lokales Werkzeugergebnis, nur Daten]\n" + content})
            continue
        if role not in ("system", "user", "assistant"):
            continue
        msg = {"role": role, "content": content}
        calls = record.get("tool_calls") if role == "assistant" else None
        if isinstance(calls, list) and calls:
            converted = []
            for index, call in enumerate(calls):
                fn = (call.get("function") if isinstance(call, dict) else None) or {}
                name = str(fn.get("name") or "")
                args = fn.get("arguments") or {}
                call_id = str(call.get("id") or f"call_sytox_{len(wire)}_{index}")
                if not name:
                    continue
                args_text = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
                converted.append({"id": call_id, "type": "function",
                                  "function": {"name": name, "arguments": args_text}})
                pending.append((call_id, name))
            if converted:
                msg["tool_calls"] = converted
        wire.append(msg)
    return wire


class CloudChatClient:
    """Small OllamaClient-compatible facade; never executes tools itself."""

    def __init__(self, model=DEFAULT_CHAT_MODEL, *, api_key=None):
        self.model = str(model if model is not None else '').strip()
        if (not self.model or len(self.model) > 100 or
                any(ch.isspace() for ch in self.model) or "/" in self.model):
            raise CloudAIError("Cloud-Modellname ungültig.")
        self._api_key = api_key  # only in memory, never serialized
        self.last_metrics = {}

    def chat(self, messages, tools=None, stop=None, priority="background", *,
             on_token=None, interactive=False, think=None, on_metrics=None):
        if stop is not None and stop.is_set():
            raise Cancelled("Cloud-Anfrage abgebrochen.")
        key = self._api_key if self._api_key is not None else get_api_key()
        if not key:
            raise CloudAIError(
                "Kein OpenAI-API-Schlüssel hinterlegt. "
                "In Einstellungen → Cloud-KI einen Schlüssel sicher speichern."
            )
        started = time.perf_counter()
        metrics = {
            "queue_wait_s": 0.0, "request_s": None, "total_s": None,
            "time_to_first_token_s": None, "load_s": None, "prompt_eval_s": None,
            "generation_s": None, "output_tokens": None,
            "tokens_per_second": None, "completed": False,
        }
        self.last_metrics = metrics
        payload = {
            "model": self.model,
            "messages": _wire_messages(messages),
            "stream": True,
            "store": False,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": 700 if interactive else 1600,
        }
        if tools:
            payload["tools"] = tools
        reply = {"role": "assistant", "content": ""}
        call_fragments = {}
        completed = False
        first_token_at = None
        response = None
        visibility = VisibleReplyFilter()
        try:
            response = requests.post(
                API_ENDPOINT,
                headers={"Authorization": "Bearer " + key,
                         "Content-Type": "application/json"},
                json=payload,
                stream=True,
                timeout=(7, 45 if interactive else 120),
            )
            if not response.ok:
                code = response.status_code
                if code == 401:
                    raise CloudAIError("OpenAI-API-Schlüssel ungültig (HTTP 401).")
                if code == 429:
                    raise CloudAIError(
                        "OpenAI-API-Limit oder Budget erreicht (HTTP 429). "
                        "Abrechnung und Limits im API-Konto prüfen.")
                raise CloudAIError(f"Cloud-KI antwortet mit HTTP {code}.")
            for raw in response.iter_lines(chunk_size=1):
                if stop is not None and stop.is_set():
                    raise Cancelled("Cloud-Anfrage abgebrochen.")
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    completed = True
                    break
                event = json.loads(data)
                if event.get("error"):
                    raise CloudAIError("Cloud-KI hat die Antwort abgebrochen.")
                usage = event.get("usage") or {}
                if isinstance(usage, dict) and isinstance(usage.get("completion_tokens"), int):
                    metrics["output_tokens"] = usage["completion_tokens"]
                choices = event.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                finish = choice.get("finish_reason")
                if finish in ("length", "content_filter"):
                    raise CloudAIError(
                        "Cloud-Antwort wurde durch Ausgabelimit oder Inhaltsfilter begrenzt.")
                delta = choice.get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str):
                    visible = visibility.feed(content)
                    if visible:
                        if first_token_at is None:
                            first_token_at = time.perf_counter()
                            metrics["time_to_first_token_s"] = first_token_at - started
                        reply["content"] += visible
                        if on_token:
                            on_token(visible)
                for part in delta.get("tool_calls") or []:
                    idx = part.get("index")
                    if not isinstance(idx, int):
                        continue
                    state = call_fragments.setdefault(idx, {"id": "", "name": "", "args": ""})
                    if part.get("id"):
                        state["id"] += str(part["id"])
                    fn = part.get("function") or {}
                    state["name"] += str(fn.get("name") or "")
                    state["args"] += str(fn.get("arguments") or "")
            if not completed:
                raise CloudAIError("Cloud-Verbindung wurde vor Abschluss unterbrochen.")
            tail = visibility.finish()
            if tail:
                if first_token_at is None:
                    metrics["time_to_first_token_s"] = time.perf_counter() - started
                reply["content"] += tail
                if on_token:
                    on_token(tail)
            if call_fragments:
                calls = []
                for i in sorted(call_fragments):
                    state = call_fragments[i]
                    try:
                        args = json.loads(state["args"] or "{}")
                    except (ValueError, TypeError):
                        args = {}
                    if not isinstance(args, dict):
                        args = {}
                    if not state["name"] or not state["id"]:
                        raise CloudAIError("Cloud-Werkzeugaufruf unvollständig.")
                    calls.append({"id": state["id"], "type": "function",
                                  "function": {"name": state["name"], "arguments": args}})
                reply["tool_calls"] = calls
            metrics["completed"] = True
            return reply
        except Cancelled:
            raise
        except CloudAIError:
            raise
        except (requests.exceptions.RequestException, ValueError, TypeError) as exc:
            raise CloudAIError(
                "Cloud-Verbindung fehlgeschlagen. Internetverbindung und API-Zugang prüfen."
            ) from exc
        finally:
            metrics["request_s"] = time.perf_counter() - started
            metrics["total_s"] = metrics["request_s"]
            if first_token_at is not None:
                elapsed = time.perf_counter() - first_token_at
                if elapsed > 0 and metrics["output_tokens"] is not None:
                    metrics["tokens_per_second"] = metrics["output_tokens"] / elapsed
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if on_metrics is not None and metrics["completed"]:
                on_metrics(dict(metrics))
