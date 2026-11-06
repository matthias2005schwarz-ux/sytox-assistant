"""Read-only, scoped regression-test suggestions after source edits.

No test is executed here. This module merely identifies real test files and
conventional project-level commands for the agent to consider. Execution still
goes through Toolkit.run_command with its existing approval/safety checks.
"""
from __future__ import annotations

import re
from pathlib import Path

_SOURCE_SUFFIX = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".cs"}
_SKIP = frozenset({"node_modules", ".git", ".venv", "venv", "dist", "build",
                   "__pycache__", ".next", "target", "bin", "obj"})


def _check_project_file(root: Path, raw: str) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    current = root
    for part in relative.parts:
        if part in _SKIP or part.startswith("."):
            return None
        current = current / part
        if current.is_symlink():
            return None
    result = current.resolve()
    if root not in result.parents or not result.is_file():
        return None
    return result


def plan_regression_tests(workspace: str | Path, changed_files: list[str]) -> str:
    """Produce bounded, scoped test suggestions without claiming validation."""
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        return "Kein gültiger Projektordner. Zuerst Projektstruktur prüfen."
    if not isinstance(changed_files, (set, tuple, list)):
        return "Keine gültigen geänderten Dateien bekannt."
    files = []
    for name in sorted(changed_files)[:32]:
        path = _check_project_file(root, name)
        if path is not None and path.suffix.lower() in _SOURCE_SUFFIX:
            files.append(path)
    if not files:
        return "Keine existierenden Quellcodedateien als geändert bekannt."
    patterns = {}
    for src in files:
        suffix = src.suffix.lower()
        stem = src.stem
        if suffix in (".py", ".pyi"):
            names = [f"test_{stem}.py", f"{stem}_test.py"]
            locations = [root / "tests", src.parent, src.parent / "tests"]
            key = "Python"
        elif suffix in (".js", ".jsx", ".ts", ".tsx"):
            names = [f"{stem}.test{suffix}", f"{stem}.spec{suffix}",
                     f"{stem}.test.ts", f"{stem}.spec.ts"]
            locations = [src.parent, src.parent / "__tests__", root / "tests"]
            key = "JavaScript/TypeScript"
        else:
            continue
        for folder in locations:
            if folder.is_symlink() or not folder.is_dir():
                continue
            for candidate in names:
                maybe = folder / candidate
                if maybe.is_symlink() or not maybe.is_file():
                    continue
                try:
                    rel = maybe.resolve().relative_to(root).as_posix()
                except ValueError:
                    continue
                patterns.setdefault(key, set()).add(rel)
    lines = ["Gezielte Regressionstest-Hinweise (keine Tests ausgeführt):"]
    if patterns.get("Python"):
        paths = sorted(patterns["Python"])[:8]
        lines.append("Python-Tests: " + ", ".join(paths))
        # Use only unquoted safe file names in command suggestions to avoid
        # accidentally turning filenames into shell arguments.
        if all(re.fullmatch(r"[A-Za-z0-9_./-]+", p) for p in paths):
            lines.append("Möglicher Testbefehl: python -m pytest " + " ".join(paths))
    if patterns.get("JavaScript/TypeScript"):
        lines.append("JS/TS-Tests: " + ", ".join(sorted(
            patterns["JavaScript/TypeScript"])[:8]))
        lines.append("Den im Projekt konfigurierten Test-Runner prüfen; keine "
                     "Paketinstallation oder Ausführung automatisch.")
    suffixes = {p.suffix.lower() for p in files}
    if ".py" in suffixes or ".pyi" in suffixes:
        paths = sorted(p.relative_to(root).as_posix() for p in files
                       if p.suffix.lower() == ".py")[:8]
        if paths and all(re.fullmatch(r"[A-Za-z0-9_./-]+", p) for p in paths):
            lines.append("Zusätzliche Syntaxprüfung: python -m compileall " + " ".join(paths))
    if suffixes & {".go"} and (root / "go.mod").is_file():
        lines.append("Go-Projekt: go test ./... (nach Freigabe)")
    if suffixes & {".rs"} and (root / "Cargo.toml").is_file():
        lines.append("Rust-Projekt: cargo test (nach Freigabe)")
    if suffixes & {".cs"} and any(root.glob("*.csproj")):
        lines.append("C#-Projekt: dotnet test (nach Freigabe)")
    lines.append("Prüfe den aktuellen Testumfang; eine erfolgreiche Syntaxprüfung "
                 "beweist keine fehlerfreie Laufzeitfunktion. Nach Änderungen "
                 "muss der passende Test tatsächlich ausgeführt werden.")
    return "\n".join(lines)[:2400]
