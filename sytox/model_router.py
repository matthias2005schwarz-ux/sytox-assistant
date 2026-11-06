"""Automatic model selection, with screen vision kept available in any chat."""
from __future__ import annotations
import re

DEFAULT_FAST_MODEL = 'qwen3:4b'
DEFAULT_PROJECT_MODEL = 'qwen3-coder:30b'

# A programming topic is not itself a request to operate on a project. In
# particular, questions such as "Was ist Python?" should not load a 30B model.
_DEVELOPMENT_ACTION = re.compile(
    r"\b(?:programmier(?:e|en|st)?|implementier(?:e|en|st)?|debugg?(?:e|en)?|"
    r"refactor(?:e|en)?|kompilier(?:e|en)?|compile|refactor|debug|implement)\b",
    re.IGNORECASE,
)
_PROJECT_ACTION = re.compile(
    r"\b(?:erstell\w*|schreib\w*|bau(?:e|en)?|entwickl\w*|beheb\w*|"
    r"korrigier\w*|reparier\w*|optimier\w*|analysier\w*|überarbeit\w*|"
    r"ueberarbeit\w*|bearbeit\w*|änder\w*|aender\w*|ergänz\w*|ergaenz\w*|"
    r"erweiter\w*|verbesser\w*|generier\w*|erzeug\w*|füg\w*|fueg\w*|"
    r"entfern\w*|test(?:e|en)?|write|create|build|develop|fix|edit|update|"
    r"improve|analyse|analyze)\b",
    re.IGNORECASE,
)
_PROJECT_SUBJECT = re.compile(
    r"\b(?:app|anwendung|programm|installer|exe|funktion|klasse|modul|"
    r"quellcode|sourcecode|code|skript\w*|script\w*|software|python|"
    r"javascript|typescript|java|rust|github|repository|repo|api|bugfix|"
    r"plugin|projekt|project|function|class|module|webseite|website|spiel|game|"
    r"ui|interface|oberfläche\w*|oberflaeche\w*|button\w*|schaltfläche\w*|"
    r"menü\w*|menue\w*|design|layout|ansicht\w*|animation\w*)\b|"
    r"\b[\w.-]+\.(?:py|js|ts|tsx|jsx|rs|cpp|c|cs|java|go|php|lua)\b",
    re.IGNORECASE,
)
_CODE_SUBJECT = re.compile(
    r"\b(?:quellcode|sourcecode|code|funktion|klasse|modul|script\w*|"
    r"skript\w*|repository|repo|api|plugin|projekt|project|function|class|module)\b|"
    r"\b[\w.-]+\.(?:py|js|ts|tsx|jsx|rs|cpp|c|cs|java|go|php|lua)\b",
    re.IGNORECASE,
)
_EXPLANATION = re.compile(
    r"^\s*(?:bitte\s+)?(?:was\b|wer\b|warum\b|wieso\b|weshalb\b|"
    r"wie\b|erklär\w*|erklaer\w*|erläuter\w*|erlaeuter\w*|"
    r"beschreib\w*|what\b|why\b|how\b|explain\b|describe\b)",
    re.IGNORECASE,
)
_ACTION_NEGATION = re.compile(
    r"^\s+(?:bitte\s+)?(?:nicht|niemals|nie|kein(?:e|en|em|er|es)?)\b",
    re.IGNORECASE,
)
_PROJECT_CONTINUATION = re.compile(
    r"\b(?:mach\w*|setz\w*|arbeite)\b.{0,80}\b(?:projekt|project|programmier\w*)\b"
    r".{0,45}\b(?:weiter|fort)\b",
    re.IGNORECASE,
)
_TOOL_ACTION = re.compile(
    r"\b(?:öffne\w*|oeffne\w*|starte\w*|lies|lese|zeige?\w*|liste\w*|"
    r"erstell\w*|schreib\w*|"
    r"lösch\w*|loesch\w*|speicher\w*|verschieb\w*|kopier\w*|such\w*|"
    r"open|launch|read|list|delete|save|move|copy)\b"
    r".{0,100}\b(?:datei\w*|ordner\w*|verzeichnis\w*|notepad|editor|"
    r"browser|webseite\w*|website\w*|programm\w*|fenster\w*|anwendung\w*|"
    r"file\w*|folder\w*|directory|https?://|[\w.-]+\.[a-z0-9]{1,6}\b)",
    re.IGNORECASE,
)
_OTHER_TOOL_ACTION = re.compile(
    r"\b(?:klick\w*|click)\b|\b(?:füll\w*|fuell\w*)\b.{0,60}\bformular\b|"
    r"\b(?:sende|schicke|versende|lies|lese)\b.{0,80}\b(?:e-?mails?|mails?)\b|"
    r"\b(?:merke\s+dir|erinnere\s+dich|speichere\s+(?:eine\s+)?erinnerung)\b",
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
_LIVE_SCREEN_REFERENCE = re.compile(
    r"\b(?:mein(?:en|em|e|es)?|dein(?:en|em|e|es)?|den|dem|"
    r"dies(?:em|en|e)|aktuellen)\b(?:\W+\w+){0,3}\W+"
    r"(?:bildschirm|screen|desktop|monitor|fensterinhalt)\b",
    re.IGNORECASE,
)
_SCREEN_NEGATION = re.compile(
    r"\b(?:nicht|niemals|nie|ohne|kein(?:en|e|es)?)\b.{0,45}"
    r"(?:bildschirm|screen|monitor|desktop|screenshot)", re.IGNORECASE
)


def wants_screen(question: str) -> bool:
    """Require an explicit, positive request. Mentions alone never start capture."""
    text = re.sub(r"\s+", " ", str(question or "")).strip().lower()
    if not _SCREEN_SUBJECT.search(text) or not _LIVE_SCREEN_REFERENCE.search(text):
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
    """Use the project route for development work, not technical small talk."""
    if task_mode != "once":
        return True
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    if _EXPLANATION.search(text):
        return False
    if _PROJECT_CONTINUATION.search(text):
        return True
    for action in _DEVELOPMENT_ACTION.finditer(text):
        # "Kannst du programmieren?" asks about a capability, not for a job.
        if re.fullmatch(r"kannst du (?:auch )?programmieren\??", text, re.IGNORECASE):
            return False
        if not _ACTION_NEGATION.search(text[action.end():]):
            return True
    if not _PROJECT_SUBJECT.search(text):
        return False
    for action in _PROJECT_ACTION.finditer(text):
        if _ACTION_NEGATION.search(text[action.end():]):
            continue
        if re.match(r"(?:beheb|reparier|fix)", action.group(), re.IGNORECASE):
            # Repairing a Windows app/DLL is handled by the existing diagnosis
            # service; it is not source development unless code is named.
            if not _CODE_SUBJECT.search(text):
                continue
        return True
    return False


def requires_agent(question: str, task_mode: str = "once") -> bool:
    """Keep explicit file/PC actions available without tool-enabling small talk.

    Model choice is independent: a manually selected small model can still
    execute a requested project task through the existing approval workflow.
    Explicit screen observations remain in the conversational vision path.
    """
    if is_project_request(question, task_mode):
        return True
    text = re.sub(r"\s+", " ", str(question or "")).strip()
    if _EXPLANATION.search(text) or wants_screen(text):
        return False
    return bool(_TOOL_ACTION.search(text) or _OTHER_TOOL_ACTION.search(text))


def select_chat_model(question: str, config: dict, task_mode: str = "once") -> tuple[str, str]:
    """Return selected model and route, honoring manual overrides."""
    manual = str(config.get("model_mode", "auto") or "auto").lower()
    if manual not in ("auto", "fast", "project"):
        manual = "auto"
    route = ("project" if is_project_request(question, task_mode) else "fast") if manual == "auto" else manual
    default = DEFAULT_PROJECT_MODEL if route == 'project' else DEFAULT_FAST_MODEL
    # Preserve an explicitly configured legacy/custom model. The former shipped
    # default is migrated to the dedicated route defaults when no override exists.
    legacy = str(config.get('model') or '').strip()
    fallback = legacy if legacy and legacy != 'qwen2.5-coder:7b' else default
    configured = str(config.get("project_model" if route == "project" else "fast_model") or '').strip()
    model = configured or fallback
    return model, route
