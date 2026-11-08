"""Plan bounded local development checks without running project code.

Plans describe commands, not successful verification. A caller must still use
the normal command approval, cancellation and output-validation path.
"""
from __future__ import annotations

import ast
import configparser
import json
import os
import re
from pathlib import Path, PurePosixPath


_IGNORED = {'.git', '.hg', '.svn', '.venv', 'venv', 'env', 'node_modules',
            '__pycache__', '.pytest_cache', '.mypy_cache', '.tox', '.nox',
            'build', 'dist', 'target', 'build_output', 'build_work', 'backups',
            '.next', '.nuxt', 'coverage', 'htmlcov', 'vendor'}
_MAX_FILES = 1600
_MAX_ENTRIES = 6000
_MAX_TEXT_BYTES = 64000
_MAX_CHECKS = 6


def _scan(root):
    files, entries, truncated = [], 0, False
    if not root.is_dir():
        return files, truncated
    for directory, folders, names in os.walk(root, followlinks=False):
        base = Path(directory)
        depth = len(base.relative_to(root).parts)
        folders[:] = sorted(name for name in folders if name.casefold() not in _IGNORED
                            and not name.startswith('.')
                            and not (base / name).is_symlink()) if depth < 7 else []
        entries += len(folders) + len(names)
        for name in sorted(names):
            path = base / name
            if path.is_symlink() or not path.is_file():
                continue
            if (name.startswith('.') and name not in ('.coveragerc',)) or name.casefold().endswith(
                    ('.pem', '.key', '.p12', '.pfx')):
                continue
            files.append(path.relative_to(root).as_posix())
            if len(files) >= _MAX_FILES:
                truncated = True
                break
        if truncated or entries >= _MAX_ENTRIES:
            truncated = True
            break
    return files, truncated


def _read(root, relative):
    """Read only small regular, non-linked files below the selected root."""
    path = root / relative
    try:
        if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != root):
            return None
        if root not in path.resolve().parents or not path.is_file() or path.stat().st_size > _MAX_TEXT_BYTES:
            return None
        with path.open('rb') as handle:
            raw = handle.read(_MAX_TEXT_BYTES + 1)
        if len(raw) > _MAX_TEXT_BYTES or b'\0' in raw:
            return None
        return raw.decode('utf-8-sig')
    except (OSError, UnicodeError, ValueError):
        return None


def _argument(relative):
    """Use the shared safe subset accepted by Windows and POSIX tokenizers."""
    if not re.fullmatch(r'[A-Za-z0-9_./ -]+', relative) or relative.startswith('-'):
        return None
    return '"' + relative + '"' if ' ' in relative else relative


def _pytest_configured(root, files):
    if 'pytest.ini' in files:
        text = _read(root, 'pytest.ini')
        if text and re.search(r'^\s*\[pytest\]\s*$', text, re.MULTILINE):
            return True
    if 'setup.cfg' in files:
        text = _read(root, 'setup.cfg')
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(text or '')
            if config.has_section('tool:pytest'):
                return True
        except configparser.Error:
            pass
    if 'pyproject.toml' in files:
        text = _read(root, 'pyproject.toml')
        try:
            import tomllib
            config = tomllib.loads(text or '')
            return isinstance(config.get('tool', {}).get('pytest', {}).get('ini_options'), dict)
        except (ImportError, ValueError, AttributeError, TypeError):
            pass
    return False


def _pytest_tests(root, tests):
    remaining = 256000
    for relative in tests[:80]:
        text = _read(root, relative)
        if text is None:
            continue
        text = text[:remaining]
        remaining -= len(text)
        try:
            module = ast.parse(text)
        except (SyntaxError, ValueError, RecursionError):
            module = None
        if module is not None:
            for node in module.body:
                if isinstance(node, (ast.Import, ast.ImportFrom)) and (
                        getattr(node, 'module', '') == 'pytest' or any(
                            alias.name == 'pytest' for alias in node.names)):
                    return True
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'):
                    return True
                if isinstance(node, ast.ClassDef) and node.name.startswith('Test') and not node.bases:
                    if any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and
                           child.name.startswith('test_') for child in node.body):
                        return True
        if remaining <= 0:
            break
    return False


