"""Deterministic, read-only routing for explicit local program-open requests.

The resolver returns choices, never approval or execution. Window identity comes
only from the desktop adapter's process-based lookup, never a window title.
"""
from __future__ import annotations

from collections.abc import Mapping
from itertools import islice
from pathlib import PurePosixPath, PureWindowsPath
import re


_ALIASES = {
    'spotify': ('Spotify',),
    'discord': ('Discord',),
    'googlechrome': ('Google Chrome', 'Chrome'),
    'chrome': ('Google Chrome', 'Chrome'),
    'firefox': ('Firefox', 'Mozilla Firefox'),
    'mozillafirefox': ('Firefox', 'Mozilla Firefox'),
    'edge': ('Microsoft Edge', 'Edge'),
    'microsoftedge': ('Microsoft Edge', 'Edge'),
    'vscode': ('Visual Studio Code', 'VS Code'),
    'visualstudiocode': ('Visual Studio Code', 'VS Code'),
    'rechner': ('Rechner', 'Taschenrechner', 'Calculator'),
    'taschenrechner': ('Rechner', 'Taschenrechner', 'Calculator'),
    'calculator': ('Rechner', 'Taschenrechner', 'Calculator'),
    'editor': ('Editor', 'Notepad'),
    'notepad': ('Notepad', 'Editor'),
}
_WAKE_PREFIX = re.compile(
    r'^(?:hey|hei|he)\s+(?:sytox|saitox|seitox|sytoks|seitoks)(?:\s*,\s*|\s+)', re.I)
_OPEN = re.compile(
    r'^(?:bitte\s+)?(?:öffne|oeffne|starte)\s+'
    r'(?:(?:bitte|mir)\s+){0,2}(?:(?:das|die|den)\s+)?'
    r'(?:(?:programm|app|anwendung)\s+)?(.+)$', re.I)
_UNSUITABLE = re.compile(
    r'\b(?:nicht|nie|niemals|kein\w*|ohne|und|oder|dann|danach|anschließend|'
    r'anschliessend|sowie|falls|wenn|datei\w*|ordner\w*|verzeichnis\w*|'
    r'webseite\w*|website\w*|fenster\w*|gesprächsmodus|gespraechsmodus|'
    r'sprachmodus|mikrofon|öffne|oeffne|starte|lösche|loesche|beende|'
    r'schließe|schliesse|installiere|deinstalliere|sende|kopiere)\b', re.I)
_PANEL_NAMES = {'pcsteuerung', 'windowssteuerung', 'desktopsteuerung'}
_INCOMPLETE_NAMES = {'app', 'programm', 'anwendung', 'bitte', 'mir', 'das', 'die', 'den'}
_FILE_SUFFIX = re.compile(
    r'\.(?:exe|lnk|bat|cmd|com|ps1|py|js|vbs|sh|txt|pdf|docx?|xlsx?|pptx?|'
    r'zip|rar|7z|json|html?|url|msc|msi|dll|reg)$', re.I)
_MAINTENANCE = re.compile(
    r'\b(?:uninstall\w*|deinstall\w*|updat(?:e|er|es)|installer|installation|'
    r'installieren|setup|repair|reparatur|hilfe|help|readme|dokumentation|helper)\b', re.I)
_MAX_DISCOVERY = 100
_MAINTENANCE_ENDINGS = ('uninstall', 'uninstaller', 'deinstallieren', 'deinstallation',
                        'updater', 'update', 'setup', 'installer', 'installation',
                        'install', 'repair', 'helper', 'hilfe', 'help', 'readme')


def _key(value):
    return ''.join(character for character in value.casefold() if character.isalnum())


def _valid_name(value):
    if not isinstance(value, str) or not 2 <= len(value) <= 80:
        return False
    if (not value[0].isalnum() or not any(character.isalpha() for character in value)
            or len(value.split()) > 10 or '--' in value or '..' in value
            or _UNSUITABLE.search(value) or _FILE_SUFFIX.search(value)
            or _key(value) in _PANEL_NAMES or value.casefold() in _INCOMPLETE_NAMES):
        return False
    return all(character.isalnum() or character in ' .+-' for character in value)


def _canonical(value):
    return _ALIASES.get(_key(value), (value,))[0]


def _maintenance_name(value):
    separated = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', value)
    return bool(_MAINTENANCE.search(separated) or _key(value).endswith(_MAINTENANCE_ENDINGS))


def app_open_intent(phrase):
    """Recognize one explicit app-opening command after normal wake routing.

    This is intentionally narrower than natural-language understanding. Search,
    questions, files and compound requests stay on their existing UI/agent paths.
    """
    if not isinstance(phrase, str) or not phrase or len(phrase) > 180:
        return None
    if any(ord(character) < 32 for character in phrase) or '?' in phrase:
        return None
    text = _WAKE_PREFIX.sub('', phrase.strip(), count=1)
    text = ' '.join(text.split()).rstrip(' .!')
    match = _OPEN.fullmatch(text)
    if not match:
        return None
    name = re.sub(r'\s+bitte$', '', match.group(1).strip(), flags=re.I)
    return _canonical(name) if _valid_name(name) else None


