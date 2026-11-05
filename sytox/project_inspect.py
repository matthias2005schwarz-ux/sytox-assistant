"""Bounded, read-only project navigation for a local coding agent.

No dependency folders, symlink traversal, or automatic file writes.
"""

from __future__ import annotations

from collections import Counter
from itertools import islice
import os
from pathlib import Path


SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "bower_components", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".idea", ".next", ".nuxt",
    "dist", "build", "target", "coverage", "site-packages",
    "vendor", "bin", "obj", ".gradle",
})
SKIP_FILE_NAMES = frozenset({
    "id_rsa", "id_ed25519", "credentials.json", "secrets.json",
    "secrets.yaml", "secrets.yml", "token.json", ".npmrc", ".pypirc",
})
TEXT_SUFFIXES = frozenset({
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt",
    ".go", ".rs", ".cs", ".c", ".h", ".cpp", ".hpp", ".cc",
    ".php", ".lua", ".html", ".css", ".scss", ".sql", ".json",
    ".toml", ".ini", ".cfg", ".md", ".txt", ".yml", ".yaml",
    ".xml", ".sh", ".ps1", ".bat", ".cmd", ".gradle", ".properties",
})
TEXT_NAMES = frozenset({
    "dockerfile", "makefile", "cmakelists.txt", "gemfile", "procfile",
    "requirements.txt", "gradlew", "cargo.lock", ".gitignore",
})
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript", ".tsx": "TypeScript", ".java": "Java",
    ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".cs": "C#",
    ".c": "C", ".cpp": "C++", ".cc": "C++", ".php": "PHP",
    ".lua": "Lua",
}
ENTRY_NAMES = frozenset({
    "main.py", "app.py", "main.js", "index.js", "main.ts",
    "package.json", "pyproject.toml", "requirements.txt", "go.mod",
    "cargo.toml", "pom.xml", "build.gradle", "cmakelists.txt",
    "makefile", "main.rs", "program.cs", "main.go",
})


def _scope(workspace: str | Path, path: str = ".") -> tuple[Path, Path]:
    root = Path(workspace).expanduser().resolve()
    target = (root / str(path or ".")).resolve()
    if target != root and root not in target.parents:
        raise PermissionError("Zugriff außerhalb des Projektordners ist gesperrt.")
    return root, target


def _safe_filename(name: str) -> bool:
    lower = name.lower()
    if lower in SKIP_FILE_NAMES or lower.startswith(".env"):
        return False
    if lower.endswith((".pem", ".p12", ".pfx", ".key", ".keystore")):
        return False
    return not (name.startswith(".") and lower not in TEXT_NAMES)


def _walk_files(start: Path, max_files: int = 2400, max_dirs: int = 300):
    """Yield deterministic candidates, with a strict traversal budget."""
    scanned_files = scanned_dirs = 0
    for directory, dirs, files in os.walk(start, followlinks=False):
        scanned_dirs += 1
        if scanned_dirs > max_dirs:
            return
        dirs[:] = sorted(d for d in dirs
                         if d not in SKIP_DIRS
                         and not d.startswith(".")
                         and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            scanned_files += 1
            if scanned_files > max_files:
                return
            path = Path(directory) / name
            if path.is_symlink() or not _safe_filename(name):
                continue
            yield path


def project_overview(workspace: str | Path, path: str = ".") -> str:
    """List a representative source map without reading source content."""
    root, start = _scope(workspace, path)
    if not start.is_dir():
        return "Kein Verzeichnis."
    paths = list(_walk_files(start))
    languages = Counter(LANGUAGES[p.suffix.lower()] for p in paths
                        if p.suffix.lower() in LANGUAGES)
    relative = [p.relative_to(root).as_posix() for p in paths]
    entries = [p for p in relative if Path(p).name.lower() in ENTRY_NAMES][:30]
    tests = [p for p in relative if Path(p).name.lower().startswith("test_")
             or "tests" in Path(p).parts][:25]
    result = [
        f"Projektübersicht: {start.relative_to(root).as_posix() or '.'}",
        f"Erfasste Dateien: {len(paths)} (maximal 2400; große Projekte nur teilweise erfasst)",
        "Sprachen: " + (", ".join(f"{name} ({count})" for name, count
                                   in languages.most_common()) or "keine erkannt"),
        "Einstiegspunkte/Konfiguration: " + (", ".join(entries) or "keine erkannt"),
        "Testdateien: " + (", ".join(tests) or "keine erkannt"),
        "Dateien (Auszug):",
    ]
    result.extend(relative[:130])
    if len(relative) > 130:
        result.append(f"... {len(relative) - 130} weitere erfasste Dateien.")
    return "\n".join(result)[:16000]


def search_project(workspace: str | Path, query: str, path: str = ".") -> str:
    """Literal case-insensitive search in small source files; no regex or shell."""
    if not isinstance(query, str) or not 2 <= len(query.strip()) <= 120:
        raise ValueError("Suchtext muss 2 bis 120 Zeichen enthalten.")
    root, start = _scope(workspace, path)
    if not start.is_dir():
        return "Kein Verzeichnis."
    needle = query.strip().casefold()
    found: list[str] = []
    scanned = 0
    for candidate in _walk_files(start):
        if len(found) >= 40:
            break
        if (candidate.suffix.lower() not in TEXT_SUFFIXES
                and candidate.name.lower() not in TEXT_NAMES):
            continue
        try:
            if candidate.stat().st_size > 250_000:
                continue
            scanned += 1
            with candidate.open("r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    at = line.casefold().find(needle)
                    if at < 0:
                        continue
                    # Return local context, not huge lines or complete files.
                    excerpt = line[max(0, at - 85):at + len(query) + 85].strip()
                    excerpt = excerpt.replace("\t", " ")
                    rel = candidate.relative_to(root).as_posix()
                    found.append(f"{rel}:{number}: {excerpt[:220]}")
                    if len(found) >= 40:
                        break
        except (OSError, UnicodeError):
            continue
    prefix = f"Codesuche: {query.strip()!r} in {scanned} Dateien; "
    if not found:
        return prefix + "keine Treffer im begrenzten Suchbereich."
    return (prefix + f"{len(found)} Treffer (maximal 40):\n"
            + "\n".join(found))[:17000]


def read_project_lines(workspace: str | Path, path: str,
                       start_line: int = 1, end_line: int = 100) -> str:
    """Read an explicit line window in a workspace file (without execution)."""
    root, target = _scope(workspace, path)
    if not target.is_file():
        raise ValueError("Keine Datei.")
    if target.stat().st_size > 2_000_000:
        raise ValueError("Datei zu groß (maximal 2 MB).")
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        raise ValueError("Zeilennummern müssen Ganzzahlen sein.")
    if start_line < 1 or end_line < start_line or end_line - start_line >= 180:
        raise ValueError("Bitte 1 bis 180 aufeinanderfolgende Zeilen angeben.")
    if end_line > 1_000_000:
        raise ValueError("Zeilenbereich zu groß.")
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        lines = list(islice(handle, start_line - 1, end_line))
    if not lines:
        return f"{target.relative_to(root).as_posix()}: Keine Zeilen in diesem Bereich."
    content = "\n".join(f"{start_line + i}: {line.rstrip()[:420]}"
                        for i, line in enumerate(lines))
    return (f"{target.relative_to(root).as_posix()} – Zeilen "
            f"{start_line}–{start_line + len(lines) - 1}:\n{content}")[:17000]
