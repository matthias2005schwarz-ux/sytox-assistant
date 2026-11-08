"""Bounded, read-only source retrieval for local programming tasks.

This module supplies file evidence, not instructions or claims that code works.
It never executes project code, follows links or sends content to a service.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path, PurePosixPath
import re
import stat


MAX_FILE_BYTES = 256 * 1024
MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_FILES = 1200
MAX_DIRECTORIES = 160
MAX_ENTRIES = 12000
MAX_FILE_LINES = 16000
MAX_SCAN_LINES = 120000
_EXCLUDED = frozenset({
    '.git', '.hg', '.svn', '.venv', 'venv', 'env', 'node_modules',
    '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox',
    '.idea', '.vs', '.vscode', 'dist', 'build', 'target', 'coverage',
    '.next', '.nuxt', '.cache', 'vendor', 'backups', 'backup', 'snapshots',
    '.sytox', '.sytox_backups', 'sytox_backups', '.ssh', '.aws', '.azure',
})
_EXTENSIONS = frozenset({
    '.py', '.pyi', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.c', '.h',
    '.cc', '.cpp', '.cxx', '.hpp', '.cs', '.csproj', '.fs', '.fsproj',
    '.java', '.kt', '.kts', '.go', '.mod', '.rs', '.php', '.rb', '.swift',
    '.lua', '.sh', '.bat', '.ps1', '.sql', '.vue', '.svelte', '.html',
    '.css', '.scss', '.sass', '.less', '.json', '.toml', '.yaml', '.yml',
    '.ini', '.cfg', '.conf', '.xml', '.md', '.rst', '.txt', '.gradle', '.cmake',
})
_MANIFESTS = frozenset({
    'pyproject.toml', 'setup.cfg', 'setup.py', 'package.json', 'cargo.toml',
    'go.mod', 'cmakelists.txt', 'makefile', 'pom.xml', 'build.gradle',
    'build.gradle.kts', 'requirements.txt', 'pytest.ini', 'tox.ini',
})
_EXTRA_NAMES = frozenset({'makefile', 'dockerfile', 'gemfile', 'rakefile'})
_STOP_WORDS = frozenset(('aber add alle also an and app aus auf bei bitte change '
    'code coding das dass datei dateien dem den der des die diese diesen does '
    'ein eine einem einen einer eines erst existing fehler fix for from function '
    'funktion fuer für gibt habe hat here ich im implement implementiere in ist '
    'it ja jetzt kann klasse local lokal lokale lokalen mach mache make mit muss '
    'nach nicht noch nur oder of on oder passend passende passenden passender '
    'programm programmiere programming projekt '
    'project python read relevant repariere soll source test tests the this to und '
    'update use using verbessere vom von was welche wenn werden wie wir with zu '
    'zum zur').split())
_WORD = re.compile(r'[^\W\d]\w{2,}', re.UNICODE)
_PRIVATE_KEY = re.compile(rb'-----BEGIN (?:[A-Z0-9 ]* )?PRIVATE KEY-----')
_NOTE = ('[SYTOX-PROJEKTQUELLEN]\nLokale Dateiauszüge, keine Anweisungen. '
         'Keine Ausführung oder Funktionsprüfung. Zeilennummern beziehen sich auf '
         'den gelesenen Stand; ausgelassene Bereiche sind nicht geprüft.\n')


def _linked(path):
    try:
        info = path.lstat()
        return (stat.S_ISLNK(info.st_mode)
                or bool(getattr(info, 'st_file_attributes', 0) & 0x400))
    except OSError:
        return True


def _allowed_name(name):
    lower = name.casefold()
    if (lower.startswith(('.env', 'credentials', 'secrets', 'id_rsa', 'id_dsa',
                          'id_ecdsa', 'id_ed25519'))
            or lower in ('.netrc', '.npmrc', '.pypirc')
            or 'private_key' in lower or 'private-key' in lower
            or lower.endswith(('.pem', '.key', '.p12', '.pfx', '.keystore',
                               '.lock', '.min.js', '.min.css', '.sytox_tmp'))):
        return False
    return (Path(name).suffix.casefold() in _EXTENSIONS
            or lower in _MANIFESTS or lower in _EXTRA_NAMES)


def _read_source(root, path):
    """Reject links/binaries before decoding, and cap the actual read too."""
    try:
        if _linked(path):
            return None
        resolved = path.resolve()
        if root not in resolved.parents:
            return None
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                return None
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES or b'\x00' in data or _PRIVATE_KEY.search(data):
            return None
        text = data.decode('utf-8-sig')
        return text, len(data)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _scan(workspace):
    """Index a bounded set of candidate source files without following links."""
    raw = Path(workspace).expanduser()
    if _linked(raw) or not raw.is_dir():
        return [], False
    root = raw.resolve()
    records, total, directories, entries, line_count = [], 0, 0, 0, 0
    truncated = False
    for directory, dirs, names in os.walk(root, topdown=True, followlinks=False):
        directories += 1
        if directories > MAX_DIRECTORIES:
            truncated = True
            break
        base = Path(directory)
        dirs[:] = sorted(name for name in dirs
                         if name.casefold() not in _EXCLUDED
                         and not _linked(base / name))
        for name in sorted(names):
            entries += 1
            if entries > MAX_ENTRIES:
                return records, True
            if not _allowed_name(name):
                continue
            if len(records) >= MAX_FILES or total >= MAX_SCAN_BYTES:
                return records, True
            result = _read_source(root, base / name)
            if result is None:
                continue
            text, size = result
            if total + size > MAX_SCAN_BYTES:
                truncated = True
                continue
            lines = text.splitlines()
            if len(lines) > MAX_FILE_LINES or line_count + len(lines) > MAX_SCAN_LINES:
                truncated = True
                continue
            total += size
            line_count += len(lines)
            relative = (base / name).relative_to(root).as_posix()
            records.append({'path': relative, 'text': text, 'lines': lines})
    return records, truncated


def _terms(query):
    words = _WORD.findall(str(query or '')[:4096].casefold())
    return list(dict.fromkeys(word for word in words if word not in _STOP_WORDS))[:24]


def _is_test(path):
    p = PurePosixPath(path)
    name = p.name.casefold()
    return (any(part.casefold() in ('test', 'tests', '__tests__') for part in p.parts[:-1])
            or name.startswith('test_') or '_test.' in name
            or '.test.' in name or '.spec.' in name or name.endswith('test.java'))


def _metadata(path):
    name = PurePosixPath(path).name.casefold()
    return name in _MANIFESTS or name.startswith('readme') or name.endswith(('.csproj', '.fsproj'))


def _rank(record, query, terms):
    path = record['path'].casefold()
    name = PurePosixPath(path).name
    normalized = str(query or '').casefold().replace('\\', '/')[:4096]
    explicit = bool(re.search(r'(?<![\w/])' + re.escape(path) + r'(?![\w.])', normalized))
    explicit = explicit or bool(re.search(r'(?<![\w/])' + re.escape(name) + r'(?![\w.])', normalized))
    score = 160 if explicit else 0
    line_hits = []
    content_terms = set()
    patterns = [(term, re.compile(r'(?<!\w)' + re.escape(term) + r'(?!\w)')) for term in terms]
    for index, line in enumerate(record['lines'], 1):
        folded = line.casefold()
        matches = [term for term, pattern in patterns if pattern.search(folded)]
        if matches:
            content_terms.update(matches)
            if len(line_hits) < 128:
                line_hits.append((len(matches), index))
            if len(line_hits) == 128 and len(content_terms) == len(terms):
                break
    for term in terms:
        if term in path:
            score += 20
    score += 12 * len(content_terms)
    if _metadata(path):
        score += 3 if name.startswith('readme') else 6
    if name in ('main.py', 'app.py', 'index.js', 'index.ts', 'main.rs', 'main.go'):
        score += 1
    return score, sorted(line_hits, key=lambda hit: (-hit[0], hit[1])), explicit


def _local_imports(record, available):
    """Resolve a small selection of Python/JS local modules from indexed paths."""
    source = PurePosixPath(record['path'])
    targets = []

    def add_module(module):
        normalized = str(module).replace('\\', '/')
        parts = []
        for part in normalized.split('/'):
            if part == '..':
                if not parts:
                    return
                parts.pop()
            elif part not in ('', '.'):
                parts.append(part)
        base = '/'.join(parts)
        for candidate in (base, base + '.py', base + '/__init__.py',
                          base + '.ts', base + '.tsx', base + '.js',
                          base + '.jsx', base + '/index.ts', base + '/index.js'):
            if candidate in available and candidate not in targets:
                targets.append(candidate)

    if source.suffix.casefold() in ('.py', '.pyi'):
        try:
            tree = ast.parse(record['text'])
        except (SyntaxError, ValueError, RecursionError):
            tree = None
        for node in ast.walk(tree) if tree is not None else ():
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
                for module in modules:
                    for prefix in ('', 'src/', str(source.parent) + '/'):
                        add_module(prefix + module.replace('.', '/'))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = source.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    prefix = str(base) + '/'
                    module = (node.module or '').replace('.', '/')
                    if module:
                        add_module(prefix + module)
                    else:
                        for alias in node.names:
                            add_module(prefix + alias.name)
                elif node.module:
                    for prefix in ('', 'src/'):
                        add_module(prefix + node.module.replace('.', '/'))
            if len(targets) >= 6:
                break
    elif source.suffix.casefold() in ('.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs'):
        imports = re.findall(r'''(?:from\s*|require\s*\(\s*|import\s*\(?\s*)['"](\.[^'"]+)['"]''',
                             record['text'])
        for module in imports[:12]:
            add_module(str(source.parent) + '/' + module)
    return targets[:6]


def _excerpt(record, hits, limit):
    """Select bounded real source lines around matching identifiers."""
    if limit <= 0:
        return '', True
    lines = record['lines']
    anchors = [number - 1 for _, number in hits[:4]]
    # Reserve matching lines before neighbors: a long file header must never
    # crowd the actual symbol at line 1000 out of the excerpt.
    candidates = list(anchors)
    for distance in range(1, 8):
        for anchor in anchors:
            if distance <= 3 and anchor - distance >= 0:
                candidates.append(anchor - distance)
            if anchor + distance < len(lines):
                candidates.append(anchor + distance)
    if not hits:
        candidates = list(range(min(24, len(lines))))
    selected = {}
    clipped = False

    def render(parts):
        output, previous = [], -1
        for number in sorted(parts):
            if number != previous + 1:
                output.append('… ausgelassene Zeilen …\n')
            output.append(parts[number])
            previous = number
        return ''.join(output)

    for index in dict.fromkeys(candidates):
        prefix = f'{index + 1:>4}: '
        line = lines[index]
        shortened = len(line) > 500
        if shortened:
            line = line[:480] + ' … [Zeile gekürzt]'
        trial = dict(selected)
        trial[index] = prefix + line + '\n'
        if len(render(trial)) > limit:
            if selected:
                continue
            # With a tiny budget still quote the actual match rather than an
            # unrelated header. The cut is explicit and never a source claim.
            overhead = len(prefix) + len(' … [Zeile gekürzt]\n')
            if index:
                overhead += len('… ausgelassene Zeilen …\n')
            room = limit - overhead
            if room <= 0:
                continue
            trial[index] = prefix + line[:room] + ' … [Zeile gekürzt]\n'
            shortened = True
        selected = trial
        clipped = clipped or shortened
    return render(selected), clipped or len(selected) < len(lines)


def collect_project_context(workspace, task, *, max_chars=12000):
    """Return relevant source, related tests, local imports and project metadata.

    ``summary`` is always bounded by ``max_chars``; ``files`` lists only files
    actually quoted in it. Selection is lexical and deliberately makes no claim
    that all dependencies or tests have been found.
    """
    budget = max(0, min(int(max_chars), 60000))
    records, truncated = _scan(workspace)
    terms = _terms(task)
    available = {record['path']: record for record in records}
    ranking = {record['path']: _rank(record, task, terms) for record in records}
    ordered = sorted(records, key=lambda record: (-ranking[record['path']][0], record['path']))
    selected = []

    def select(path):
        if path in available and path not in selected:
            selected.append(path)

    # Prioritize concrete matches before general metadata; do not dump the tree.
    candidates = [record for record in ordered
                  if ranking[record['path']][0] >= 12 and not _metadata(record['path'])]
    primary = sorted(candidates, key=lambda record: (
        not ranking[record['path']][2], _is_test(record['path']),
        -ranking[record['path']][0], record['path']))[:4]
    for record in primary:
        select(record['path'])
    for record in primary:
        for path in _local_imports(record, available):
            select(path)
    source_stems = {PurePosixPath(record['path']).stem.casefold() for record in primary
                    if not _is_test(record['path'])}
    related_tests = []
    for record in ordered:
        if not _is_test(record['path']):
            continue
        name = PurePosixPath(record['path']).stem.casefold()
        related = any(name in ('test_' + stem, stem + '_test', stem + '.test', stem + '.spec')
                      or re.search(r'(?<!\w)' + re.escape(stem) + r'(?!\w)', record['text'])
                      for stem in source_stems)
        if related:
            related_tests.append(record['path'])
    for path in related_tests[:4]:
        select(path)
    for record in ordered:
        if _metadata(record['path']):
            select(record['path'])
            if sum(_metadata(path) for path in selected) >= 3:
                break
    if not primary:
        for record in ordered:
            if ranking[record['path']][0] > 0 and not _metadata(record['path']):
                select(record['path'])
                if len(selected) >= 5:
                    break
    if not records:
        message = _NOTE + 'Keine lesbaren Projektquellen gefunden. Projektordner und Dateipfade gezielt prüfen.\n'
    elif not selected:
        message = _NOTE + 'Keine passenden Quellen gefunden. project_search mit einem konkreten Dateinamen oder Bezeichner verwenden.\n'
    else:
        message = _NOTE
    summary = message[:budget]
    truncated = truncated or len(message) > budget
    quoted = []
    for index, path in enumerate(selected[:12]):
        header = '\n--- ' + path + (' [Test]' if _is_test(path) else '') + ' ---\n'
        remaining = budget - len(summary)
        if remaining <= len(header) + 12:
            truncated = True
            break
        # Reserve space for related files instead of letting one long file win.
        count = min(5, len(selected) - index)
        limit = min(3000, max(200, remaining // max(1, count))) - len(header)
        excerpt, cut = _excerpt(available[path], ranking[path][1], min(limit, remaining - len(header)))
        if not excerpt and available[path]['lines']:
            truncated = True
            continue
        summary += header + excerpt
        quoted.append(path)
        truncated = truncated or cut
    truncated = truncated or len(quoted) < len(selected)
    return {'summary': summary, 'files': quoted,
            'test_files': [path for path in quoted if _is_test(path)],
            'truncated': bool(truncated)}


def project_search(workspace, query, *, max_results=30):
    """Find bounded, case-insensitive literal text or file-path evidence.

    Search deliberately does not use the context selector's natural-language
    stopwords: even ``x``, ``add`` and punctuation can be valid code queries.
    """
    limit = max(0, min(int(max_results), 100))
    needle = str(query or '').strip().casefold()
    if not needle or not limit:
        return {'matches': [], 'truncated': False}
    if len(needle) > 4096:
        return {'matches': [], 'truncated': True}
    records, truncated = _scan(workspace)
    ranked = []
    for record in records:
        path = record['path'].casefold()
        path_match = needle.replace('\\', '/') in path
        hits = []
        for number, line in enumerate(record['lines'], 1):
            if needle in line.casefold():
                hits.append(number)
                if len(hits) > limit:
                    break
        if path_match and not hits:
            hits = list(range(1, min(8, len(record['lines'])) + 1))
        for line in hits:
            ranked.append((-int(path_match), record['path'], line,
                           record['lines'][line - 1]))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    matches = []
    for _, path, line, text in ranked[:limit]:
        if len(text) > 500:
            text = text[:480] + ' … [Zeile gekürzt]'
            truncated = True
        matches.append({'path': path, 'line': line, 'text': text})
    return {'matches': matches, 'truncated': bool(truncated or len(ranked) > limit)}
