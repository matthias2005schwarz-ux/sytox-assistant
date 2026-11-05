"""Explicit capabilities. The local model never gets an unrestricted hidden shell."""
from __future__ import annotations
import os
import platform
import re
import json
import shutil
import shlex
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from .toolchains import canonical_language, propose, status, TOOLCHAINS
from .program_build import build_plan, inspect_build_artifact
from .storage import default_data_dir
from .selfdev import SelfDevelopment
from .extensions import Registry
from .gmail import GmailClient
from .pc_control import WindowsDesktop
from .web_search import search_web, format_results


TOOLS = [
    ('list_files','List files relative to the chosen project workspace.',{'path':('string','Relative directory, e.g. .')},['path']),
    ('read_file','Read a UTF-8 file in the project workspace.',{'path':('string','Relative file path')},['path']),
    ('write_file','Create/replace a UTF-8 file inside the project workspace. Backups of edited files are made.',
     {'path':('string','Relative file path'),'content':('string','Complete file contents')},['path','content']),
    ('run_command','Execute a local development command in the project. Common test/lint commands run without approval; others require permission.',
     {'command':('string','Command to execute, e.g. python -m pytest')},['command']),
    ('project_build_plan','Read-only: show deterministic Windows project build command, expected artifact and runtime dependencies.',{},[]),
    ('project_build','Build a supported project with explicit approval; verify a native EXE, JVM artifact or checked script and SHA256, without launching it.',{},[]),
    ('toolchain_inspect','Read-only: recommend a language for a task, inspect project files and check installed developer tools. Never installs anything.',
     {'task':('string','Describe the program to build; may be empty to inspect the project')},[]),
    ('toolchain_install','Install ONE curated Windows compiler/SDK through winget. Always asks for explicit user approval of the exact package first.',
     {'language':('string','Language from toolchain_inspect, e.g. python, cpp, csharp, java, rust')},['language']),
    ('remember','Save a persistent note to recall across conversations.',{'text':('string','Important durable fact')},['text']),
    ('open_url','Open a webpage in the standard PC browser.',{'url':('string','Full https URL')},['url']),
    ('web_search','Search public internet for factual/current information. Read-only; returns snippets and source URLs.',
     {'query':('string','Public search terms; do not include private data or secrets')},['query']),
    ('browser_visit','Open an address in the automated browser (separate saved login profile).',
     {'url':('string','Full https URL')},['url']),
    ('browser_read','Read visible page title and text from the automated browser.',{},[]),
    ('browser_click','Click a browser element via CSS selector. Requires permission for every click because buttons may have side effects.',
     {'selector':('string','CSS selector')},['selector']),
    ('browser_type','Enter text into a page element via CSS selector. Does not submit forms.',
     {'selector':('string','CSS selector'),'text':('string','Text to type')},['selector','text']),
    ('pc_find_apps','Find installed Windows Start Menu/Desktop shortcuts by name; returns absolute paths.',
     {'query':('string','Part of application name, e.g. Notepad')},['query']),
    ('pc_list_windows','List visible Windows desktop windows with ID, title and bounds. Does not change anything.',{},[]),
    ('pc_select_window','Select and focus a window by ID returned from pc_list_windows. Requires approval before focusing.',
     {'window_id':('integer','Window ID from pc_list_windows')},['window_id']),
    ('pc_inspect_window','Read named accessibility controls of the selected window after approval; may expose private text.',{},[]),
    ('pc_click_control','Click a named Windows UI Automation control by ID from pc_inspect_window; requires approval.',
     {'control_id':('integer','Control ID from pc_inspect_window')},['control_id']),
    ('pc_open_app','Launch an existing Windows .exe or .lnk by absolute path. Requires approval.',
     {'path':('string','Absolute .exe or .lnk path')},['path']),
    ('pc_type_text','Enter Unicode text into the explicitly selected desktop window, after approval. Never use for passwords.',
     {'text':('string','Text to type into selected window')},['text']),
    ('pc_hotkey','Send a keyboard shortcut to the selected desktop window, e.g. ctrl+s. Requires approval.',
     {'keys':('string','Keys joined by +')},['keys']),
    ('pc_click','Click desktop coordinates inside the selected window only. Requires approval.',
     {'x':('integer','Screen pixel X'),'y':('integer','Screen pixel Y')},['x','y']),
    ('selfdev_prepare','Create a working copy and preserved baseline for self-development.',{},[]),
    ('selfdev_review','Compare the self-development worktree with the original baseline; show changed files and a small diff.',{},[]),
    ('selfdev_validate','Run source syntax checks and unit tests in the development copy, with explicit permission.',{},[]),
    ('selfdev_stage','After successful tests and approval, package the development copy for manual review. Never install automatically.',{},[]),
    ('extension_install','Install a new assistant tool from the project workspace/extension_candidates/<name>/, after explicit permission.',
     {'name':('string','Extension identifier, e.g. gmail_helper')},['name']),
    ('extension_list','List currently installed user-approved assistant extensions.',{},[]),
    ('gmail_connect','Begin explicit Google OAuth login for Gmail (requires a configured desktop OAuth client JSON).',{},[]),
    ('gmail_search','Search Gmail messages by a Gmail search query. Requires user OAuth.',
     {'query':('string','Gmail search syntax, e.g. from:example@example.com newer_than:7d')},['query']),
    ('gmail_read','Read one Gmail message by its ID. Requires user OAuth.',
     {'message_id':('string','Gmail message ID from gmail_search')},['message_id']),
    ('gmail_draft','Create a Gmail draft; does NOT send.',
     {'to':('string','Recipient email'),'subject':('string','Subject'),'body':('string','Message body')},['to','subject','body']),
    ('gmail_send','Send an email through the user-owned Gmail account. ALWAYS requires a separate approval.',
     {'to':('string','Recipient email'),'subject':('string','Subject'),'body':('string','Message body')},['to','subject','body']),
]


