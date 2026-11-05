"""User-initiated Ollama setup for Windows: install, start, and pull a local model.

No download, package install or service start occurs without an explicit UI action.
This module has no Qt dependency so its safety and error paths can be unit tested.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse

import requests

from .ollama_setup import _MODEL_PATTERN, check_ollama_status, OLLAMA_DOWNLOAD


class SetupFailure(RuntimeError):
    """An actionable Ollama installation, launch or model download failure."""


class SetupCancelled(SetupFailure):
    pass


MODEL_CHOICES = (
    ('Empfohlen für anspruchsvolles Programmieren · Qwen3-Coder 30B (19 GB)', 'qwen3-coder:30b'),
    ('Weniger RAM · Qwen2.5-Coder 7B (ca. 4,7 GB)', 'qwen2.5-coder:7b'),
    ('Sparsam · Qwen2.5-Coder 3B (ca. 2 GB)', 'qwen2.5-coder:3b'),
    ('Sehr sparsam · Qwen2.5-Coder 1.5B (ca. 1 GB)', 'qwen2.5-coder:1.5b'),
)


def valid_local_endpoint(address: str) -> str:
    """Never install or send a model-pull request to an arbitrary remote server."""
    raw = str(address or '').strip().rstrip('/')
    parsed = urlparse(raw)
    if (parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or parsed.port != 11434):
        raise SetupFailure('Automatische Einrichtung ist nur für http://localhost:11434 möglich. '
                           'Bitte die Ollama-Adresse in den Einstellungen prüfen.')
    return raw


def validate_model(model: str) -> str:
    name = str(model or '').strip()
    if not _MODEL_PATTERN.fullmatch(name):
        raise SetupFailure('Ungültiger Modellname.')
    return name


def find_ollama_exe(which=shutil.which, environ=None) -> str | None:
    """Detect a per-user Ollama installation even before PATH is refreshed."""
    env = environ if environ is not None else os.environ
    found = which('ollama.exe') or which('ollama')
    if found:
        return str(found)
    roots = (Path(env.get('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'ollama.exe',
             Path(env.get('ProgramFiles', '')) / 'Ollama' / 'ollama.exe')
    for item in roots:
        if str(item) and item.is_file():
            return str(item)
    return None


def _ensure_not_cancelled(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise SetupCancelled('Einrichtung abgebrochen.')


def install_with_winget(cancel: threading.Event, report, *, which=shutil.which,
                        popen=subprocess.Popen, timeout=900) -> None:
    """Install only the official winget package, no shell or unverified executable URL."""
    if sys.platform != 'win32':
        raise SetupFailure('Die automatische Installation funktioniert nur unter Windows.')
    winget = which('winget.exe') or which('winget')
    if not winget:
        raise SetupFailure('Windows-Paketmanager winget nicht gefunden. '
                           f'Ollama stattdessen über {OLLAMA_DOWNLOAD} installieren.')
    _ensure_not_cancelled(cancel)
    report('Ollama wird über den Windows-Paketmanager installiert …', None)
    cmd = [winget, 'install', '--id', 'Ollama.Ollama', '--exact', '--source', 'winget',
           '--silent', '--accept-package-agreements', '--accept-source-agreements',
           '--disable-interactivity']
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    proc = popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, creationflags=flags)
    start = time.monotonic()
    try:
        while proc.poll() is None:
            _ensure_not_cancelled(cancel)
            if time.monotonic() - start > timeout:
                raise SetupFailure('Ollama-Installation hat das Zeitlimit überschritten. '
                                   'Bitte im Windows-Paketmanager prüfen.')
            time.sleep(.25)
        if proc.returncode != 0:
            raise SetupFailure(f'Windows-Paketmanager meldet Fehlercode {proc.returncode}. '
                               f'Alternativ direkt von {OLLAMA_DOWNLOAD} installieren.')
    except (SetupCancelled, SetupFailure):
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        raise


def start_ollama(url: str, cancel: threading.Event, report, *, exe: str | None = None,
                 popen=subprocess.Popen, get=requests.get, wait_seconds=35) -> None:
    """Start `ollama serve` only if no local Ollama API is already responding."""
    endpoint = valid_local_endpoint(url)
    _ensure_not_cancelled(cancel)
    try:
        response = get(endpoint + '/api/tags', timeout=2)
        if response.ok:
            return
    except requests.RequestException:
        pass
    binary = exe or find_ollama_exe()
    if not binary:
        raise SetupFailure('Ollama wurde nicht gefunden. Bitte erneut installieren oder Ollama starten.')
    report('Ollama wird im Hintergrund gestartet …', None)
    flags = (getattr(subprocess, 'CREATE_NO_WINDOW', 0)
             | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    popen([binary, 'serve'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
          stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
    until = time.monotonic() + wait_seconds
    while time.monotonic() < until:
        _ensure_not_cancelled(cancel)
        try:
            response = get(endpoint + '/api/tags', timeout=2)
            if response.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(.5)
    raise SetupFailure('Ollama wurde gestartet, die lokale API antwortet aber noch nicht. '
                       'Bitte Ollama im Windows-Infobereich kontrollieren.')


def pull_model(url: str, model: str, cancel: threading.Event, report,
               *, post=requests.post) -> None:
    """Stream progress from Ollama; only success frames count as completion."""
    endpoint = valid_local_endpoint(url)
    name = validate_model(model)
    _ensure_not_cancelled(cancel)
    report('KI-Modell wird heruntergeladen – das kann mehrere Gigabyte benötigen …', 0)
    try:
        with post(endpoint + '/api/pull', json={'model': name, 'stream': True},
                  stream=True, timeout=(10, 90)) as response:
            response.raise_for_status()
            succeeded = False
            for line in response.iter_lines():
                _ensure_not_cancelled(cancel)
                if not line:
                    continue
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise SetupFailure('Ungültige Antwort beim Modell-Download.')
                if message.get('error'):
                    raise SetupFailure(str(message['error'])[:250])
                state = str(message.get('status', 'Download läuft'))
                total = message.get('total') or 0
                done = message.get('completed') or 0
                percent = None
                if isinstance(total, (int, float)) and isinstance(done, (int, float)) and total > 0:
                    percent = min(99, max(0, int(done / total * 100)))
                    report(f'{state}: {done / (1024 ** 2):.0f} / {total / (1024 ** 2):.0f} MB', percent)
                else:
                    report(state, percent)
                if state == 'success':
                    succeeded = True
                    break
            if not succeeded:
                raise SetupFailure('Ollama meldete keinen erfolgreichen Abschluss des Modell-Downloads.')
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise SetupFailure('Modell-Download fehlgeschlagen: ' + str(exc)[:230]) from exc
    _ensure_not_cancelled(cancel)
    report('KI-Modell vollständig heruntergeladen.', 100)


def setup_local_ollama(url: str, model: str, cancel: threading.Event, report,
                       *, status_checker=check_ollama_status,
                       installer=install_with_winget, starter=start_ollama,
                       puller=pull_model, locate=find_ollama_exe) -> str:
    """Orchestrate only the missing steps; every step is user-initiated in the UI."""
    address = valid_local_endpoint(url)
    name = validate_model(model)
    _ensure_not_cancelled(cancel)
    report('Lokale KI wird überprüft …', None)
    current = status_checker(address, name)
    if current.state in ('invalid_config', 'error'):
        raise SetupFailure(current.details)
    if current.state == 'offline':
        executable = locate()
        if not executable:
            installer(cancel, report)
            # Winget may install to LOCALAPPDATA without updating the process PATH.
            for _ in range(30):
                _ensure_not_cancelled(cancel)
                executable = locate()
                if executable:
                    break
                time.sleep(.5)
            if not executable:
                raise SetupFailure('Installation abgeschlossen, Ollama.exe wurde aber nicht gefunden. '
                                   'Bitte Ollama einmal über das Windows-Startmenü starten.')
        starter(address, cancel, report, exe=executable)
        current = status_checker(address, name)
    if current.state == 'missing_model':
        puller(address, name, cancel, report)
        current = status_checker(address, name)
    _ensure_not_cancelled(cancel)
    if not current.ready:
        raise SetupFailure('KI noch nicht bereit: ' + current.details)
    report('KI ist bereit! Du kannst jetzt chatten.', 100)
    return name
