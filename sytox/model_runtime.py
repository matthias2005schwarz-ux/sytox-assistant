"""Model-aware Ollama inference settings and safe agent history compaction.

The model selection changes inference options, not model weights or training.
Keep conservative defaults because a 19 GB download may need substantially more RAM
with long context windows or concurrent inference.
"""
from __future__ import annotations

import json


def ollama_generation_options(model: str, context_tokens: int | None = None) -> dict:
    """Return bounded options for local coding models.

    None/0 means the model-specific default; explicit sizes require enough
    memory and are limited to 4k..32k to avoid accidental huge KV allocations.
    """
    name = str(model or "").lower().strip()
    large_coder = name.startswith("qwen3-coder:30b")
    default_context = 16384 if large_coder else 8192
    if context_tokens in (None, 0):
        context = default_context
    elif (isinstance(context_tokens, bool) or not isinstance(context_tokens, int)
          or not 4096 <= context_tokens <= 32768):
        raise ValueError("Kontextgröße muss zwischen 4096 und 32768 Tokens liegen.")
    else:
        context = context_tokens
    return {
        "temperature": 0.2 if large_coder else 0.3,
        "num_ctx": context,
        "num_predict": min(4096 if large_coder else 2048, context // 4),
    }


def compact_agent_history(messages: list[dict], goal: str, checkpoint: dict | None = None,
                          max_messages: int = 42, keep_recent: int = 26) -> list[dict]:
    """Retain system/goal/checkpoint and the most recent complete interactions.

    Never begin the retained suffix with an orphaned tool result. Tool results
    belong after an assistant tool call in Ollama's chat protocol.
    """
    if len(messages) <= max_messages:
        return messages
    if not messages:
        return []
    cp = checkpoint or {}
    plan = cp.get("coding_plan", {})
    notes = cp.get("progress_notes", [])
    pending = cp.get("unvalidated_paths", [])
    summary = (
        "Setze den ursprünglichen Auftrag fort: " + str(goal)[:1200] +
        "\nBisherige letzte Aktion (kein Fertig-Nachweis): " +
        str(cp.get("last_result", ""))[:1300] +
        "\nGespeicherter Plan (unverifiziert): " +
        json.dumps(plan, ensure_ascii=False, default=str)[:1800] +
        "\nFortschrittsnotizen (unverifiziert): " +
        json.dumps(notes[-3:] if isinstance(notes, list) else [], ensure_ascii=False,
                   default=str)[:1200] +
        "\nNoch nicht validierte Dateien: " +
        json.dumps(pending[:30] if isinstance(pending, list) else [],
                   ensure_ascii=False, default=str)[:700]
    )
    recent = list(messages[-keep_recent:])
    while recent and recent[0].get("role") == "tool":
        recent.pop(0)
    # If a truncated request starts with assistant text, preserving it is okay;
    # however, a user checkpoint must be present before it.
    return [messages[0], {"role": "user", "content": summary}] + recent