def tool_schema():
    result=[]
    for name,desc,props,required in TOOLS:
        result.append({'type':'function','function':{
            'name':name,'description':desc,
            'parameters':{'type':'object','properties':{
                p:{'type':ty,'description':helptext} for p,(ty,helptext) in props.items()},
                'required':required,'additionalProperties':False}}})
    return result


class Cancelled(Exception):
    pass


class Denied(Exception):
    pass


class Toolkit:
    def __init__(self, store, workspace, approval, stop_event=None, chat_id=None, logger=None, gmail_client_secrets=''):
        self.store=store
        self.workspace=Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True,exist_ok=True)
        self.approval=approval
        self.stop_event=stop_event
        self.chat_id=chat_id
        self.logger=logger or (lambda *args:None)
        self._playwright=None
        self._browser=None
        self._page=None
        self._tests_approved=False
        self.action_count=0
        self.has_meaningful_evidence=False
        self.extensions=Registry()
        self.gmail=GmailClient(gmail_client_secrets)
        self.pc=WindowsDesktop()
        self.selfdev=SelfDevelopment(self.workspace, self._request, self.stop_event)
        self._pc_selected=None
        self._pc_controls={}
        self.writes=0
        self.passed_checks=0
        self.built_artifacts=[]  # Build receipts are invalidated after every subsequent source edit.
        self.unvalidated_paths=set()  # Relative paths changed since the last successful code check.

    def _check(self):
        if self.stop_event is not None and self.stop_event.is_set(): raise Cancelled('Gestoppt')

    def _path(self, raw):
        raw=str(raw or '.')
        target=(self.workspace / raw).resolve()
        if target!=self.workspace and self.workspace not in target.parents:
            raise PermissionError('Zugriff außerhalb des Projektordners ist gesperrt.')
        return target

    def _request(self,label,description):
        self._check()
        if not self.approval(label,description):
            raise Denied('Aktion wurde nicht freigegeben.')

    def close(self):
        try:
            if self._browser: self._browser.close()
            if self._playwright: self._playwright.stop()
        except Exception: pass

    def _get_page(self):
        if self._page: return self._page
        from playwright.sync_api import sync_playwright
        self._playwright=sync_playwright().start()
        profile=default_data_dir()/'browser_profile'
        profile.mkdir(parents=True,exist_ok=True)
        self._browser=self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=False,
            accept_downloads=True, viewport={'width':1240,'height':850})
        self._page=self._browser.pages[0] if self._browser.pages else self._browser.new_page()
        return self._page

    def call(self,name,args):
        self._check()
        if not isinstance(args,dict): return 'Fehler: Werkzeugargumente sind kein Objekt.'
        valid={x[0] for x in TOOLS}
        if name not in valid and not (name.startswith('ext_') and name[4:] in {e['name'] for e in self.extensions.list()}):
            return f'Unbekanntes Werkzeug {name}'
        # Never print Gmail bodies, OAuth data, typed passwords or full file contents
        # to the activity log; project file paths and lengths are enough for progress.
        safe_args = {key: (f'<{len(str(value))} Zeichen>' if key in ('content','text','body')
                            else str(value)[:120]) for key, value in args.items()}
        request_line = f'{name}: {safe_args}'
        self.logger('Werkzeug', request_line[:190])
        self.store.log('tool_request', request_line[:900], self.chat_id)
        try:
            if name.startswith('ext_'):
                response=self.extensions.run(name[4:],args,self.approval,self.stop_event,self.workspace)
            else:
                fn=getattr(self,'action_'+name)
                response=fn(**args)
            outcome=str(response)[:20000]
            # Read-only discovery, listing, and failed commands are NOT proof of completion.
            # Side effects (e.g. saved files or drafts) and actual reads count toward
            # a non-coding task; coding tasks additionally need post-write validation.
            evidence_tools = {
                'read_file', 'write_file', 'run_command', 'remember', 'browser_visit', 'web_search',
                'browser_read', 'browser_click', 'browser_type', 'pc_open_app',
                'pc_inspect_window', 'pc_click_control',
                'pc_type_text', 'pc_hotkey', 'pc_click', 'selfdev_prepare',
                'selfdev_validate', 'selfdev_stage',
                'extension_install', 'toolchain_install', 'project_build', 'gmail_search', 'gmail_read', 'gmail_draft',
                'gmail_send',
            }
            ok_command = name == 'run_command' and outcome.startswith('Exit code: 0\n')
            has_result = outcome not in ('', '(leer)', 'Kein Verzeichnis.')
            if name == 'web_search' and outcome.startswith('Keine Live-Suchergebnisse'):
                has_result = False
            if ((name in evidence_tools and name != 'run_command' and has_result)
                    or ok_command or name.startswith('ext_')):
                self.action_count += 1
                self.has_meaningful_evidence = True
            if name == 'write_file':
                self.built_artifacts.clear()
                self.writes += 1
                self.unvalidated_paths.add(str(self._path(args['path']).relative_to(self.workspace)))
            if ok_command and self._validates_pending_edits(str(args.get('command', '')), outcome):
                self.passed_checks += 1
                self.unvalidated_paths.clear()
            if name == 'selfdev_validate' and outcome.startswith('Syntaxprüfung bestanden;'):
                self.passed_checks += 1
                # Validated only files in the self-development copy, not unrelated edits.
                self.unvalidated_paths = {f for f in self.unvalidated_paths
                                          if not f.replace('\\', '/').startswith('assistant_source/')}
            # Desktop titles/accessibility content can contain private data. Do not save it in logs.
            logged = (f'{len(outcome)} Zeichen (Inhalt nicht protokolliert)'
                      if name in ('pc_find_apps', 'pc_list_windows', 'pc_select_window', 'pc_inspect_window') else outcome[:2000])
            self.store.log('tool_result', f'{name}: {logged}',self.chat_id)
            return outcome
        except Cancelled: raise
        except (Denied,Exception) as e:
            self.store.log('tool_error', f'{name}: {type(e).__name__}: {e}',self.chat_id)
            return f'FEHLER {type(e).__name__}: {e}'

    def action_list_files(self,path='.'):
        directory=self._path(path)
        if not directory.is_dir(): return 'Kein Verzeichnis.'
        entries=[]
        for child in sorted(directory.iterdir())[:160]:
            entries.append(('DIR ' if child.is_dir() else 'FILE ')+child.name)
        return '\n'.join(entries) or '(leer)'

    def action_read_file(self,path):
        p=self._path(path)
        if p.stat().st_size > 250_000: return 'Datei ist größer als 250 KB; bitte gezielter lesen.'
        return p.read_text(encoding='utf-8',errors='replace')[:22000]

    def action_write_file(self,path,content):
        p=self._path(path)
        if p.is_dir(): raise ValueError('Pfad ist ein Verzeichnis')
        if not isinstance(content,str): raise ValueError('Text benötigt')
        if len(content.encode('utf-8'))>900_000: raise ValueError('Datei zu groß für eine Aktion')
        p.parent.mkdir(parents=True,exist_ok=True)
        if p.exists():
            backup=default_data_dir()/'backups'/self.chat_id/(datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
            out=backup/p.relative_to(self.workspace)
            out.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(p,out)
        temp=p.with_name(p.name+'.sytox_tmp')
        temp.write_text(content,encoding='utf-8')
        temp.replace(p)
        return f'Gespeichert: {p.relative_to(self.workspace)} ({len(content)} Zeichen).'+ (' Vorherige Version gesichert.' if 'backup' in locals() else '')

    @staticmethod
    def _safe_command(command):
        # Safe means execution of known test/lint/read-only commands only, never arbitrary code.
        c=' '.join(command.lower().strip().split())
        if re.fullmatch(r'(?:python|py)(?:\.exe)? -m compileall(?: [\w./\\*:=+\- ]*)?',c): return True
        if re.fullmatch(r'php(?:\.exe)? -l [\w./\\-]+\.php',c): return True
        if re.fullmatch(r'git (?:status|diff|log)(?: [\w./\\*:=+\- ]*)?',c): return True
        return False

    def _validates_pending_edits(self, command, output):
        """A green test is not proof for files it did not check.

        In particular ``python -m compileall missing.py`` exits with code 0 on
        CPython, and must NOT satisfy the post-write validation rule.
        """
        if not output.startswith('Exit code: 0\n'):
            return False
        tokens = command.lower().strip().split()
        if not tokens:
            return False
        if tokens[0] in ('python', 'python.exe', 'py', 'py.exe') and tokens[1:3] == ['-m', 'compileall']:
            targets = [t for t in command.strip().split()[3:] if not t.startswith('-')]
            if not targets:
                return False
            try:
                paths = [self._path(t) for t in targets]
                if not all(p.exists() and (p.is_dir() or p.suffix.lower() == '.py') for p in paths):
                    return False
                return all(any(self._path(f) == t or t in self._path(f).parents for t in paths)
                           and f.lower().endswith('.py') for f in self.unvalidated_paths)
            except (PermissionError, ValueError):
                return False
        if tokens[0] in ('php', 'php.exe') and len(tokens) == 3 and tokens[1] == '-l':
            try:
                p = self._path(command.strip().split()[2])
                return p.is_file() and all(self._path(f) == p for f in self.unvalidated_paths)
            except (PermissionError, ValueError):
                return False
        if tokens[:3] in ([tokens[0], '-m', 'pytest'], [tokens[0], '-m', 'unittest']) and tokens[0] in ('python','python.exe','py','py.exe'):
            if re.search(r'Ran\s+0\s+tests?', output, re.IGNORECASE):
                return False
            return True
        if not self.unvalidated_paths:
            return False
        changed = {Path(path).suffix.lower() for path in self.unvalidated_paths}
        parts = command.lower().strip().split()
        if not parts:
            return False
        # Only compilation of a relevant workspace project is accepted here.
        # These are not "safe" shell commands: run_command still asks permission.
        if parts[:2] in (['dotnet', 'build'], ['dotnet', 'test']):
            projects = list(self.workspace.glob('*.csproj')) + list(self.workspace.glob('*/*.csproj'))
            return ('--no-build' not in parts and bool(projects)
                    and changed <= {'.cs', '.csproj', '.sln', '.slnx', '.xaml', '.resx'})
        if parts[:2] in (['cargo', 'check'], ['cargo', 'build'], ['cargo', 'test']):
            return ((self.workspace / 'Cargo.toml').is_file()
                    and changed <= {'.rs', '.toml'})
        if parts[:2] in (['go', 'build'], ['go', 'test']):
            return ((self.workspace / 'go.mod').is_file()
                    and changed <= {'.go', '.mod', '.sum'})
        if parts[0] in ('tsc', 'tsc.cmd') and '--noemit' in parts:
            return ((self.workspace / 'tsconfig.json').is_file()
                    and changed <= {'.ts', '.tsx', '.json'}
                    and any(self.workspace.rglob('*.ts')))
        if parts[:2] == ['node', '--check'] and len(parts) == 3:
            try:
                file = self._path(command.strip().split()[2])
                return (file.is_file() and file.suffix.lower() in ('.js', '.mjs', '.cjs')
                        and all(self._path(p) == file for p in self.unvalidated_paths))
            except (ValueError, PermissionError):
                return False
        if parts[0] in ('javac', 'javac.exe') and len(parts) >= 2:
            try:
                targets = [self._path(p) for p in command.split()[1:]]
                return (all(p.is_file() and p.suffix == '.java' for p in targets)
                        and all(self._path(p) in targets for p in self.unvalidated_paths))
            except (ValueError, PermissionError):
                return False
        if parts[0] in ('clang', 'clang++', 'gcc', 'g++') and '-fsyntax-only' in parts:
            try:
                targets = [self._path(p) for p in command.split()[1:]
                           if Path(p).suffix.lower() in ('.c', '.cpp', '.cc', '.cxx')]
                return (bool(targets) and all(p.is_file() for p in targets)
                        and all(self._path(p) in targets for p in self.unvalidated_paths))
            except (ValueError, PermissionError):
                return False
        return False


    def action_project_build_plan(self):
        return json.dumps(build_plan(self.workspace), ensure_ascii=False)

    def verified_builds(self):
        """Only report artifacts whose content still matches the approved build receipt."""
        verified = []
        for receipt in getattr(self, 'built_artifacts', []):
            try:
                current = inspect_build_artifact(self.workspace, receipt['path'], receipt.get('artifact_kind', 'pe'))
                if current['sha256'] == receipt['sha256']:
                    verified.append(current)
            except (OSError, ValueError):
                continue
        return verified

    def verified_exe_builds(self):
        """Non-native artifacts cannot satisfy an explicit .exe request."""
        return [item for item in self.verified_builds()
                if item.get('format') == 'Windows PE x64']

    def action_project_build(self):
        """Build or validate a supported project with per-build approval."""
        if platform.system() != 'Windows':
            raise RuntimeError('Automatische Projekt-Builds sind nur unter Windows verfügbar.')
        plan = build_plan(self.workspace)
        argv = plan['command']
        expected_name = plan.get('expected_artifact', plan.get('expected_executable'))
        kind = plan.get('artifact_kind', 'pe')
        self._request(
            'Windows-Projekt erstellen: ' + plan['language'],
            'Ein Build kann Projektcode ausführen und Dateien erzeugen. '
            'Abhängigkeiten können heruntergeladen werden.\n\n'
            + 'Befehl (ohne Shell): ' + subprocess.list2cmdline(argv)
            + '\nErwartetes Artefakt: ' + expected_name
            + '\nFormat: ' + kind
            + '\nNur nach Zustimmung wird der Build ausgeführt. '
              'Die erzeugte Datei wird verifiziert, aber NICHT gestartet.'
        )
        self._check()
        expected = self._path(expected_name)
        expected.parent.mkdir(parents=True, exist_ok=True)
        started_ns = time.time_ns()
        proc = None
        try:
            proc = subprocess.Popen(argv, cwd=str(self.workspace), shell=False,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace')
            start = time.monotonic()
            while True:
                if self.stop_event is not None and self.stop_event.is_set():
                    proc.kill()
                    raise Cancelled('Build abgebrochen.')
                if time.monotonic() - start > 600:
                    proc.kill()
                    raise TimeoutError('Build nach zehn Minuten abgebrochen.')
                try:
                    output, _ = proc.communicate(timeout=.4)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if proc.returncode != 0:
                raise RuntimeError('Compiler-Fehler (Exitcode ' + str(proc.returncode)
                                   + '):\n' + output[-2500:])
            if plan.get('copy_after_validation'):
                source = self._path(plan['copy_after_validation'])
                if source.is_symlink() or not source.is_file():
                    raise ValueError('Prüfquelle fehlt oder ist ein Link.')
                shutil.copyfile(source, expected)
            receipt = inspect_build_artifact(self.workspace, expected_name, kind)
            if expected.stat().st_mtime_ns < started_ns:
                raise RuntimeError('Ausgabe stammt aus einem früheren Build.')
            self._check()
            self.built_artifacts = [receipt]
            self.passed_checks += 1
            self.unvalidated_paths.clear()
            outcome = 'validated' if plan.get('copy_after_validation') else 'compiled'
            return json.dumps({
                'build': outcome, 'language': plan['language'],
                'command': argv, 'artifact': receipt,
                'runtime_command': plan.get('runtime_command'),
                'compiler_output_tail': output[-1200:]},
                ensure_ascii=False)
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()

    def action_toolchain_inspect(self, task=''):
        if not isinstance(task, str) or len(task) > 1000:
            raise ValueError('Auftragsbeschreibung zu lang.')
        return json.dumps(propose(task, self.workspace), ensure_ascii=False)

    def action_toolchain_install(self, language):
        """No arbitrary package IDs, no shell, and no implied consent from task text."""
        key = canonical_language(language)
        spec = TOOLCHAINS[key]
        if status(key, self.workspace)['ready']:
            return spec.name + ': benötigte Werkzeuge sind bereits im Suchpfad.'
        if key == 'typescript' and status('javascript')['ready']:
            return ('Node.js ist vorhanden, aber TypeScript fehlt noch. '
                    'Im gewählten Projekt ist nach gesonderter Freigabe '
                    'npm install --save-dev typescript möglich. '
                    'Anschließend toolchain_inspect erneut ausführen.')
        if platform.system() != 'Windows':
            raise RuntimeError('Die automatische Installation ist nur unter Windows verfügbar.')
        if not spec.package:
            raise ValueError('Für ' + spec.name + ' ist kein freigegebenes winget-Paket hinterlegt.')
        winget = shutil.which('winget')
        if not winget:
            raise RuntimeError('Windows-Paketmanager winget fehlt. Bitte App Installer prüfen.')
        argv = [winget, 'install', '--id', spec.package, '--exact', '--source', 'winget',
                '--accept-package-agreements', '--accept-source-agreements',
                '--disable-interactivity']
        self._request(
            'Entwicklungswerkzeug installieren: ' + spec.name,
            'Nur das folgende Paket aus der winget-Quelle wird installiert:\n'
            + spec.package + '\n\nAusführung: ' + ' '.join(argv)
            + '\nDownloads, Systemänderungen und ggf. Administratorrechte sind möglich. '
            + 'Es wird ohne Zustimmung nichts heruntergeladen. '
            + (('\nHinweis: ' + spec.note) if spec.note else '')
        )
        self._check()
        proc = None
        try:
            proc = subprocess.Popen(argv, cwd=str(self.workspace), shell=False,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding='utf-8', errors='replace')
            start = time.monotonic()
            while True:
                if self.stop_event and self.stop_event.is_set():
                    proc.kill()
                    raise Cancelled('Installation angehalten; bereits gestartete Systeminstaller '
                                    'können separat weiterlaufen.')
                if time.monotonic() - start > 900:
                    proc.kill()
                    raise TimeoutError('Installation nach 15 Minuten abgebrochen.')
                try:
                    output, _ = proc.communicate(timeout=.5)
                    break
                except subprocess.TimeoutExpired:
                    pass
            self._check()
            if proc.returncode:
                raise RuntimeError('winget Exitcode ' + str(proc.returncode)
                                   + ': ' + output[-2000:])
            check = status(key, self.workspace)
            return ('winget meldet Erfolg für ' + spec.package + '.\n'
                    + ('Compiler erkannt.' if check['ready'] else
                       'Compiler noch nicht im aktuellen Suchpfad. '
                       'SYTOX bzw. Windows-Terminal neu starten und erneut prüfen.')
                    + (('\n' + spec.note) if spec.note else ''))
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill()

    def action_run_command(self,command):
        if not isinstance(command,str) or len(command)>1500: raise ValueError('Ungültiger Befehl')
        if not self._safe_command(command):
            normalized=' '.join(command.lower().split())
            is_test=bool(re.fullmatch(r'(?:python|py)(?:\.exe)? -m (?:pytest|unittest)(?: [\w./\\*:=+\- ]*)?',normalized))
            if is_test and self._tests_approved:
                pass
            elif is_test:
                self._request('Projekt-Tests ausführen',
                    'Der Agent darf Tests aus dem Projektordner ausführen. Testdateien können beliebige '
                    'Python-Befehle enthalten. Die Freigabe gilt für Testläufe in diesem Auftrag.\n'+command[:350])
                self._tests_approved=True
            else:
                self._request('Befehl ausführen',command[:350])
        argv=command if os.name=='nt' else shlex.split(command)
        if not command.strip(): raise ValueError('Leerer Befehl')
        # Windows shlex(posix=False) keeps quotation marks around path arguments; prefer
        # subprocess with shell=False and a tokenized argument list.
        try:
            proc=subprocess.Popen(argv,cwd=str(self.workspace),stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
            start=time.monotonic()
            while True:
                if self.stop_event and self.stop_event.is_set():
                    proc.kill(); raise Cancelled('Befehl abgebrochen')
                if time.monotonic()-start>120:
                    proc.kill(); raise TimeoutError('Befehl nach 120 Sekunden abgebrochen')
                try:
                    output,_=proc.communicate(timeout=.4)
                    break
                except subprocess.TimeoutExpired:
                    pass
            return f'Exit code: {proc.returncode}\n{output[:12000]}'
        finally:
            if 'proc' in locals() and proc.poll() is None: proc.kill()

    def action_remember(self,text):
        return 'Gespeichert: '+self.store.add_memory(text)

    def action_open_url(self,url):
        parsed=urlparse(url)
        if parsed.scheme not in ('https','http'): raise ValueError('Nur Webadressen mit http(s) sind erlaubt')
        webbrowser.open(url)
        return 'Seite im Standardbrowser geöffnet.'

    def action_web_search(self, query):
        return format_results(query, search_web(query, stop_event=self.stop_event))

    def action_browser_visit(self,url):
        parsed=urlparse(url)
        if parsed.scheme not in ('https','http'): raise ValueError('Nur Webadressen mit http(s) sind erlaubt')
        page=self._get_page()
        page.goto(url,wait_until='domcontentloaded',timeout=25000)
        return f'Titel: {page.title()}\nURL: {page.url}\n'+page.locator('body').inner_text(timeout=10000)[:9000]

    def action_browser_read(self):
        page=self._get_page()
        return f'Titel: {page.title()}\nURL: {page.url}\n'+page.locator('body').inner_text(timeout=10000)[:10000]

    def action_browser_click(self,selector):
        page=self._get_page()
        self._request('Browser-Klick bestätigen',f'{page.url}\nCSS-Element: {selector}')
        page.locator(selector).first.click(timeout=10000)
        return f'Geklickt: {selector}. URL: {page.url}'

    def action_browser_type(self,selector,text):
        page=self._get_page()
        if len(text)>8000: raise ValueError('Text zu lang')
        page.locator(selector).first.fill(text,timeout=10000)
        return f'{len(text)} Zeichen in {selector} eingegeben (nicht abgesendet).'

    def action_pc_find_apps(self,query):
        return json.dumps(self.pc.find_apps(query),ensure_ascii=False)

    def action_pc_list_windows(self):
        windows=self.pc.windows()
        return json.dumps(windows,ensure_ascii=False) if windows else 'Keine sichtbaren Fenster gefunden.'

    def action_pc_select_window(self,window_id):
        target=self.pc.window(window_id)
        self._request('Windows-Fenster auswählen',f"Fenster: {target['title']}\nID: {target['id']}")
        self.pc.activate(target['id'])
        self._pc_selected=target['id']
        self._pc_controls={}
        return f"Fenster ausgewählt: {target['title']} (ID: {target['id']})."

    def _pc_target(self):
        if self._pc_selected is None:
            raise ValueError('Zuerst pc_list_windows und pc_select_window aufrufen.')
        return self.pc.window(self._pc_selected)

    def _pc_activate_and_check(self):
        target=self._pc_target()
        self._check()
        self.pc.activate(target['id'])
        if self.pc.foreground_id()!=target['id']:
            raise RuntimeError('Zielfenster hat nicht den Fokus. Keine Eingabe gesendet.')
        return target

    def action_pc_inspect_window(self):
        target=self._pc_target()
        self._request('Fensterinhalt lesen',f"UI-Elemente in {target['title']} auslesen? Kann private Texte enthalten.")
        self._pc_activate_and_check()
        elements,self._pc_controls=self.pc.inspect(target['id'])
        return json.dumps(elements,ensure_ascii=False) if elements else 'Keine zugänglichen Bedienelemente gefunden.'

    def action_pc_click_control(self,control_id):
        target=self._pc_target()
        if type(control_id) is not int or control_id not in self._pc_controls:
            raise LookupError('Bedienelement nicht vorhanden. Bitte pc_inspect_window erneut aufrufen.')
        control=self._pc_controls[control_id]
        self._request('Bedienelement anklicken',f"Fenster: {target['title']}\nBedienelement ID: {control_id}\nEin Klick kann Aktionen auslösen.")
        self._pc_activate_and_check()
        self._check()
        self.pc.click_control(control)
        self._pc_controls={}  # A click can change the UI; don't reuse stale element handles.
        return f'Bedienelement {control_id} angeklickt.'

    def action_pc_open_app(self,path):
        if os.name!='nt':
            raise EnvironmentError('App-Start über dieses Werkzeug ist nur unter Windows verfügbar.')
        p=Path(path).expanduser()
        if not p.is_absolute() or p.suffix.lower() not in ('.exe','.lnk') or not p.is_file():
            raise ValueError('Nur existierende, absolute Windows-Pfade zu .exe oder .lnk sind erlaubt.')
        self._request('Anwendung starten',str(p))
        self._check()
        if not p.is_file():
            raise FileNotFoundError('Anwendung wurde vor dem Start verschoben oder entfernt.')
        self.pc.open_app(p)
        return 'Startbefehl an Windows übergeben. Mit pc_list_windows das Fenster auswählen.'

    def action_pc_type_text(self,text):
        if not isinstance(text,str) or not text or len(text)>3000:
            raise ValueError('Texteingabe muss zwischen 1 und 3000 Zeichen lang sein.')
        target=self._pc_target()
        self._request('Text in Windows-Anwendung eingeben',
                      f"Fenster: {target['title']}\n{len(text)} Zeichen eingeben? Inhalt wird nicht protokolliert.\n"
                      'Keine Passwörter oder Zugangsdaten über diese Funktion eingeben.')
        self._pc_activate_and_check()
        def verify():
            self._check()
            if self.pc.foreground_id()!=self._pc_selected:
                raise RuntimeError('Fokus während der Eingabe gewechselt; Eingabe unterbrochen.')
        self.pc.type_unicode(text,verify)
        return f'{len(text)} Unicode-Zeichen an das ausgewählte Fenster gesendet.'

    def action_pc_hotkey(self,keys):
        if not isinstance(keys,str):
            raise ValueError('Ungültige Tastenkombination.')
        parts=[part.strip().lower() for part in keys.split('+')]
        allowed={'ctrl','alt','shift','win','enter','esc','tab','space','backspace','delete',
                 'up','down','left','right','home','end','pageup','pagedown'}
        allowed.update(chr(c) for c in range(ord('a'),ord('z')+1))
        allowed.update(str(c) for c in range(10))
        allowed.update(f'f{n}' for n in range(1,13))
        if len(parts)>4 or not all(part in allowed for part in parts):
            raise ValueError('Tastenkombination enthält ungültige oder zu viele Tasten.')
        target=self._pc_target()
        self._request('Tastenkombination senden',f"Fenster: {target['title']}\nTasten: {' + '.join(parts)}")
        self._pc_activate_and_check()
        self._check()
        self.pc.hotkey(parts)
        return 'Tastenkombination gesendet.'

    def action_pc_click(self,x,y):
        if type(x) is not int or type(y) is not int:
            raise ValueError('Bildschirmkoordinaten müssen ganze Zahlen sein.')
        target=self._pc_target()
        left,top,right,bottom=target['rect']
        if not (left<=x<right and top<=y<bottom):
            raise ValueError('Mausklick außerhalb des ausgewählten Fensters gesperrt.')
        self._request('Mausklick im ausgewählten Fenster',
                      f"Fenster: {target['title']}\nPosition: {x}, {y}")
        target=self._pc_activate_and_check()
        left,top,right,bottom=target['rect']
        if not (left<=x<right and top<=y<bottom):
            raise ValueError('Fenster wurde verschoben, Klick abgebrochen.')
        self._check()
        self.pc.click(x,y)
        return 'Mausklick ausgeführt.'

    def action_selfdev_prepare(self):
        return self.selfdev.prepare()

    def action_selfdev_review(self):
        return self.selfdev.review()['report']

    def action_selfdev_validate(self):
        return self.selfdev.validate()

    def action_selfdev_stage(self):
        return self.selfdev.stage()

    def action_extension_list(self):
        return json.dumps([{'name':e['name'],'description':e['description']}
                           for e in self.extensions.list()],ensure_ascii=False)

    def action_extension_install(self,name):
        # Local candidate must be within workspace; no side-loading arbitrary files.
        candidate=self._path('extension_candidates/'+str(name))
        info=self.extensions.candidate(candidate,name)
        self._request('Neue Erweiterung installieren',
            f"{info['name']} – {info['description']}\nSHA256: {info['sha256']}\n"
            'Dies installiert ausführbaren Python-Code. Spätere Ausführung erfordert erneut eine Freigabe.')
        self.extensions.install(candidate,name)
        return 'Erweiterung installiert: '+name+'. Änderungen werden erst bei einer erneuten Anfrage sichtbar.'

    def action_gmail_connect(self):
        self._request('Gmail verknüpfen','Der Google-OAuth-Anmeldeprozess öffnet einen Browser. '
                      'Dein Passwort wird nicht an SYTOX übergeben. Erteile nur gewünschte Berechtigungen.')
        return self.gmail.connect()

    def action_gmail_search(self,query):
        return json.dumps(self.gmail.search(query),ensure_ascii=False)

    def action_gmail_read(self,message_id):
        # External content is untrusted and must remain data, not system instructions.
        return json.dumps(self.gmail.read(message_id),ensure_ascii=False)

    def action_gmail_draft(self,to,subject,body):
        return json.dumps(self.gmail.draft(to,subject,body),ensure_ascii=False)

    def action_gmail_send(self,to,subject,body):
        self._request('E-Mail wirklich versenden?',
            f'AN: {to}\nBETREFF: {subject}\n\nTEXT:\n{body[:5000]}\n\n'
            'Diese Freigabe gilt nur für diese konkrete Nachricht.')
        return json.dumps(self.gmail.send(to,subject,body),ensure_ascii=False)