def _records(value):
    if value is None:
        return [], False
    if isinstance(value, (str, bytes, Mapping)):
        return [], False
    records = list(islice(iter(value), _MAX_DISCOVERY + 1))
    return records[:_MAX_DISCOVERY], len(records) > _MAX_DISCOVERY


def _label(value, limit=120):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        return None
    return value.strip()


def _launch_path(value):
    if not _label(value, 4096):
        return None
    windows, posix = PureWindowsPath(value), PurePosixPath(value)
    if not (windows.is_absolute() or posix.is_absolute()):
        return None
    if windows.suffix.casefold() not in ('.lnk', '.exe'):
        return None
    return value


def _result(query, candidates=(), *, error=None, truncated=False):
    candidates = list(candidates)
    if error is not None:
        return {'status': 'unavailable', 'query': query, 'candidates': [],
                'message': 'Die lokale Programmsuche ist nicht verfügbar: ' + str(error)[:220]}
    if truncated:
        return {'status': 'unavailable', 'query': query, 'candidates': [],
                'message': 'Zu viele Suchtreffer. Bitte einen genaueren Programmnamen nennen.'}
    if not candidates:
        return {'status': 'not_found', 'query': query, 'candidates': [],
                'message': f'„{query}“ wurde nicht gefunden. Prüfe, ob das Programm installiert '
                           'ist und eine Verknüpfung im Startmenü oder auf dem Desktop besitzt.'}
    single = len(candidates) == 1
    return {'status': 'single' if single else 'multiple', 'query': query, 'candidates': candidates,
            'message': ('Ein passender Treffer. Bitte den Wechsel oder Start bestätigen.' if single else
                        f'{len(candidates)} passende Treffer. Welches Programm bzw. Fenster meinst du?')}


def resolve_app_request(desktop, query):
    """Return process-verified windows or discovered shortcuts, without action.

    Discovery results are untrusted metadata. Confirmed path existence and the
    current process identity must be checked by the UI immediately before action.
    """
    if not isinstance(query, str):
        query = ''
    query = ' '.join(query.strip().split())
    if not _valid_name(query):
        return {'status': 'not_found', 'query': query, 'candidates': [],
                'message': 'Bitte einen einzelnen Programmnamen ohne Pfad oder Zusatzbefehl nennen.'}
    query = _canonical(query)
    try:
        finder = getattr(desktop, 'find_app_windows', None)
        windows, truncated = _records(finder(query)) if callable(finder) else ([], False)
        candidates, seen = [], set()
        for window in windows:
            if not isinstance(window, Mapping):
                continue
            identifier = window.get('id')
            executable = _launch_path(window.get('executable'))
            if (type(identifier) is not int or identifier <= 0 or identifier in seen
                    or not executable or PureWindowsPath(executable).suffix.casefold() != '.exe'):
                continue
            seen.add(identifier)
            candidates.append({'kind': 'window', 'name': _label(window.get('app_name')) or query,
                               'window_id': identifier, 'title': _label(window.get('title'), 250) or query,
                               'executable': executable, 'active': window.get('active') is True})
        if candidates or truncated:
            return _result(query, candidates, truncated=truncated)

        aliases = _ALIASES.get(_key(query), (query,))
        exact_names = {_key(alias) for alias in aliases}
        by_path = {}
        # Compare all curated names before ranking: a primary partial match
        # (e.g. Chrome Canary) cannot hide an exact match under another alias.
        # No fuzzy edit distance, executable guessing or drive-wide search.
        for alias in aliases[:3]:
            entries, truncated = _records(desktop.find_apps(alias))
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                name, path = _label(entry.get('name')), _launch_path(entry.get('path'))
                if not name or not path or _maintenance_name(name):
                    continue
                name_key = _key(name)
                if not any(key in name_key for key in exact_names):
                    continue
                normalized = path.replace('\\', '/').rstrip('/').casefold()
                is_exact = name_key in exact_names
                previous = by_path.get(normalized)
                if previous and (previous[0] or not is_exact):
                    continue
                candidate = {'kind': 'app', 'name': name, 'path': path}
                by_path[normalized] = (is_exact, candidate)
            if truncated:
                return _result(query, truncated=True)
        exact = [candidate for is_exact, candidate in by_path.values() if is_exact]
        partial = [candidate for is_exact, candidate in by_path.values() if not is_exact]
        return _result(query, exact or partial)
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError) as exc:
        return _result(query, error=exc)
