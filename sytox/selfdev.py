"""Reviewable self-development in a separate source copy.

No code is ever installed into the running application. Python tests in a worktree
are executable code, so a separate and explicit user approval is required.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from .storage import default_data_dir


EXCLUDED = {'.git', '.venv', '__pycache__', 'build', 'dist', 'browser_profile',
            '.pytest_cache', 'selfdev_releases', '.mypy_cache', '.tox'}
FILE_LIMIT = 750_000
TOTAL_LIMIT = 14_000_000


class SelfDevelopment:
    def __init__(self, workspace, approve, stop=None, source=None, data_dir=None):
        self.workspace = Path(workspace).expanduser().resolve()
        if source is None and getattr(sys, 'frozen', False):
            source = Path(sys._MEIPASS) / 'source_bundle'
        self.source = Path(source or Path(__file__).resolve().parent.parent).resolve()
        self.approve = approve
        self.stop = stop
        self.worktree = self.workspace / 'assistant_source'
        # The baseline and validation are kept outside the model-editable workspace.
        key = hashlib.sha256(str(self.workspace).encode('utf-8')).hexdigest()[:24]
        self.state = Path(data_dir or default_data_dir()) / 'selfdev' / key
        self.baseline = self.state / 'baseline'
        self.validation = self.state / 'validation.json'

    @staticmethod
    def _files(root):
        result = {}
        total = 0
        if not root.is_dir():
            raise ValueError('Quellcode-Verzeichnis fehlt.')
        for path in root.rglob('*'):
            parts = path.relative_to(root).parts
            if any(p in EXCLUDED for p in parts):
                continue
            if path.is_symlink():
                raise ValueError(f'Symbolische Verknüpfung in der Arbeitskopie verboten: {path.name}')
            if not path.is_file():
                continue
            size = path.stat().st_size
            if size > FILE_LIMIT:
                raise ValueError(f'Datei zu groß: {path.name}')
            total += size
            if total > TOTAL_LIMIT:
                raise ValueError('Arbeitskopie überschreitet die Größenbegrenzung.')
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result

    def _require_prepared(self):
        if not (self.worktree.is_dir() and self.baseline.is_dir()):
            raise ValueError('Erst selfdev_prepare ausführen; Arbeitskopie/Baseline fehlt.')
        if self.worktree.is_symlink() or self.baseline.is_symlink():
            raise ValueError('Symlink als Quellcode-Verzeichnis ist nicht erlaubt.')

    def prepare(self):
        if self.workspace == self.source or self.source in self.workspace.parents or self.workspace in self.source.parents:
            raise PermissionError('Arbeitsordner muss außerhalb des installierten Quellcodes liegen.')
        if self.worktree.exists() or self.baseline.exists():
            self._require_prepared()
            return 'Bestehende Arbeitskopie assistant_source unverändert erhalten; kein Überschreiben.'
        self.approve('Self-Development vorbereiten',
                     'Quellcode in assistant_source kopieren, Baseline im lokalen App-Datenordner speichern. '
                     'Die laufende Anwendung bleibt unverändert.')
        self.state.mkdir(parents=True, exist_ok=True)
        ignore = shutil.ignore_patterns(*EXCLUDED, '*.pyc', '*.db', '*.sqlite3', '*.key')
        try:
            shutil.copytree(self.source, self.baseline, ignore=ignore)
            shutil.copytree(self.source, self.worktree, ignore=ignore)
            # Detect symlinks/binary payloads in both trees before trusting them.
            self._files(self.baseline)
            self._files(self.worktree)
        except Exception:
            shutil.rmtree(self.worktree, ignore_errors=True)
            shutil.rmtree(self.baseline, ignore_errors=True)
            raise
        return 'Arbeitskopie assistant_source erstellt; unabhängige Original-Baseline gespeichert.'

    def _changes(self):
        self._require_prepared()
        original, current = self._files(self.baseline), self._files(self.worktree)
        allpaths = sorted(set(original) | set(current))
        changed = [p for p in allpaths if original.get(p) != current.get(p)]
        if len(changed) > 100:
            raise ValueError('Zu viele veränderte Dateien (max. 100).')
        fingerprint = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
        return changed, original, current, fingerprint

    def review(self):
        changed, old, new, fingerprint = self._changes()
        lines = []
        for path in changed[:40]:
            kind = 'NEU' if path not in old else 'GELÖSCHT' if path not in new else 'GEÄNDERT'
            lines.append(f'{kind}: {path}')
        if len(changed) > 40:
            lines.append(f'... weitere {len(changed)-40} Dateien')
        # Show a bounded preview of the first changed source file.
        for path in changed:
            if not path.endswith(('.py', '.md', '.ps1', '.iss', '.bat', '.txt')):
                continue
            before = (self.baseline / path).read_text(encoding='utf-8', errors='replace').splitlines() if path in old else []
            after = (self.worktree / path).read_text(encoding='utf-8', errors='replace').splitlines() if path in new else []
            diff = list(difflib.unified_diff(before, after, fromfile='original/'+path,
                                             tofile='working/'+path, lineterm=''))
            if diff:
                lines.append('\nDiff-Auszug:\n'+'\n'.join(diff[:55])[:5500])
                break
        return {'changed': changed, 'fingerprint': fingerprint,
                'report': f'{len(changed)} geänderte Datei(en).\n' + '\n'.join(lines)}

    def _command(self, cmd):
        proc = subprocess.Popen(cmd, cwd=str(self.worktree), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', env=self._limited_env())
        started = time.monotonic()
        try:
            while True:
                if self.stop is not None and self.stop.is_set():
                    raise RuntimeError('Validierung abgebrochen.')
                if time.monotonic() - started > 120:
                    raise TimeoutError('Testlauf nach 120 Sekunden abgebrochen.')
                try:
                    stdout, _ = proc.communicate(timeout=0.25)
                    return proc.returncode, stdout[-8000:]
                except subprocess.TimeoutExpired:
                    pass
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    @staticmethod
    def _limited_env():
        # A precaution, not a sandbox: tests can access user files on the host.
        return {k:v for k,v in os.environ.items()
                if not re.search('token|secret|passw|api.?key|credential|authorization', k, re.I)}

    def validate(self):
        report = self.review()
        if not report['changed']:
            raise ValueError('Keine Änderungen vorhanden, die geprüft werden könnten.')
        if not (self.worktree / 'tests').is_dir():
            raise ValueError('tests/ wurde entfernt: sichere Prüfung nicht möglich.')
        self.approve('Self-Development-Tests ausführen',
                     f'{len(report["changed"])} geänderte Datei(en) in assistant_source. '
                     'Die Tests führen Code aus dieser Kopie auf deinem Computer aus. '
                     'Das ist KEINE isolierte Sandbox. Erst nach Freigabe starten.')
        # Both subprocesses run inside the copy, never in the live installation.
        python = ([sys.executable] if not getattr(sys, 'frozen', False)
                  else (['py', '-3'] if shutil.which('py') else
                        [shutil.which('python') or 'python']))
        code, output = self._command(python + ['-B', '-m', 'compileall', '-q', 'sytox', 'tests', 'main.py'])
        if code:
            raise RuntimeError('Syntaxprüfung fehlgeschlagen:\n'+output[-3000:])
        code, output = self._command(python + ['-B', '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
        tests = re.search(r'Ran\s+(\d+)\s+tests?', output)
        if code or not tests or int(tests.group(1)) == 0 or not re.search(r'\bOK\b', output):
            raise RuntimeError('Tests fehlgeschlagen oder keine Tests ausgeführt:\n'+output[-3500:])
        # Refuse a TOCTOU source change made while tests were running.
        if self.review()['fingerprint'] != report['fingerprint']:
            raise ValueError('Dateien während der Prüfung geändert; bitte erneut validieren.')
        self.state.mkdir(parents=True, exist_ok=True)
        record = {'fingerprint': report['fingerprint'], 'tests': int(tests.group(1)),
                  'changed': report['changed'], 'validated_at': int(time.time())}
        tmp = self.validation.with_suffix('.tmp')
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.validation)
        return f'Syntaxprüfung bestanden; {record["tests"]} Tests erfolgreich. Änderungen zur Freigabe vorgemerkt.'

    def stage(self):
        report = self.review()
        if not report['changed']:
            raise ValueError('Keine Änderungen zu paketieren.')
        if not self.validation.is_file():
            raise ValueError('Erst selfdev_validate mit erfolgreichen Tests ausführen.')
        validated = json.loads(self.validation.read_text(encoding='utf-8'))
        if validated['fingerprint'] != report['fingerprint']:
            raise ValueError('Seit der Prüfung gab es neue Änderungen; erneut validieren.')
        self.approve('Geprüftes Update als ZIP bereitstellen',
                     report['report'][:6500]+'\n\nEs wird NUR ein ZIP im Projektordner erzeugt. '
                     'Kein automatisches Installieren oder Austauschen des laufenden Programms.')
        # Recheck after the approval window (the user can take minutes to respond).
        if self.review()['fingerprint'] != validated['fingerprint']:
            raise ValueError('Quellcode nach Freigabe verändert; abgebrochen.')
        out = self.workspace / 'selfdev_releases'
        out.mkdir(parents=True, exist_ok=True)
        destination = out / f'SYTOX_kandidat_{uuid.uuid4().hex[:10]}.zip'
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self._files(self.worktree)):
                archive.write(self.worktree / path, arcname=path)
            archive.writestr('SELFDEV_REVIEW.json', json.dumps({
                'changed_files': report['changed'], 'tests': validated['tests'],
                'fingerprint': report['fingerprint'], 'warning': 'Not installed; manual review required.'},
                ensure_ascii=False, indent=2))
        return f'Kandidat erstellt: {destination.relative_to(self.workspace)}. Keine Live-Änderung.'
