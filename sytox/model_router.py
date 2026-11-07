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
_PROJECT_CONTINUATION = re.compile(
    r"\b(?:mach\w*|setz\w*|arbeite)\b.{0,80}\b(?:projekt|project|programmier\w*)\b"
    r".{0,45}\b(?:weiter|fort)\b",
    re.IGNORECASE,
)
_TOOL_ACTION = re.compile(
    r"\b(?:öffne\w*|oeffne\w*|starte\w*|lies|lese|zeige?\w*|liste\w*|"
    r"erstell\w*|schreib\w*|bearbeit\w*|änder\w*|aender\w*|verbesser\w*|"
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


def _prose(question):
    """Quoted examples and code are data, not direct action requests."""
    text = str(question or '')
    text = re.sub(r'(?ms)^ {0,3}(`{3,}|~{3,})[^\n]*\n.*?(?:^ {0,3}\1[ \t]*(?:\n|$)|\Z)', ' ', text)

    def inert_target(match):
        content = match.group()[1:-1].strip()
        # Keep target types for routing, never verbs from the quoted text.
        # The original untouched message is what the selected model receives.
        if re.fullmatch(r'https?://\S+', content, re.I):
            return ' Webziel https://quoted.invalid '
        suffix = re.search(r'\.([a-z][a-z0-9]{0,11})$', content, re.I)
        if suffix:
            return ' Dateiziel.' + suffix.group(1) + ' '
        return ' Dateiziel ' if '/' in content or '\\' in content else ' '

    return re.sub(r"\"[^\"\n]*\"|„[^“\n]*“|«[^»\n]*»|`[^`\n]*`|(?<!\w)'[^'\n]*'(?!\w)", inert_target, text)


def _negated(text):
    # Scope negation to one clause; "nicht nur" is an additive request.
    text = re.sub(r'\bnicht nur\b', '', text, flags=re.I)
    # Later relative clauses describe constraints, not a negated main action.
    main_clause = text.split(',', 1)[0]
    if re.search(r'\b(?:nicht|niemals|nie|kein\w*)\b', main_clause, re.I):
        return True
    return bool(re.search(
        r'^(?:bitte\s+)?(?:nicht|niemals|nie|kein\w*)\b|'
        r'^\w+\s+(?:bitte\s+)?(?:nicht|niemals|nie|kein\w*)\b|'
        r'\b(?:nicht|niemals|nie)\s*(?:[,;.!?]|$)|'
        r'\b(?:auf keinen fall|unter keinen umständen)\b', text, re.I))


def _action_clauses(question):
    """Recognize explicit request framing, including a command after a question.

    This is conservative local routing, not permission to execute an action.
    The Agent still performs its ordinary approval and validation checks.
    """
    for sentence in re.split(r'[?!;\n]+|(?<=\.)\s+', _prose(question)):
        sentence = sentence.strip()
        if re.match(r'^(?:zum beispiel|beispiel|angenommen|wenn ich|falls ich|'
                    r'ich (?:habe|hatte|kann|konnte|lerne)|der (?:satz|befehl|nutzer))\b', sentence, re.I):
            continue
        how_question = bool(re.match(r'^(?:bitte\s+)?(?:wie|how)\b', sentence, re.I))
        for index, clause in enumerate(re.split(
                r'\s+(?:und|aber)\s+|,\s*(?:danach|dann|anschließend|anschliessend)\s+', sentence, flags=re.I)):
            clause = clause.strip(' ,:')
            # "Wie öffne ich ... und lösche Dateien?" remains an explanation.
            if index and how_question and not re.match(r'^(?:bitte|kannst|könntest|würdest)\b', clause, re.I):
                continue
            clause = re.sub(r'^(?:(?:hey\s+)?sytox[, ]+)?(?:(?:bitte|danach|dann|anschließend|anschliessend)[, ]+)*', '', clause, flags=re.I)
            if not clause or _negated(clause) or _EXPLANATION.match(clause):
                continue
            polite = re.match(r'^(?:kannst|könntest|koenntest|würdest|wuerdest)\s+du\s+', clause, re.I)
            desired = re.match(r'^ich\s+(?:möchte|moechte|will|wünsche|wuensche)\b.*?\bdass du\s+', clause, re.I)
            if polite or desired:
                clause = clause[(polite or desired).end():].strip()
                clause = re.sub(r'^(?:bitte\s+)?', '', clause, flags=re.I)
                if (_EXPLANATION.match(re.sub(r'^mir\s+', '', clause, flags=re.I))
                        or _negated(clause)):
                    continue
                # A broad capability question is not an instruction to build.
                if re.fullmatch(r'(?:auch\s+)?(?:(?:in|mit)\s+)?(?:\w+\s+)?programmieren', clause, re.I):
                    continue
                yield clause
            elif re.match(r'^(?:hilf|helfe|unterstütze|unterstuetze)\s+(?:mir|mich)\b', clause, re.I):
                if not re.search(r'\b(?:verstehen|lernen|erklären|erklaeren)\b', clause, re.I):
                    yield clause
            elif (_DEVELOPMENT_ACTION.match(clause) or _PROJECT_ACTION.match(clause)
                  or _TOOL_ACTION.match(clause) or _OTHER_TOOL_ACTION.match(clause)
                  or _PROJECT_CONTINUATION.match(clause)):
                # Verb-first questions or reported actions are not imperatives.
                if not re.match(r'^\w+\s+(?:ich|wir|man|er|sie|es|ist|sind|war|macht|hilft)\b', clause, re.I):
                    yield clause


def wants_screen(question: str) -> bool:
    """Require an explicit, positive request. Mentions alone never start capture."""
    text = re.sub(r"\s+", " ", _prose(question)).strip().lower()
    if not _SCREEN_SUBJECT.search(text) or not _LIVE_SCREEN_REFERENCE.search(text):
        return False
    if any(phrase in text for phrase in (
        "wenn ich sage", "zum beispiel", "angenommen", "wie mache ich",
        "wie kann ich einen screenshot", "wie erstelle ich",
    )):
        return False
    if _SCREEN_NEGATION.search(text) or re.search(
            r'\b(?:bildschirm|screen|monitor|desktop)\b.{0,35}\bnicht\s*(?:an)?[.!?]*$', text):
        return False
    return bool(_SCREEN_ACTION.search(text))


def is_project_request(question: str, task_mode: str = "once") -> bool:
    """Use the project route for requested development work, not quoted topics."""
    if task_mode != "once":
        return True
    for clause in _action_clauses(question):
        if _PROJECT_CONTINUATION.search(clause) or _DEVELOPMENT_ACTION.search(clause):
            return True
        if not _PROJECT_SUBJECT.search(clause):
            continue
        if re.match(r'^(?:hilf|helfe|unterstütze|unterstuetze)\b', clause, re.I):
            if _CODE_SUBJECT.search(clause) and re.search(r'\b(?:fehler|bug|traceback|exception|absturz)\b', clause, re.I):
                return True
        for action in _PROJECT_ACTION.finditer(clause):
            # Windows app/DLL repair remains in the scoped diagnosis service.
            if re.match(r'(?:beheb|reparier|fix)', action.group(), re.I) and not _CODE_SUBJECT.search(clause):
                continue
            return True
    return False


def requires_agent(question: str, task_mode: str = "once") -> bool:
    """Tool need is independent of manual model choice and screen observations."""
    if is_project_request(question, task_mode):
        return True
    return any(not wants_screen(clause) and
               (_TOOL_ACTION.search(clause) or _OTHER_TOOL_ACTION.search(clause))
               for clause in _action_clauses(question))


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
