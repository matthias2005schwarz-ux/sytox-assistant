"""Automatic source snapshots and gated rollback for user-owned projects.

Snapshots live outside the project. Reject links, oversize workspaces and
unsafe archive members. A restore requires explicit user confirmation and
saves a rollback snapshot of the current state first.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

MAX_FILES = 1500
MAX_BYTES = 120 * 1024 * 1024
MAX_FILE_BYTES = 24 * 1024 * 1024
RETAIN = 12
EXCLUDED = frozenset({
    '.git', '.hg', '.svn', '__pycache__', '.venv', 'venv', 'node_modules',
    '.mypy_cache', '.pytest_cache', '.tox', '.idea', 'dist', 'build',
})


class SnapshotError(RuntimeError):
    pass


def _safe_root(workspace, root):
    project = Path(workspace).expanduser().resolve()
    backups = Path(root).expanduser().resolve()
    if not project.is_dir():
        raise SnapshotError('Projektordner fehlt: kein Backup möglich.')
    if backups == project or project in backups.parents:
        raise SnapshotError('Backups müssen außerhalb des Projektordners liegen.')
    return project, backups


def _list_source_files(project):
    files, total = [], 0
    for directory, dirs, names in os.walk(project, topdown=True, followlinks=False):
        base = Path(directory)
        dirs[:] = sorted(
            name for name in dirs
            if name not in EXCLUDED and not (base / name).is_symlink()
        )
        for name in sorted(names):
            if name in EXCLUDED or name.endswith(('.sytox_tmp', '.pyc')):
                continue
            path = base / name
            if path.is_symlink():
                raise SnapshotError('Projekt enthält verlinkte Datei: ' + str(path))
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                raise SnapshotError('Projektdatei zu groß für sicheres Backup: ' + name)
            total += size
            files.append(path)
            if total > MAX_BYTES or len(files) > MAX_FILES:
                raise SnapshotError(
                    'Projekt zu groß für vollständiges Quellcode-Backup; '
                    'keine unbeaufsichtigte Änderung ohne Backup.'
                )
    return files


def create_snapshot(workspace, backup_root, label='before_edit', *, preserve=()):
    project, backups = _safe_root(workspace, backup_root)
    files = _list_source_files(project)
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
    name = f'{stamp}_{label}.zip'
    # Use OS-created temporary file to prevent collisions and partial backups.
    fd, tmp_name = tempfile.mkstemp(prefix='.sytox_backup_', suffix='.tmp', dir=backups)
    os.close(fd)
    tmp = Path(tmp_name)
    records = []
    try:
        with zipfile.ZipFile(tmp, 'w', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6) as archive:
            for path in files:
                relative = path.relative_to(project).as_posix()
                data = path.read_bytes()
                records.append({
                    'path': relative, 'sha256': hashlib.sha256(data).hexdigest(),
                    'size': len(data),
                })
                archive.writestr(relative, data)
            archive.writestr('SYTOX_SNAPSHOT_MANIFEST.json', json.dumps(
                {'format': 1, 'label': label, 'files': records},
                ensure_ascii=False
            ))
        target = backups / name
        tmp.replace(target)
        with zipfile.ZipFile(target) as verification:
            if verification.testzip() is not None:
                raise SnapshotError('Backup-ZIP ist beschädigt.')
        # Old archives are pruned only AFTER the new verified snapshot exists.
        protected = set(preserve)
        recent = sorted(backups.glob('*.zip'), reverse=True)
        for obsolete in recent[RETAIN:]:
            if obsolete.name not in protected:
                obsolete.unlink(missing_ok=True)
        return {
            'filename': name, 'path': str(target), 'files': len(records),
            'bytes': sum(item['size'] for item in records),
            'label': label, 'verified_zip': True,
        }
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def list_snapshots(backup_root):
    directory = Path(backup_root).expanduser()
    if not directory.is_dir():
        return []
    return [{'name': p.name, 'bytes': p.stat().st_size}
            for p in sorted(directory.glob('*.zip'), reverse=True)[:RETAIN]
            if p.is_file() and not p.is_symlink()]


def restore_snapshot(workspace, backup_root, name, approve, *, preserve=()):
    project, backups = _safe_root(workspace, backup_root)
    if not isinstance(name, str) or '/' in name or '\\' in name or not name.endswith('.zip'):
        raise SnapshotError('Ungültiger Snapshot-Name.')
    archive_path = backups / name
    if archive_path.is_symlink() or not archive_path.is_file():
        raise SnapshotError('Backup nicht vorhanden.')
    # Check full archive and all stored hashes before requesting approval.
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES + 1:
            raise SnapshotError('Backup enthält zu viele Einträge.')
        try:
            manifest = json.loads(archive.read('SYTOX_SNAPSHOT_MANIFEST.json'))
        except (ValueError, KeyError, UnicodeDecodeError) as exc:
            raise SnapshotError('Backup-Manifest fehlt oder ist fehlerhaft.') from exc
        records = manifest.get('files')
        if not isinstance(records, list) or len(records) > MAX_FILES:
            raise SnapshotError('Unbekanntes Backup-Format.')
        validated = {}
        total = 0
        for record in records:
            relative = record.get('path')
            if not isinstance(relative, str):
                raise SnapshotError('Ungültiger Archivpfad.')
            path = PurePosixPath(relative)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or relative == 'SYTOX_SNAPSHOT_MANIFEST.json'):
                raise SnapshotError('Unsicherer Archivpfad.')
            actual = (project / Path(*path.parts)).resolve()
            if actual != project and project not in actual.parents:
                raise SnapshotError('Archivpfad verlässt den Projektordner.')
            if actual.is_symlink():
                raise SnapshotError('Verlinkte Zieldatei darf nicht überschrieben werden.')
            data = archive.read(relative)
            total += len(data)
            if total > MAX_BYTES or len(data) > MAX_FILE_BYTES:
                raise SnapshotError('Backup überschreitet Sicherheitsgrenzen.')
            if hashlib.sha256(data).hexdigest() != record.get('sha256'):
                raise SnapshotError('Datei-Hash weicht vom Backup-Manifest ab.')
            validated[actual] = data
    if not approve('Projekt aus Backup wiederherstellen',
                   f'Backup: {name}\\n{len(validated)} Dateien werden überschrieben. '
                   'Dieser Schritt verändert das Projekt. Vorher wird der aktuelle '
                   'Zustand zusätzlich gesichert. Nicht enthaltene Dateien werden '
                   'nicht automatisch gelöscht.'):
        return {'status': 'denied', 'files': 0}
    before = create_snapshot(project, backups, 'before_restore', preserve=preserve)
    for path, data in validated.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix='.sytox_restore_', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            Path(tmp_name).replace(path)
        finally:
            Path(tmp_name).unlink(missing_ok=True)
    return {'status': 'restored', 'files': len(validated),
            'recovery_snapshot': before['filename']}
