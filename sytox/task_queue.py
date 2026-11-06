"""Detect explicit additions to an active coding job, not ordinary small talk.

Only clear modification requests are queued. Ambiguous questions remain
in the independent quick chat so ongoing programming is not interrupted.
"""
from __future__ import annotations
import re

_ACTION = re.compile(
    r"\b(?:füg\w*|hinzufüg\w*|ergänz\w*|änder\w*|"
    r"verbesser\w*|bau\w*|programmier\w*|implementier\w*|"
    r"pass\w*\s+an|entfern\w*|mach\w*\s+noch|korrigier\w*|"
    r"reparier\w*)\b", re.IGNORECASE
)
_PROJECT = re.compile(
    r"\b(?:projekt\w*|spiel\w*|programm\w*|app|anwendung\w*|"
    r"feature\w*|funktion\w*|menü\w*|interface|ui|design|"
    r"code|datei\w*|button\w*|screen\w*|einstellung\w*|"
    r"system\w*|modul\w*|ansicht\w*|animation\w*)\b", re.IGNORECASE
)
_DIRECT = re.compile(
    r"^(?:sytox[,]?\s+)?(?:bitte\s+)?"
    r"(?:füge|füg|baue|bau|ergänze|änder|ändere|implementiere|"
    r"programmiere|verbessere|korrigiere|entferne|"
    r"mach\s+(?:noch|das)|pass\s+.+\s+an)\b",
    re.IGNORECASE
)
_REF = re.compile(
    r"\b(?:da|dort|darin|dazu|dabei|noch|zusätzlich|außerdem|"
    r"bestehende\w*|aktuelle\w*|das|den|die|dem)\b", re.IGNORECASE
)
_NEGATED = re.compile(
    r"\b(?:nicht|nie|niemals|ohne)\b.{0,35}"
    r"(?:hinzufügen|einbauen|ändern|anpassen|programmieren)", re.IGNORECASE
)


def is_change_request(text: str) -> bool:
    """Require an imperative change to code/project; never treat a question as work."""
    phrase = " ".join(str(text or "").strip().split())[:2500]
    if not phrase or not _ACTION.search(phrase):
        return False
    if phrase.endswith("?") and not re.search(r"\b(?:kannst du|könntest du)\b", phrase, re.I):
        return False
    if re.search(r"\b(?:wenn ich|zum beispiel|was wäre|was passiert|"
                 r"wie funktioniert|wie kann ich|erklär mir|erkläre mir)\b",
                 phrase, re.I):
        return False
    if _NEGATED.search(phrase):
        return False
    return bool(_PROJECT.search(phrase) or (_DIRECT.search(phrase) and _REF.search(phrase)))
