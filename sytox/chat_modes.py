"""Per-chat local inference routing. No model downloads or implicit migrations.

Chats created before this feature stay Qwen projects, preserving their workflow.
New ordinary chats use a smaller tool-capable Qwen3 model for conversational
responses; clearly requested small programming projects can still use the
existing approval-gated coding agent.
"""
from __future__ import annotations

import re

QUICK = "quick"
PROJECT = "project"
FAST_MODEL = "qwen3:4b"
PROJECT_MODEL = "qwen3-coder:30b"
VISION_MODEL = "qwen3-vl:4b"


def normalize_chat_mode(value):
    return QUICK if value == QUICK else PROJECT


def model_for_chat(mode, settings):
    key = "fast_model" if normalize_chat_mode(mode) == QUICK else "model"
    return str(settings.get(key) or (FAST_MODEL if key == "fast_model"
                                    else PROJECT_MODEL)).strip()


# Use the actual agent for requests that clearly want a local program/project,
# not for casual mentions of "Python", explanations, or copy/paste code examples.
_PROJECT_ACTION = re.compile(
    r"\b(?:programmier\w*|implementier\w*|entwickel\w*|"
    r"baue|bau|erstelle|erstell|schreibe|schreib|mach|mache)\b", re.I
)
_PROJECT_OBJECT = re.compile(
    r"\b(?:skript\w*|script\w*|programm\w*|projekt\w*|"
    r"python[- ]?(?:datei|script|skript)|datei\w*|"
    r"app|anwendung\w*|webseite\w*|website\w*|plugin\w*|"
    r"bot\w*|tool\w*|funktion\w*|klasse\w*)\b", re.I
)


def is_small_project_request(phrase):
    """Route explicit build/edit requests to permission-gated Agent.

    For general coding questions the quick, tool-free conversational model is
    safer and faster. This is routing, not an assumption that the requested
    workload is feasible on the user's hardware.
    """
    text = str(phrase or "").strip()
    if not text:
        return False
    if re.match(r"(?i)^(?:wie|warum|wieso|was|erkläre|kannst du mir erklären)\b", text):
        return False
    return bool(_PROJECT_ACTION.search(text) and _PROJECT_OBJECT.search(text))
