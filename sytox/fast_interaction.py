"""Small, deterministic conversation shortcuts and safe visible-token streaming.

A strictly standalone greeting never needs to wake a 4B or 30B model.
Reasoning tags occasionally embedded in older Ollama content chunks are
internal text, not assistant-visible output. Keep those hidden without
silently rewriting ordinary sentences or project code.
"""
from __future__ import annotations

import re

_GREETING = re.compile(
    r"^(?:(?:hey|hei)\s+sytox\s*[,!]?\s+)?"
    r"(?:hi|hallo|hello|hey|moin|servus|guten\s+morgen|guten\s+tag|guten\s+abend)"
    r"[!.\s]*$", re.IGNORECASE,
)

def instant_reply(question: str) -> str | None:
    """Only exact standalone greetings. Never intercept tool or coding requests."""
    if not isinstance(question, str) or len(question) > 80:
        return None
    if _GREETING.fullmatch(question.strip()):
        return "Hallo! Wie kann ich dir helfen?"
    return None


class VisibleReplyFilter:
    """Suppress a leading <think> or <analysis> section across stream chunks.

    Only leading tagged reasoning is filtered. Once an ordinary visible answer
    begins, preserve its content exactly, including code samples that mention
    these tags. This does not claim to detect unmarked model reasoning.
    """
    _OPEN = ("<think>", "<analysis>")
    _CLOSE = {"<think>": "</think>", "<analysis>": "</analysis>"}

    def __init__(self):
        self._buffer = ""
        self._state = "leading"
        self._closing = ""

    def feed(self, chunk: str) -> str:
        if not isinstance(chunk, str) or not chunk:
            return ""
        if self._state == "visible":
            return chunk
        self._buffer += chunk
        while True:
            if self._state == "hidden":
                lower = self._buffer.lower()
                end = lower.find(self._closing)
                if end >= 0:
                    self._buffer = self._buffer[end + len(self._closing):]
                    self._state = "leading"
                    self._closing = ""
                    continue
                # Keep only a possible suffix of the closing delimiter;
                # discard the rest of the internal reasoning indefinitely.
                keep = len(self._closing) - 1
                self._buffer = self._buffer[-keep:] if keep else ""
                return ""
            stripped = self._buffer.lstrip()
            if not stripped:
                return ""
            lowered = stripped.lower()
            opener = next((name for name in self._OPEN if lowered.startswith(name)), None)
            if opener is not None:
                self._buffer = stripped[len(opener):]
                self._state = "hidden"
                self._closing = self._CLOSE[opener]
                continue
            if lowered.startswith("</think>") or lowered.startswith("</analysis>"):
                tag = "</think>" if lowered.startswith("</think>") else "</analysis>"
                self._buffer = stripped[len(tag):]
                continue
            if any(name.startswith(lowered) for name in (*self._OPEN, "</think>", "</analysis>")):
                return ""
            result = self._buffer
            self._buffer = ""
            self._state = "visible"
            return result

    def finish(self) -> str:
        """Flush only ordinary visible text, never incomplete thinking tags."""
        if self._state == "visible":
            text = self._buffer
            self._buffer = ""
            return text
        if self._state == "hidden":
            self._buffer = ""
            return ""
        stripped = self._buffer.lstrip().lower()
        if stripped and not any(tag.startswith(stripped) for tag in
                                (*self._OPEN, "</think>", "</analysis>")):
            text = self._buffer
        else:
            text = ""
        self._buffer = ""
        return text