def _python_checks(root, files, changed, checks, notes):
    tests = [path for path in files if path.endswith('.py') and
             (PurePosixPath(path).name.startswith('test_') or PurePosixPath(path).name.endswith('_test.py'))]
    python_files = [path for path in files if path.endswith('.py')]
    if not python_files:
        return []
    pytest = _pytest_configured(root, files) or _pytest_tests(root, tests)
    if tests or pytest:
        if pytest:
            checks.append({'command': 'python -m pytest', 'label': 'Vorhandene Python-Tests (pytest)',
                           'kind': 'tests', 'runner': 'pytest'})
            notes.append('pytest ist durch Konfiguration oder Testcode erkennbar; es wird nicht automatisch installiert.')
        else:
            # Nested suites are planned separately: unittest discovery does not
            # recurse through directories without __init__.py. A parent suite
            # alone could therefore pass while leaving nested tests unrun.
            directories = sorted({str(PurePosixPath(path).parent) for path in tests})
            starts = directories
            for start in starts:
                argument = _argument(start)
                if argument is None:
                    notes.append('Ein Testpfad benötigt einen projektspezifischen Befehl; kein automatisch geratener Shellbefehl.')
                    continue
                command = 'python -m unittest discover -s ' + argument
                # unittest's default pattern ignores pytest-style *_test.py.
                if any(PurePosixPath(path).name.endswith('_test.py') and
                       not PurePosixPath(path).name.startswith('test_') for path in tests):
                    command += ' -p "*test*.py"'
                checks.append({'command': command, 'label': 'Vorhandene Python-Tests (' + start + ')',
                               'kind': 'tests', 'runner': 'unittest'})
            if any('/' in start for start in starts):
                notes.append('Verschachtelte Tests werden vom Projektordner aus gestartet; benötigte Importpfade bleiben projektspezifisch.')
        return tests

    selected = [path for path in changed if path in python_files] or python_files
    arguments = [_argument(path) for path in selected]
    if any(argument is None for argument in arguments):
        notes.append('Ein Python-Dateipfad ist für automatische Befehle ungeeignet; die Datei benötigt eine gezielte Prüfung.')
    arguments = [argument for argument in arguments if argument is not None]
    while arguments and len(checks) < _MAX_CHECKS:
        batch, length = [], len('python -m compileall -q ')
        while arguments and length + len(arguments[0]) + 1 < 1200:
            argument = arguments.pop(0)
            batch.append(argument)
            length += len(argument) + 1
        if not batch:
            notes.append('Ein Dateipfad überschreitet das Befehlslimit; die Datei benötigt eine gezielte Prüfung.')
            arguments.pop(0)
            continue
        checks.append({'command': 'python -m compileall -q ' + ' '.join(batch),
                       'label': 'Python-Syntax prüfen (kein Funktionstest)',
                       'kind': 'syntax', 'runner': 'compileall'})
    if arguments:
        notes.append('Die Syntaxprüfung ist begrenzt; weitere Python-Dateien wurden nicht in den Plan aufgenommen.')
    notes.append('Keine vorhandenen Python-Tests gefunden. Syntaxprüfung beweist keine korrekte Funktion.')
    return tests


def _npm_runner(script, text, dependencies):
    """Recognize only single, local, non-watch development runner commands."""
    if not isinstance(text, str) or not text.strip() or len(text) > 1000:
        return None
    if re.search(r'[;&|><`$\r\n]', text):
        return None
    # Shell quoting wrappers, environment setters and paths have platform-
    # dependent semantics. A conservative plan can leave these to the model.
    if re.search(r'["\'\\]', text):
        return None
    words = text.strip().split()
    lower = [word.casefold() for word in words]
    if any(word.startswith(('--watch', '--ui', '--browser', '--fix', '--passwithnotests'))
           or word in ('install', 'publish', 'release', 'serve', 'dev', 'download') for word in lower):
        return None
    runner = lower[0]
    if script == 'test':
        if runner == 'node' and lower[1:2] == ['--test']:
            return 'node'
        if runner == 'jest' and 'jest' in dependencies:
            return 'jest'
        if runner == 'vitest' and 'vitest' in dependencies and ('run' in lower[1:] or '--run' in lower[1:]):
            return 'vitest'
    elif script == 'lint' and runner == 'eslint' and 'eslint' in dependencies:
        return 'eslint'
    elif script == 'typecheck' and runner == 'tsc' and 'typescript' in dependencies:
        if '--noemit' in lower and '--build' not in lower and '-b' not in lower:
            index = lower.index('--noemit')
            if index + 1 < len(lower) and lower[index + 1] == 'false':
                return None
            return 'tsc'
    elif script == 'build' and runner == 'vite' and 'vite' in dependencies and lower[1:2] == ['build']:
        return 'vite'
    return None


