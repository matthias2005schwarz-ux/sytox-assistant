"""Bounded persistent code-project index; no raw source or secrets saved.

Indexes live in SYTOX's local application data, not inside the user's project.
Metadata is refreshed explicitly or when a new index is requested. The model
must still read the real source before editing.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .project_inspect import (
    _walk_files, _safe_filename, LANGUAGES, ENTRY_NAMES, TEXT_SUFFIXES,
)
from .storage import default_data_dir

MAX_FILES = 600
MAX_SYMBOLS = 32
MAX_READ_BYTES = 250_000
SYMBOL_RE = re.compile(
    r"^\s*(?:(?:export|public|private|protected|static|async|final|func|fn|fun)\s+)*"
    r"(?:class|interface|struct|enum|function|def|trait|impl|type)\s+"
    r"([A-Za-z_][A-Za-z_0-9]*)",
    re.MULTILINE,
)


def _index_path(workspace: str | Path, data_dir: Path | None = None) -> Path:
    root = Path(workspace).expanduser().resolve()
    token = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:24]
    base = data_dir if data_dir is not None else default_data_dir()
    return Path(base) / "project_indexes" / (token + ".json")


def _symbol_names(path: Path, content: str) -> list[str]:
    if path.suffix.lower() in (".py", ".pyi"):
        try:
            tree = ast.parse(content)
            result = []
            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    result.append(node.name)
            return result[:MAX_SYMBOLS]
        except SyntaxError:
            return []
    return list(dict.fromkeys(SYMBOL_RE.findall(content)))[:MAX_SYMBOLS]


def _read_index(workspace: str | Path, data_dir: Path | None = None) -> dict:
    path = _index_path(workspace, data_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            return {}
        return payload
    except (OSError, ValueError):
        return {}


def update_project_memory(workspace: str | Path, *, data_dir: Path | None = None) -> str:
    """Rebuild a deterministic bounded index without saving code contents."""
    root = Path(workspace).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Projektordner existiert nicht.")
    previous = _read_index(root, data_dir)
    cached = previous.get("files", {}) if isinstance(previous.get("files"), dict) else {}
    files = {}
    scanned = 0
    for path in _walk_files(root, max_files=MAX_FILES, max_dirs=150):
        if (path.suffix.lower() not in TEXT_SUFFIXES or
                not _safe_filename(path.name) or not path.is_file()):
            continue
        try:
            stat = path.stat()
            if stat.st_size > MAX_READ_BYTES:
                continue
            rel = path.relative_to(root).as_posix()
            if rel.startswith(".."):
                continue
            old = cached.get(rel, {})
            if (isinstance(old, dict) and old.get("size") == stat.st_size and
                    old.get("mtime_ns") == stat.st_mtime_ns):
                files[rel] = old
                continue
            raw = path.read_bytes()
            content = raw.decode("utf-8", errors="replace")
            files[rel] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "language": LANGUAGES.get(path.suffix.lower(), "Config/Text"),
                "entry": path.name.lower() in ENTRY_NAMES,
                "symbols": _symbol_names(path, content),
            }
            scanned += 1
        except (OSError, UnicodeError, ValueError):
            continue
    index = {
        "version": 1,
        "project_name": root.name[:100],
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "files": files,
    }
    target = _index_path(root, data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, prefix=".project_",
                                     suffix=".tmp", encoding="utf-8", delete=False) as f:
        temp_path = Path(f.name)
        json.dump(index, f, ensure_ascii=False, indent=2)
    try:
        temp_path.replace(target)
    finally:
        temp_path.unlink(missing_ok=True)
    return (f"Projektgedächtnis aktualisiert: {len(files)} Datei-Metadaten, "
            f"{scanned} neu eingelesen. Nur Pfade, Symbole, Prüfsummen gespeichert, "
            "kein Quelltext. Bei großen Projekten nur Teilausschnitt.")


def lookup_project_memory(workspace: str | Path, query: str,
                          *, data_dir: Path | None = None) -> str:
    """Return ranked file-path and symbol hints, refusing to disguise stale data."""
    root = Path(workspace).expanduser().resolve()
    index = _read_index(root, data_dir)
    if not index:
        return "Kein Projektindex vorhanden. Zuerst project_memory_update ausführen."
    needle = re.findall(r"[A-Za-z0-9_]{2,}", str(query or "").casefold())[:10]
    matches = []
    files = index.get("files", {})
    for rel, meta in files.items():
        path = root / rel
        try:
            st = path.stat()
            stale = st.st_size != meta["size"] or st.st_mtime_ns != meta["mtime_ns"]
        except OSError:
            stale = True
        symbols = meta.get("symbols", [])
        hay = (rel + " " + " ".join(symbols)).casefold()
        score = sum(2 if word in rel.casefold() else 1 for word in needle if word in hay)
        if not needle or score or meta.get("entry"):
            matches.append((score, rel, meta, stale))
    matches.sort(key=lambda x: (-x[0], x[1]))
    if not matches:
        return "Keine passenden Projektdateien im lokalen Index gefunden."
    output = [f"Projektindex: {index.get('project_name','Projekt')} "
              f"({len(files)} Dateien, Indexstand {index.get('updated_at','?')})"]
    for _score, rel, meta, stale in matches[:20]:
        names = ", ".join(str(x) for x in meta.get("symbols", [])[:12])
        output.append(f"{rel} [{meta.get('language','?')}]"
                      + (" [VERALTET: erneut indexieren]" if stale else "")
                      + (f" – Symbole: {names}" if names else ""))
    output.append("Nur Hinweise: vor Änderungen immer die tatsächlichen Dateien lesen.")
    return "\n".join(output)[:6000]
