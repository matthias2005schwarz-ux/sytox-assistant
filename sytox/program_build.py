"""Conservative, consent-first Windows executable build support.

A build plan never executes anything. Actual project builds can run arbitrary
project code and therefore need a fresh user approval. A PE header and checksum
are proof of a generated Windows binary, NOT proof it runs correctly.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import struct
from pathlib import Path

from .toolchains import project_language
from .multilang_build import extra_plan, check_artifact


def needs_compiled_artifact(task: str) -> str:
    """Detect explicit finished-binary requests without matching casual chat."""
    text = str(task or '').lower()
    if re.search(r'\b(installer|installationsdatei|setup\.exe)\b', text):
        return 'installer'
    if re.search(r'\b(?:exe|executables?|ausführbar\w*|windows[- ](?:programm|app|anwendung))\b|\.exe\b', text):
        return 'exe'
    return ''


def _within_workspace(root: Path, path: Path) -> Path:
    root = Path(root).resolve()
    result = path.resolve()
    if result == root or root not in result.parents:
        raise ValueError('Build-Pfad liegt außerhalb des Projektordners.')
    return result


def _python_command() -> str | None:
    """Choose a real Python executable, not the Microsoft Store placeholder.

    'python' is preferred over the py launcher to honour a selected project
    environment and its installed PyInstaller dependencies.
    """
    for name in ('python', 'py'):
        executable = shutil.which(name)
        if executable and 'windowsapps' not in executable.lower():
            return executable
    return None


def build_plan(workspace: Path) -> dict:
    """Generate fixed, reproducible commands for an unambiguous Windows project."""
    root = Path(workspace).resolve()
    if not root.is_dir():
        raise ValueError('Projektordner fehlt.')
    projects = sorted(root.glob('*.csproj')) + sorted(root.glob('*/*.csproj'))
    projects = [p for p in projects if not p.is_symlink()
                and _within_workspace(root, p).is_file()]
    if len(projects) > 1:
        raise ValueError('Mehrere C#-Projekte gefunden. Bitte ein einzelnes Startprojekt wählen.')
    if len(projects) == 1:
        project = projects[0]
        relative = project.relative_to(root).as_posix()
        filename = project.stem + '.exe'
        command = ['dotnet', 'publish', relative, '-c', 'Release', '-r',
                   'win-x64', '--self-contained', 'false', '-o', 'build_output']
        expected = 'build_output/' + filename
        language = 'csharp'
    elif (root / 'go.mod').is_file() and not (root / 'go.mod').is_symlink():
        language = 'go'
        command = ['go', 'build', '-o', 'build_output/SYTOX_Program.exe', '.']
        expected = 'build_output/SYTOX_Program.exe'
    elif (root / 'Cargo.toml').is_file() and not (root / 'Cargo.toml').is_symlink():
        import tomllib
        metadata = tomllib.loads((root / 'Cargo.toml').read_text(encoding='utf-8'))
        name = str(metadata.get('package', {}).get('name', ''))
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,80}', name):
            raise ValueError('Rust-Paketname fehlt oder ist ungültig.')
        language = 'rust'
        command = ['cargo', 'build', '--release']
        expected = 'target/release/' + name + '.exe'
    elif (root / 'main.py').is_file() and not (root / 'main.py').is_symlink():
        language = 'python'
        python = _python_command()
        if not python:
            raise RuntimeError('Python fehlt. Erst toolchain_inspect aufrufen.')
        command = [python, '-m', 'PyInstaller', '--noconfirm', '--onedir',
                   '--distpath', 'build_output', '--workpath', 'build_work',
                   '--specpath', 'build_work', '--name', 'SYTOX_Program', 'main.py']
        expected = 'build_output/SYTOX_Program/SYTOX_Program.exe'
    elif (root / 'app.py').is_file() and not (root / 'app.py').is_symlink():
        language = 'python'
        python = _python_command()
        if not python:
            raise RuntimeError('Python fehlt. Erst toolchain_inspect aufrufen.')
        command = [python, '-m', 'PyInstaller', '--noconfirm', '--onedir',
                   '--distpath', 'build_output', '--workpath', 'build_work',
                   '--specpath', 'build_work', '--name', 'SYTOX_Program', 'app.py']
        expected = 'build_output/SYTOX_Program/SYTOX_Program.exe'
    else:
        extended = extra_plan(root)
        if extended is not None:
            return extended
        detected = project_language(root)
        raise ValueError(
            'Für diese Projektstruktur gibt es noch keinen automatisierten Einzelprojekt-Build. '
            f'Erkannt: {detected or "unbekannt"}. Komplexere Projekte benötigen '
            'projektspezifische Compilerbefehle und Tests.')

    output = _within_workspace(root, root / expected)
    return {
        'language': language,
        'command': command,
        'expected_executable': output.relative_to(root).as_posix(),
        'requires_approval': True,
        'note': ('Ein Build kann beliebigen Projektcode ausführen und Abhängigkeiten '
                 'nachladen. Der Installer ist NICHT enthalten. Ein PE-Formatcheck '
                 'ersetzt keinen Start- oder Funktionstest.'),
    }


def inspect_windows_executable(workspace: Path, relative_path: str) -> dict:
    """Read, bound and hash an existing PE file, without executing it."""
    root = Path(workspace).resolve()
    if not isinstance(relative_path, str) or len(relative_path) > 350:
        raise ValueError('Ungültiger EXE-Pfad.')
    if not relative_path.lower().endswith('.exe'):
        raise ValueError('Erwartete Datei ist keine .exe.')
    file = _within_workspace(root, root / relative_path)
    if not file.is_file() or file.is_symlink():
        raise FileNotFoundError('Erwartete Windows-EXE fehlt oder ist ein Link.')
    size = file.stat().st_size
    if size < 512 or size > 1_200_000_000:
        raise ValueError('EXE-Dateigröße außerhalb der Prüflimits.')
    with file.open('rb') as stream:
        header = stream.read(8192)
    if header[:2] != b'MZ' or len(header) < 0x40:
        raise ValueError('Keine gültige Windows-PE-Datei (MZ fehlt).')
    offset = struct.unpack_from('<I', header, 0x3c)[0]
    if offset < 0x40 or offset + 26 > len(header) or header[offset:offset+4] != b'PE\0\0':
        raise ValueError('Windows-PE-Header fehlt oder ist beschädigt.')
    machine = struct.unpack_from('<H', header, offset + 4)[0]
    magic = struct.unpack_from('<H', header, offset + 24)[0]
    if machine != 0x8664 or magic != 0x20b:
        raise ValueError('Es wurde keine Windows-x64-EXE erkannt.')
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {
        'path': file.relative_to(root).as_posix(),
        'size_bytes': size,
        'sha256': digest.hexdigest(),
        'format': 'Windows PE x64',
        'format_valid': True,
        'runtime_tested': False,
        'note': 'Datei und PE-Header geprüft, aber nicht gestartet oder funktional getestet.',
    }

def inspect_build_artifact(workspace: Path, relative_path: str, kind='pe') -> dict:
    """Verify an exact output format. Never mistake a script for a native EXE."""
    if kind == 'pe':
        return inspect_windows_executable(workspace, relative_path)
    if kind not in ('class', 'jar', 'lua_bytecode', 'script_js', 'script_php'):
        raise ValueError('Unbekanntes Build-Artefaktformat.')
    return check_artifact(workspace, relative_path, kind)