def _javascript_checks(root, files, checks, notes):
    if 'package.json' not in files:
        if any(path.endswith('/package.json') for path in files):
            notes.append('Nur verschachtelte JavaScript-Projekte gefunden; deren Arbeitsordner muss gezielt gewählt werden.')
        return []
    text = _read(root, 'package.json')
    try:
        package = json.loads(text or '')
    except (ValueError, TypeError):
        notes.append('package.json ist nicht lesbar, zu groß oder ungültig; keine npm-Befehle geplant.')
        return []
    if not isinstance(package, dict) or not isinstance(package.get('scripts', {}), dict):
        notes.append('package.json enthält keine gültigen Entwicklungs-Skripte.')
        return []
    scripts = package.get('scripts', {})
    dependencies = set()
    for name in ('dependencies', 'devDependencies', 'optionalDependencies'):
        if isinstance(package.get(name), dict):
            dependencies.update(package[name])
    labels = {'test': ('Vorhandene JavaScript-Tests', 'tests'),
              'lint': ('JavaScript-Lintprüfung', 'lint'),
              'typecheck': ('TypeScript-Typprüfung', 'build'),
              'build': ('Lokaler JavaScript-Build', 'build')}
    for script, (label, kind) in labels.items():
        if script not in scripts:
            continue
        if any(name in scripts for name in ('pre' + script, 'post' + script)):
            notes.append('npm-Skript ' + script + ' besitzt Lifecycle-Hooks; keine automatische Planung.')
            continue
        runner = _npm_runner(script, scripts[script], dependencies)
        if runner is None:
            notes.append('npm-Skript ' + script + ' ist kein eindeutig einmaliger lokaler Prüfaufruf; gezielten Befehl wählen.')
            continue
        checks.append({'command': 'npm run ' + script, 'label': label, 'kind': kind, 'runner': runner})
    return [path for path in files if re.search(r'(?:^|/|\.)(?:test|spec)[^/]*\.(?:[cm]?js|jsx|tsx?|mts|cts)$', path)
            or re.search(r'\.(?:test|spec)\.(?:[cm]?js|jsx|tsx?|mts|cts)$', path)]


def plan_project_checks(workspace, changed_paths=()):
    """Return deterministic checks and limitations, never execute or install.

    ``behavior_tests`` means a real test-run command was planned, not that any
    tests ran or passed. In particular empty, skipped and failed test output
    still needs to be rejected by the caller.
    """
    root = Path(workspace).resolve()
    checks, notes = [], []
    files, truncated = _scan(root)
    if not root.is_dir():
        return {'checks': [], 'notes': ['Projektordner fehlt; keine Prüfung geplant.'],
                'behavior_tests': False, 'test_files': [], 'truncated': False}
    changed = []
    for raw in changed_paths:
        if not isinstance(raw, str):
            continue
        normalized = raw.replace('\\', '/')
        if normalized in files and normalized not in changed:
            changed.append(normalized)
    tests = _python_checks(root, files, changed, checks, notes)
    tests += _javascript_checks(root, files, checks, notes)
    if len(checks) > _MAX_CHECKS:
        # Real tests have priority over fallback/static checks in mixed projects.
        checks.sort(key=lambda check: check['kind'] != 'tests')
        checks = checks[:_MAX_CHECKS]
        truncated = True
        notes.append('Prüfplan auf sechs Befehle begrenzt; weitere Prüfungen müssen gezielt ergänzt werden.')
    if truncated:
        notes.append('Projektinventar ist begrenzt; nicht alle Dateien wurden berücksichtigt.')
    if not checks:
        notes.append('Keine verlässlich automatisch planbare Prüfung gefunden; projektspezifische Tests wählen.')
    return {'checks': checks, 'notes': notes, 'behavior_tests': any(check['kind'] == 'tests' for check in checks),
            'test_files': sorted(set(tests))[:120], 'truncated': truncated}
