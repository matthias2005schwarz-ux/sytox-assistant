"""Strict Ollama tool-call validation before any agent action or permission prompt.

Qwen3-Coder can return structured function arguments either as a Python/JSON
object or as a JSON-encoded string. Invalid output must never become an empty
argument dict, silently invoke tools, or partially execute an oversized batch.
"""
from __future__ import annotations

import json
import re

MAX_CALLS_PER_TURN = 8
MAX_ARGUMENT_CHARS = 120_000
MAX_TOOL_NAME_CHARS = 80


class ToolProtocolError(ValueError):
    """Model formatting error; send a bounded retry hint, not a tool action."""


def _check_value(value, spec: dict, field: str, depth: int = 0) -> None:
    if depth > 8:
        raise ToolProtocolError("Werkzeugargument ist zu tief verschachtelt.")
    kind = spec.get("type")
    valid = {
        "string": lambda v: isinstance(v, str),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }
    if kind in valid and not valid[kind](value):
        raise ToolProtocolError(f"Argument '{field}' erwartet Typ '{kind}'.")
    if "enum" in spec and value not in spec["enum"]:
        raise ToolProtocolError(f"Argument '{field}' hat einen nicht erlaubten Wert.")
    if kind == "array":
        if len(value) > 200:
            raise ToolProtocolError(f"Liste '{field}' ist zu lang.")
        items = spec.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                _check_value(item, items, f"{field}[{i}]", depth + 1)
    if kind == "object":
        props = spec.get("properties", {})
        if not isinstance(props, dict):
            props = {}
        missing = [name for name in spec.get("required", []) if name not in value]
        if missing:
            raise ToolProtocolError(
                f"Pflichtargument '{missing[0]}' fehlt in '{field}'.")
        if spec.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise ToolProtocolError(
                    f"Nicht unterstütztes Argument '{sorted(extra, key=str)[0]}' in '{field}'.")
        for key, subvalue in value.items():
            if not isinstance(key, str):
                raise ToolProtocolError("Argumentnamen müssen Text sein.")
            if isinstance(props.get(key), dict):
                _check_value(subvalue, props[key], key, depth + 1)


def normalize_tool_calls(calls, offered_tools: list[dict]) -> list[dict]:
    """Validate an entire batch atomically; never run any of it on error.

    The normalized result contains only advertised tool names, typed arguments
    and Ollama-compatible function records. It does *not* grant permission to
    execute anything; Toolkit approvals remain separate.
    """
    if not isinstance(calls, list) or not calls:
        raise ToolProtocolError("Werkzeugaufrufe müssen eine nichtleere Liste sein.")
    if len(calls) > MAX_CALLS_PER_TURN:
        raise ToolProtocolError(
            f"Zu viele Werkzeuge auf einmal. Maximal {MAX_CALLS_PER_TURN} "
            "pro Antwort; weitere Werkzeuge in der nächsten Antwort aufrufen.")
    catalog = {
        spec["function"]["name"]: spec["function"].get("parameters", {})
        for spec in offered_tools
        if isinstance(spec, dict) and isinstance(spec.get("function"), dict)
        and isinstance(spec["function"].get("name"), str)
    }
    clean = []
    for call in calls:
        if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
            raise ToolProtocolError("Werkzeugaufruf benötigt 'function'.")
        fn = call["function"]
        name = fn.get("name")
        if (not isinstance(name, str) or len(name) > MAX_TOOL_NAME_CHARS
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
                or name not in catalog):
            raise ToolProtocolError("Werkzeugname ist unbekannt oder nicht freigegeben.")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            if len(args) > MAX_ARGUMENT_CHARS:
                raise ToolProtocolError("Werkzeugargumente sind zu lang.")
            try:
                args = json.loads(args)
            except (TypeError, ValueError) as exc:
                raise ToolProtocolError(
                    f"Argumente für '{name}' müssen gültiges JSON sein.") from exc
        if not isinstance(args, dict):
            raise ToolProtocolError(
                f"Argumente für '{name}' müssen ein JSON-Objekt sein.")
        try:
            size = len(json.dumps(args, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise ToolProtocolError("Werkzeugargumente enthalten ungültige Werte.") from exc
        if size > MAX_ARGUMENT_CHARS:
            raise ToolProtocolError("Werkzeugargumente sind zu lang.")
        _check_value(args, catalog[name], name)
        record = {"type": "function",
                  "function": {"name": name, "arguments": args}}
        # Ollama may return an index for multi-call responses; preserve it.
        index = fn.get("index")
        if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            record["function"]["index"] = index
        clean.append(record)
    return clean
