"""Explicit per-file recovery snapshots for autonomous coding.

A snapshot never modifies project files. Restoration requires user approval
from the Toolkit, and every target is revalidated. Missing/new files are not
silently deleted. Backups live outside the project in private app data.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from .storage import default_data_dir

MAX_FILES = 16
MAX_BYTES = 20 * 1024 * 1024


def _root(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve()


def _storage(root: Path, data_dir: Path | None = None) -> Path:
    folder = data_dir if data_dir is not None else default_data_dir()
    hashed = hashlib.sha256(os.fsencode(str(root))).hexdigest()[:24]
    return Path(folder) / "recovery" / hashed


def _safe_path(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ValueError("Nur relative Dateipfade sind erlaubt.")
    if ".." in Path(raw).parts:
        raise PermissionError("Pfad verlässt den Projektordner.")
    path = root / raw
    if path.is_symlink():
        raise PermissionError("Snapshot über symbolische Verknüpfungen gesperrt.")
    resolved = path.resolve()
    if resolved != root and root not in resolved.parents:
        raise PermissionError("Pfad verlässt den Projektordner.")
    return resolved


def create_snapshot(workspace: str | Path, paths: list[str], *,
                    data_dir: Path | None = None) -> tuple[str, list[str]]:
    root = _root(workspace)
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError("Snapshot benötigt 1 bis 16 Dateien.")
    selected = []
    seen = set()
    total = 0
    for raw in paths:
        path = _safe_path(root, raw)
        if path in seen or not path.is_file():
            raise ValueError("Doppelte oder nicht vorhandene Datei.")
        seen.add(path)
        total += path.stat().st_size
        if total > MAX_BYTES:
            raise ValueError("Dateien zu groß für einen Snapshot.")
        selected.append(path)
    sid = uuid.uuid4().hex
    folder = _storage(root, data_dir) / sid
    folder.mkdir(parents=True)
    manifest = {"version": 1, "workspace": str(root), "files": []}
    try:
        for i, path in enumerate(selected):
            original = path.read_bytes()
            backup = folder / f"{i:02d}.bak"
            backup.write_bytes(original)
            manifest["files"].append({
                "path": path.relative_to(root).as_posix(),
                "backup": backup.name,
                "sha256": hashlib.sha256(original).hexdigest(),
            })
        (folder / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return sid, [x["path"] for x in manifest["files"]]


def _manifest(workspace: str | Path, snapshot_id: str,
              data_dir: Path | None = None) -> tuple[Path, dict]:
    root = _root(workspace)
    if not isinstance(snapshot_id, str) or len(snapshot_id) != 32 or not all(
            c in "0123456789abcdef" for c in snapshot_id):
        raise ValueError("Ungültige Snapshot-ID.")
    folder = _storage(root, data_dir) / snapshot_id
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or manifest.get("workspace") != str(root):
        raise PermissionError("Snapshot gehört zu einem anderen Projekt.")
    if not isinstance(manifest.get("files"), list) or not 1 <= len(manifest["files"]) <= MAX_FILES:
        raise ValueError("Ungültiges Snapshot-Manifest.")
    return folder, manifest


def snapshot_paths(workspace: str | Path, snapshot_id: str,
                   *, data_dir: Path | None = None) -> list[str]:
    _, manifest = _manifest(workspace, snapshot_id, data_dir)
    return [str(x["path"]) for x in manifest["files"]]


def restore_snapshot(workspace: str | Path, snapshot_id: str, *,
                     data_dir: Path | None = None) -> list[str]:
    """Restore snapshots of existing files; preserve a second pre-restore copy."""
    root = _root(workspace)
    folder, manifest = _manifest(root, snapshot_id, data_dir)
    prepared = []
    total = 0
    for entry in manifest["files"]:
        target = _safe_path(root, entry["path"])
        if not target.is_file() or target.is_symlink():
            raise ValueError("Wiederherstellung abgebrochen: Datei fehlt oder ist ein Link.")
        backup_name = entry["backup"]
        if not isinstance(backup_name, str) or not backup_name.endswith(".bak") or Path(backup_name).name != backup_name:
            raise ValueError("Unsicheres Backup im Snapshot.")
        original = (folder / backup_name).read_bytes()
        total += len(original)
        if total > MAX_BYTES or hashlib.sha256(original).hexdigest() != entry["sha256"]:
            raise ValueError("Snapshot beschädigt oder zu groß.")
        prepared.append((target, original))
    current = [(p, p.read_bytes()) for p, _ in prepared]
    # Keep pre-restore state even if a later restore or tool operation fails.
    safeguard = folder / ("pre_restore_" + uuid.uuid4().hex)
    safeguard.mkdir()
    for i, (_, data) in enumerate(current):
        (safeguard / f"{i:02d}.bak").write_bytes(data)
    written = []
    try:
        for target, original in prepared:
            fd, name = tempfile.mkstemp(dir=target.parent, prefix=".sytox_restore_")
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(original)
                Path(name).replace(target)
            finally:
                Path(name).unlink(missing_ok=True)
            written.append(target)
    except Exception:
        for target, data in current:
            if target in written:
                target.write_bytes(data)
        raise
    return [p.relative_to(root).as_posix() for p, _ in prepared]
