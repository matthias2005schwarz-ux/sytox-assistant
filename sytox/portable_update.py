"""Portable in-app updates with bounded startup verification and rollback.

A verified, complete PyInstaller onedir bundle is unpacked in APPDATA first.
The *new bundled EXE*, running from that staged directory, is a detached
helper. It waits for the old process to stop, swaps the application folder,
performs a real EXE smoke test and reopens the application. The previous
installation stays available for rollback. Chats and projects are elsewhere
in APPDATA and never participate in the swap.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

APP_EXE = "SYTOX_Assistant.exe"
BACKUP_SUFFIX = ".SYTOX-previous"
UNINSTALLER_RE = re.compile(r"unins\d{3}\.(?:exe|dat|msg)", re.IGNORECASE)
STAGE_PREFIX = "sytox-stage-"


class PortableUpdateError(RuntimeError):
    pass


def _is_file_in(directory: Path, file: Path) -> bool:
    return file.resolve().parent == directory.resolve()


def _validated_stage(stage):
    from .updater import update_cache_dir
    cache = update_cache_dir().resolve()
    path = Path(stage).resolve()
    if path.parent != cache or not path.name.startswith(STAGE_PREFIX):
        raise PortableUpdateError("Update-Paket liegt außerhalb des sicheren Update-Ordners.")
    if not (path / APP_EXE).is_file() or not (path / "_internal").is_dir():
        raise PortableUpdateError("Das Update enthält keine vollständige Windows-Anwendung.")
    if (path / APP_EXE).is_symlink():
        raise PortableUpdateError("Das Update enthält einen unsicheren EXE-Link.")
    return path


def _validated_target(target, stage):
    path = Path(target).resolve()
    if path == stage or path in stage.parents or stage in path.parents:
        raise PortableUpdateError("Installations- und Update-Ordner überschneiden sich.")
    if not (path / APP_EXE).is_file():
        raise PortableUpdateError("Die bisherige SYTOX-Installation wurde nicht gefunden.")
    if not any(p.is_file() and UNINSTALLER_RE.fullmatch(p.name)
               for p in path.glob("unins*.dat")):
        raise PortableUpdateError(
            "Direkte Updates sind nur für die installierte Windows-Version verfügbar."
        )
    return path


def _flags():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _write_result(status, message):
    from .updater import update_cache_dir
    root = update_cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / "last_portable_update.tmp"
    destination = root / "last_portable_update.json"
    try:
        temporary.write_text(json.dumps({
            "status": str(status), "message": str(message)[:800],
        }, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, destination)
    except OSError:
        pass


def _start(exe: Path):
    return subprocess.Popen([str(exe)], cwd=str(exe.parent),
                            close_fds=True, creationflags=_flags())


def _restore_backup(target: Path, backup: Path):
    """Restore the old folder, even if copying the new application failed."""
    if target.exists():
        shutil.rmtree(target)
    if not backup.is_dir():
        raise PortableUpdateError("Rückgängig machen fehlgeschlagen: Sicherung fehlt.")
    os.replace(backup, target)


def _copy_inno_metadata(backup: Path, target: Path):
    # The per-user Inno installation must remain uninstallable. We preserve
    # its registration files, without running an installer or changing HKCU.
    found = False
    for path in backup.iterdir():
        if path.is_file() and UNINSTALLER_RE.fullmatch(path.name):
            shutil.copy2(path, target / path.name)
            found = True
    if not found:
        raise PortableUpdateError("Inno-Uninstaller-Metadaten fehlen im Backup.")


def apply_staged_update(stage, target, *, smoke_timeout=90, startup_grace=7):
    """Swap application files only; rollback on a failed smoke or launch.

    Called after the old process exits. Does not need GitHub or network access.
    The helper itself runs from the staged bundle, not the directory replaced.
    """
    stage = _validated_stage(stage)
    target = _validated_target(target, stage)
    backup = target.with_name(target.name + BACKUP_SUFFIX)
    if backup.exists():
        # A previous successful update leaves one last-known-good copy.
        if not (backup / APP_EXE).is_file():
            raise PortableUpdateError("Vorhandene Sicherung ist ungültig.")
        shutil.rmtree(backup)
    moved = False
    launched = None
    try:
        os.replace(target, backup)
        moved = True
        shutil.copytree(stage, target)
        _copy_inno_metadata(backup, target)
        exe = target / APP_EXE
        check = subprocess.run(
            [str(exe), "--smoke-test"], cwd=str(target), check=False,
            creationflags=_flags(), timeout=smoke_timeout,
        )
        if check.returncode != 0:
            raise PortableUpdateError(
                f"Starttest der neuen Version fehlgeschlagen (Code {check.returncode})."
            )
        launched = _start(exe)
        # A new EXE that immediately dies does not count as a good update.
        until = time.monotonic() + startup_grace
        while time.monotonic() < until:
            if launched.poll() is not None:
                raise PortableUpdateError(
                    f"Neue Version wurde sofort beendet (Code {launched.returncode})."
                )
            time.sleep(min(.25, max(0.0, until - time.monotonic())))
        _write_result("success", "SYTOX wurde aktualisiert und neu gestartet.")
        return 0
    except Exception as exc:
        failure = str(exc)
        if launched is not None and launched.poll() is None:
            launched.terminate()
            try:
                launched.wait(timeout=10)
            except subprocess.TimeoutExpired:
                launched.kill()
                launched.wait(timeout=10)
        if moved:
            try:
                _restore_backup(target, backup)
            except Exception as restore_error:
                _write_result("failed", "Update-Fehler: " + failure
                              + "; Wiederherstellung fehlgeschlagen: " + str(restore_error))
                raise PortableUpdateError(
                    "Wiederherstellung fehlgeschlagen: " + str(restore_error)
                ) from exc
        _write_result("rolled_back", "Update fehlgeschlagen: " + failure
                      + ". Die vorige Version wurde wiederhergestellt.")
        if (target / APP_EXE).is_file():
            _start(target / APP_EXE)
        raise PortableUpdateError("Update rückgängig gemacht: " + failure) from exc


def run_portable_helper(stage, target, parent_pid):
    """Entry point of staged executable, before any Qt UI or microphone starts."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise PortableUpdateError("Dieser Update-Helfer läuft nur als Windows-EXE.")
    stage = _validated_stage(stage)
    target = _validated_target(target, stage)
    pid = int(parent_pid)
    if pid <= 0 or pid == os.getpid():
        raise PortableUpdateError("Ungültige Prozessnummer für das Update.")
    from .updater import _wait_for_process_exit
    if not _wait_for_process_exit(pid, timeout_ms=120000):
        _write_result("failed", "SYTOX läuft noch. Die Dateien wurden nicht geändert.")
        raise PortableUpdateError("Die bisherige Anwendung wurde nicht beendet.")
    return apply_staged_update(stage, target)
