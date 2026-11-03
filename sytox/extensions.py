"""User-approved, reversible assistant extensions. Every execution also needs consent.

An extension is a manifest and executable Python script installed as files; no dynamic
in-process imports, no hidden code execution. This is NOT an operating-system sandbox.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from .storage import default_data_dir

NAME_RE = re.compile(r'^[a-z][a-z0-9_]{2,31}$')


class ExtensionError(ValueError):
    pass


class Registry:
    def __init__(self, root=None):
        self.root = Path(root or default_data_dir() / 'extensions').resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _name(self, name):
        name = str(name or '')
        if not NAME_RE.fullmatch(name):
            raise ExtensionError('Erweiterungsname ungültig (3–32 Buchstaben/Ziffern/_).')
        return name

    def candidate(self, source_dir, name):
        name = self._name(name)
        folder = Path(source_dir).resolve()
        # Caller constrains candidate to the workspace.
        manifest_path = folder / 'manifest.json'
        script = folder / 'run.py'
        if not (manifest_path.is_file() and script.is_file()):
            raise ExtensionError('manifest.json oder run.py fehlt.')
        if manifest_path.stat().st_size > 15000 or script.stat().st_size > 200000:
            raise ExtensionError('Erweiterung zu groß.')
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('name') != name:
            raise ExtensionError('Erweiterungsname passt nicht zur manifest.json.')
        desc = manifest.get('description', '')
        if not isinstance(desc, str) or not 5 <= len(desc) <= 200:
            raise ExtensionError('Eine Beschreibung mit 5–200 Zeichen ist erforderlich.')
        inputs = manifest.get('parameters', {})
        if not isinstance(inputs, dict) or len(inputs) > 12:
            raise ExtensionError('Ungültige Parameterdefinition.')
        for k, v in inputs.items():
            if not NAME_RE.fullmatch(k) or v not in ('string', 'integer', 'boolean'):
                raise ExtensionError('Parameterdefinition ist ungültig.')
        tree = ast.parse(script.read_text(encoding='utf-8'), filename=str(script))
        # Python AST syntax check only: it does NOT declare the code secure.
        del tree
        codehash = hashlib.sha256(script.read_bytes()).hexdigest()
        return {'name': name, 'description': desc, 'parameters': inputs,
                'sha256': codehash, 'source': folder}

    def install(self, candidate_dir, name):
        info = self.candidate(candidate_dir, name)
        dest = self.root / info['name']
        if dest.exists():
            raise ExtensionError('Erweiterung existiert bereits. Zum Ändern zuerst deinstallieren.')
        tmp = Path(tempfile.mkdtemp(prefix='sytox-ext-', dir=self.root))
        try:
            shutil.copy2(info['source'] / 'manifest.json', tmp / 'manifest.json')
            shutil.copy2(info['source'] / 'run.py', tmp / 'run.py')
            (tmp / 'sha256.txt').write_text(info['sha256'], encoding='utf-8')
            tmp.replace(dest)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp)
        return info

    def list(self):
        entries = []
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir() or not NAME_RE.fullmatch(folder.name):
                continue
            try:
                info = self.candidate(folder, folder.name)
                if info['sha256'] != (folder / 'sha256.txt').read_text().strip():
                    continue
                entries.append(info)
            except (ExtensionError, FileNotFoundError, json.JSONDecodeError, SyntaxError):
                continue
        return entries

    def schema(self):
        return [{'type': 'function', 'function': {
            'name': 'ext_' + ext['name'], 'description': ext['description'] +
                ' (installierte Erweiterung; Ausführung benötigt Freigabe)',
            'parameters': {'type': 'object',
                           'properties': {k: {'type': v} for k, v in ext['parameters'].items()},
                           'required': list(ext['parameters']), 'additionalProperties': False}}}
                for ext in self.list()]

    def run(self, name, args, approval, stop_event, workspace):
        name = self._name(name)
        info = next((e for e in self.list() if e['name'] == name), None)
        if info is None:
            raise ExtensionError('Erweiterung ist nicht installiert oder wurde verändert.')
        if not isinstance(args, dict) or set(args) != set(info['parameters']):
            raise ExtensionError('Parameter passen nicht zum Manifest.')
        for key, kind in info['parameters'].items():
            expected = {'string': str, 'integer': int, 'boolean': bool}[kind]
            if type(args[key]) is not expected:
                raise ExtensionError(f'Parameter {key}: Typfehler')
        if not approval('Erweiterung ausführen: ' + name,
                        'Installierte Erweiterungen sind ausführbare Python-Programme und können mit deinen '
                        'Windows-Rechten auf Dateien und Netzwerk zugreifen.\n'
                        'Beschreibung: ' + info['description'] + '\nArgumente: ' + str(args)[:900]):
            raise ExtensionError('Ausführung nicht freigegeben.')
        if getattr(sys, 'frozen', False):
            interpreter = shutil.which('python') or shutil.which('python3')
            if not interpreter:
                raise ExtensionError('Für Python-Erweiterungen wird ein installierter Python-Interpreter benötigt.')
        else:
            interpreter = sys.executable
        cmd = [interpreter, str(info['source'] / 'run.py')]
        data = json.dumps(args, ensure_ascii=False)
        with tempfile.TemporaryFile(mode='w+t', encoding='utf-8') as output:
            proc = subprocess.Popen(cmd, cwd=str(workspace), stdin=subprocess.PIPE,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace')
            try:
                proc.stdin.write(data)
                proc.stdin.close()
                start = time.monotonic()
                while proc.poll() is None:
                    if stop_event is not None and stop_event.is_set():
                        proc.kill()
                        raise ExtensionError('Erweiterung gestoppt.')
                    if time.monotonic() - start > 45:
                        proc.kill()
                        raise ExtensionError('Erweiterung nach 45 s abgebrochen.')
                    time.sleep(.1)
                output.seek(0)
                out = output.read(12000)
                if proc.returncode:
                    raise ExtensionError('Erweiterung fehlgeschlagen (Exit '+str(proc.returncode)+'): '+out[-1500:])
                return 'Erweiterung erfolgreich: ' + out[:9000]
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)

