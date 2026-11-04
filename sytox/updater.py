"""Verified, consent-first updates from official SYTOX GitHub Releases.

Background checks never install anything. An update is only applied after explicit
user approval; downloaded installers must match the release's SHA-256 sidecar.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

import requests

from . import __version__
from .storage import default_data_dir

REPOSITORY = "matthias2005schwarz-ux/sytox-assistant"
RELEASES_API = "https://api.github.com/repos/" + REPOSITORY + "/releases/latest"
RELEASES_PAGE = "https://github.com/" + REPOSITORY + "/releases"
MAX_INSTALLER_BYTES = 600 * 1024 * 1024
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-dev)?$")
_INSTALLER = re.compile(r"^SYTOX_Assistant_Setup_\d+\.\d+\.\d+\.exe$")
_ALLOWED_DOWNLOAD_HOSTS = frozenset((
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
))


class UpdateError(RuntimeError):
    """No update action was taken; the error can be shown to the user."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_url: str
    installer_url: str
    checksum_url: str
    filename: str


def version_tuple(value):
    match = _VERSION.fullmatch(str(value).strip())
    if not match:
        raise UpdateError("Ungültige Versionsnummer: " + str(value))
    return tuple(int(part) for part in match.groups())


def update_cache_dir():
    return default_data_dir() / "updates"


def is_installed_app():
    """Do not try to replace a developer's Python environment or portable build."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    return Path(sys.executable).name.lower() == "sytox_assistant.exe"


def _trusted_download(url, *, is_redirect=False):
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise UpdateError("Ungültige HTTPS-Adresse für das Update.")
    if parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise UpdateError("Update stammt nicht von einer erlaubten GitHub-Adresse.")
    if parsed.port not in (None, 443):
        raise UpdateError("Ungültiger Update-Port.")
    if not is_redirect:
        if parsed.hostname != "github.com" or not parsed.path.startswith(
            "/" + REPOSITORY + "/releases/download/"
        ):
            raise UpdateError("Das Update stammt nicht aus dem offiziellen Release.")
    return url


def _request(url, *, stream=False):
    response = requests.get(
        url, timeout=(4, 12), stream=stream, allow_redirects=True,
        headers={"User-Agent": "SYTOX-Assistant-Updater/" + __version__},
    )
    try:
        _trusted_download(response.url, is_redirect=True)
        response.raise_for_status()
        return response
    except Exception:
        response.close()
        raise


def check_for_update(current_version=__version__):
    """Return a newer stable release with both required assets, or None."""
    try:
        response = requests.get(
            RELEASES_API, timeout=(4, 12),
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "SYTOX-Assistant-Updater/" + __version__},
        )
        try:
            if response.status_code == 404:  # No published releases yet.
                return None
            response.raise_for_status()
            release = response.json()
        finally:
            response.close()
    except requests.RequestException as exc:
        raise UpdateError("GitHub konnte nicht erreicht werden: " + str(exc)) from exc

    if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
        return None
    tag = str(release.get("tag_name", ""))
    match = re.fullmatch(r"v?(\d+\.\d+\.\d+)", tag)
    if not match:
        return None
    version = match.group(1)
    if version_tuple(version) <= version_tuple(current_version):
        return None
    name = "SYTOX_Assistant_Setup_" + version + ".exe"
    assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])
              if isinstance(a, dict)}
    installer = assets.get(name)
    checksum = assets.get(name + ".sha256")
    if not installer or not checksum:
        return None  # Incomplete release: never install unverified binaries.
    _trusted_download(installer)
    _trusted_download(checksum)
    release_url = "https://github.com/" + REPOSITORY + "/releases/tag/" + tag
    return UpdateInfo(version, release_url, installer, checksum, name)


def _expected_checksum(update):
    _trusted_download(update.checksum_url)
    with _request(update.checksum_url, stream=True) as response:
        content = bytearray()
        for piece in response.iter_content(chunk_size=1024):
            content.extend(piece)
            if len(content) > 4096:
                raise UpdateError("SHA-256-Datei ist ungewöhnlich groß.")
    try:
        text = content.decode("ascii").strip()
    except UnicodeError as exc:
        raise UpdateError("Ungültige SHA-256-Datei.") from exc
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(.+)", line.strip())
        if match and match.group(2) == update.filename:
            return match.group(1).lower()
    raise UpdateError("Passender SHA-256-Prüfwert fehlt im Release.")


def download_verified_installer(update, progress=None):
    """Stream to a private temporary file, verify hash, then atomically cache."""
    if not _INSTALLER.fullmatch(update.filename):
        raise UpdateError("Ungültiger Installer-Dateiname.")
    expected = _expected_checksum(update)
    target_dir = update_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / update.filename
    fd, temp_name = tempfile.mkstemp(prefix="sytox_update_", suffix=".part", dir=target_dir)
    digest = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as out, _request(update.installer_url, stream=True) as response:
            length = int(response.headers.get("Content-Length") or 0)
            if length > MAX_INSTALLER_BYTES:
                raise UpdateError("Update überschreitet die erlaubte Dateigröße.")
            for chunk in response.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > MAX_INSTALLER_BYTES:
                    raise UpdateError("Update überschreitet die erlaubte Dateigröße.")
                digest.update(chunk)
                out.write(chunk)
                if progress and length:
                    progress(min(99, int(100 * size / length)))
        if not size or not hmac.compare_digest(digest.hexdigest(), expected):
            raise UpdateError("SHA-256-Prüfung fehlgeschlagen. Update wird nicht gestartet.")
        os.replace(temp_name, target)
        if progress:
            progress(100)
        return target
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _valid_cached_installer(path):
    path = Path(path).resolve()
    if path.parent != update_cache_dir().resolve() or not _INSTALLER.fullmatch(path.name):
        raise UpdateError("Installer außerhalb des geprüften Update-Ordners.")
    if not path.is_file():
        raise UpdateError("Update-Installer nicht gefunden.")
    return path


def schedule_installer(path):
    """Spawn the current EXE as a tiny helper; it waits until the app exits."""
    if not is_installed_app():
        raise UpdateError("Automatische Installation funktioniert nur mit der installierten Windows-EXE.")
    path = _valid_cached_installer(path)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen([sys.executable, "--apply-update", str(path), str(os.getpid())],
                     close_fds=True, creationflags=flags)


def _wait_for_process_exit(pid, timeout_ms=120000):
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x00100000, 0, pid)  # SYNCHRONIZE
    if not handle:  # Parent already exited.
        return True
    try:
        return kernel.WaitForSingleObject(handle, timeout_ms) == 0  # WAIT_OBJECT_0
    finally:
        kernel.CloseHandle(handle)


def run_update_helper(path, parent_pid):
    """Run before Qt/IPC initialization, and never hold the installer's app mutex."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        raise UpdateError("Der Update-Helfer läuft nur als Windows-EXE.")
    installer = _valid_cached_installer(path)
    pid = int(parent_pid)
    if pid <= 0 or not _wait_for_process_exit(pid):
        raise UpdateError("SYTOX läuft noch. Update wurde nicht gestartet.")
    subprocess.Popen(
        [str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
         "/CLOSEAPPLICATIONS", "/LANG=german"],
        cwd=str(installer.parent), close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return 0
