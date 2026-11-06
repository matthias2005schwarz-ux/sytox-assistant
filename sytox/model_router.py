"""Automatic model selection, with screen vision kept available in any chat."""
from __future__ import annotations
import re

_PROJECT = re.compile(
    r"\b(?:programmier\w*|coding|entwickl\w*|implementier\w*|debugg\w*|"
    r"kompilier\w*|refactor\w*|quellcode|sourcecode|code|skript\w*|"
    r"software|python|javascript|typescript|java|rust|github|repository|"
    r"repo|api|bugfix|build|exe|installer|plugin|programm|anwendung)\b",
    re.IGNORECASE,
)
_SCREEN_SUBJECT = re.compile(
    r"\b(?:bildschirm(?:es)?|screen|screenshots?|desktop|monitor|"
    r"fensterinhalt)\b", re.IGNORECASE
)
_SCREEN_ACTION = re.compile(
    r"\b(?:schau\w*|guck\w*|sieh\w*|seh\w*|siehst|anschauen|ansehen|"
    r"lies|lese|lesen|analysier\w*|erkenne\w*|erkenn\w*|"
    r"prüf\w*|pruef\w*|untersuch\w*|beschreib\w*|zeige?\w*|"
    r"was\s+(?:steht|siehst|ist|befindet)|"
    r"kannst\s+du\s+(?:sehen|lesen|erkennen))\b", re.IGNORECASE
)
_SCREEN_NEGATION = re.compile(
    r"\b(?:nicht|niemals|nie|ohne|kein(?:en|e|es)?)\b.{0,45}"
    r"(?:bildschirm|screen|monitor|desktop|screenshot)", re.IGNORECASE
)


def wants_screen(question: str) -> bool:
    """Require an explicit, positive request. Mentions alone never start capture."""
    text = re.sub(r"\s+", " ", str(question or "")).strip().lower()
    if not _SCREEN_SUBJECT.search(text):
        return False
    if any(phrase in text for phrase in (
        "wenn ich sage", "zum beispiel", "angenommen", "wie mache ich",
        "wie kann ich einen screenshot", "wie erstelle ich",
    )):
        return False
    if _SCREEN_NEGATION.search(text):
        return False
    return bool(_SCREEN_ACTION.search(text))


def is_project_request(question: str, task_mode: str = "once") -> bool:
    return task_mode != "once" or bool(_PROJECT.search(str(question or "")))


def select_chat_model(question: str, config: dict, task_mode: str = "once") -> tuple[str, str]:
    """Return selected model and route, honoring manual overrides."""
    manual = str(config.get("model_mode", "auto") or "auto").lower()
    if manual not in ("auto", "fast", "project"):
        manual = "auto"
    route = ("project" if is_project_request(question, task_mode) else "fast") if manual == "auto" else manual
    fallback = str(config.get("model", "qwen2.5-coder:7b"))
    model = str(config.get("project_model" if route == "project" else "fast_model") or fallback).strip()
    return model, route
