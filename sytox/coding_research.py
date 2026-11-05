"""Privacy-first, bounded coding research for an offline-first programming agent.

Only fixed public language/error categories enter the query. Never send code,
raw compiler output, project paths, task descriptions or other private text.
"""
from __future__ import annotations

import re


_OFFLINE = re.compile(
    r"\b(?:ohne internet|offline|keine websuche|nicht recherchieren|"
    r"nicht online suchen|nicht im internet suchen|do not search|no internet|"
    r"without internet|do not browse)\b", re.I)

_LANGUAGES = (
    (r"\bc\+\+\b|\b(?:g\+\+|clang\+\+|cpp|cmake)\b|\.cpp\b|\.hpp\b", "C++"),
    (r"\bc#\b|\b(?:csharp|dotnet|msbuild)\b|\.csproj\b|\.cs\b", "C#"),
    (r"\b(?:typescript|tsc|ts\d{4})\b|\.tsx?\b", "TypeScript"),
    (r"\b(?:javascript|node\.?js|npm)\b|\.jsx?\b", "JavaScript"),
    (r"\b(?:python|pytest|pyinstaller|pip|traceback)\b|\.py\b", "Python"),
    (r"\b(?:rust|cargo|rustc|borrow checker)\b|\.rs\b|error\[e\d{4}\]", "Rust"),
    (r"\b(?:golang|go\.mod|go build|go test)\b|\.go\b", "Go"),
    (r"\b(?:kotlin|kotlinc)\b|\.kt\b", "Kotlin"),
    (r"\b(?:java|javac|maven|gradle)\b|\.java\b", "Java"),
    (r"\b(?:php|composer)\b|\.php\b", "PHP"),
    (r"\b(?:lua|luac)\b|\.lua\b", "Lua"),
    (r"\b(?:gcc|clang|makefile)\b|\.c\b", "C"),
)
_ERROR_CATEGORIES = (
    (r"\b(?:modulenotfounderror|importerror|cannot find module|"
     r"no module named|unresolved import)\b", "missing module import dependency fix"),
    (r"\b(?:syntaxerror|indentationerror|unexpected token|"
     r"syntax error|parser error)\b", "syntax parser error debugging"),
    (r"\b(?:typeerror|type mismatch|type checking|"
     r"incompatible types|cannot convert)\b", "type checking error debugging"),
    (r"\b(?:assertionerror|assertion failed|test failed|"
     r"failures|failed tests?)\b", "failing unit test diagnosis"),
    (r"\b(?:permission denied|access denied)\b", "permissions configuration troubleshooting"),
    (r"\b(?:linker|undefined reference|unresolved external|"
     r"ld: error|ld returned)\b", "linker missing symbol fix"),
    (r"\b(?:borrow checker|cannot borrow|moved value)\b", "ownership borrow checker fix"),
    (r"\b(?:runtimeerror|exception|traceback)\b", "runtime exception debugging"),
)
_TOPICS = (
    (r"\b(?:desktop|gui|qt|fenster|oberfläche|ui)\b", "desktop GUI"),
    (r"\b(?:server|socket|network|netzwerk|proxy|http)\b", "network server"),
    (r"\b(?:datenbank|database|sql|sqlite)\b", "database"),
    (r"\b(?:api|rest|graphql)\b", "REST API"),
    (r"\b(?:plugin|extension|erweiterung)\b", "plugin architecture"),
    (r"\b(?:spiel|game|engine|unity|unreal)\b", "game development"),
    (r"\b(?:test|pytest|unittest)\b", "unit tests"),
    (r"\b(?:build|compiler|exe|kompilier|installer)\b", "build tooling"),
)


def coding_research_allowed(goal: str) -> bool:
    """An explicit offline request always forbids automatic public searches."""
    return not _OFFLINE.search(str(goal or ''))


def coding_uncertain(text: str) -> bool:
    """Detect model-signalled inability, not arbitrary error messages or task text."""
    text = str(text or '')[:1400]
    return bool(re.search(
        r"\b(?:weiß nicht (?:wie|weiter)|weiss nicht (?:wie|weiter)|"
        r"keine ahnung|unklar,? wie|nicht sicher,? wie|"
        r"ich (?:bin|weiß) (?:mir )?nicht sicher|"
        r"i (?:don't|do not) know (?:how|what)|"
        r"not sure how|cannot figure out|"
        r"weiß nicht,? wie ich (?:das|es) (?:programmieren|umsetzen) soll)\b",
        text, re.I))


def failed_coding_tool(name: str, result: str) -> bool:
    """Only failures of coding/test tools trigger automatic research."""
    if name not in ('run_command', 'project_build', 'selfdev_validate'):
        return False
    result = str(result or '')
    if result.startswith(('FEHLER Denied:', 'FEHLER PermissionError:',
                          'FEHLER Cancelled:')):
        return False
    if name == 'run_command':
        return bool(re.match(r"Exit code: [1-9]\d*\b", result)) or result.startswith("FEHLER ")
    if name == 'project_build':
        return result.startswith("FEHLER ")
    return result.startswith("FEHLER ") or (
        "fehlgeschlagen" in result.casefold()
        and not result.startswith("Syntaxprüfung bestanden;"))


def public_coding_query(goal: str, diagnostic: str = '') -> str:
    """Build a search query from an allowlist, NEVER concatenate private input.

    Detect language and error type from private text, but never include any
    verbatim portion, filename, token, stack trace, command or task name.
    """
    goal = str(goal or '')[:3000]
    diagnostic = str(diagnostic or '')[:3500]
    combined = diagnostic + " " + goal
    language = next(
        (label for pattern, label in _LANGUAGES
         if re.search(pattern, combined, re.I)), "software development")
    if diagnostic:
        category = next(
            (label for pattern, label in _ERROR_CATEGORIES
             if re.search(pattern, diagnostic, re.I)), "compiler test failure debugging")
        code = ""
        for pattern in (r"\bCS\d{4,5}\b", r"\bTS\d{4,5}\b", r"\bE\d{4}\b"):
            match = re.search(pattern, diagnostic, re.I)
            if match:
                code = match.group(0).upper()
                break
        return f"{language} {code} {category} official documentation".replace("  ", " ")
    topic = next(
        (label for pattern, label in _TOPICS
         if re.search(pattern, goal, re.I)), "programming implementation")
    return f"{language} {topic} implementation tutorial official documentation"
