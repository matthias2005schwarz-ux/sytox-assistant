"""Deterministic Windows builds for simple C/C++, JVM and scripting projects.

Project commands are never executed here. Toolkit obtains explicit approval,
then invokes commands without a shell and checks the resulting artifact.
This is a bounded single-entry-point workflow, not a general build system.
"""
from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path


# Only these exact entry names are accepted. No user-controlled command lines.
ENTRY_POINTS = (
    ('cpp', 'main.cpp'), ('c', 'main.c'), ('java', 'Main.java'),
    ('kotlin', 'Main.kt'), ('typescript', 'main.ts'),
    ('javascript', 'main.js'), ('php', 'main.php'), ('lua', 'main.lua'),
)
MAX_SCRIPT_SIZE = 16 * 1024 * 1024


def _command(*alternatives: str) -> str:
    for name in alternatives:
        path = shutil.which(name)
        if path and 'windowsapps' not in path.lower():
            return path
    raise RuntimeError('Benötigtes Entwicklungswerkzeug fehlt: ' + ' / '.join(alternatives)
                       + '. Bitte toolchain_inspect verwenden.')


def extra_plan(root: Path) -> dict | None:
    """Read-only inspection: exactly one of eight supported main files."""
    root = Path(root).resolve()
    found = [
        (language, filename)
        for language, filename in ENTRY_POINTS
        if (root / filename).is_file() and not (root / filename).is_symlink()
    ]
    if not found:
        return None
    if len(found) != 1:
        raise ValueError('Mehrere mögliche Startdateien gefunden; bitte Projekt eindeutig machen.')
    language, name = found[0]
    copy_after = None
    if language in ('c', 'cpp'):
        compiler = _command(('gcc' if language == 'c' else 'g++'),
                            ('clang' if language == 'c' else 'clang++'))
        command = [compiler, name, '-O2', '-o', 'build_output/SYTOX_Program.exe']
        expected = 'build_output/SYTOX_Program.exe'
        kind = 'pe'
        runtime = ['build_output/SYTOX_Program.exe']
    elif language == 'java':
        command = [_command('javac'), '-d', 'build_output', name]
        expected, kind = 'build_output/Main.class', 'class'
        runtime = [_command('java'), '-cp', 'build_output', 'Main']
    elif language == 'kotlin':
        command = [_command('kotlinc'), name, '-include-runtime', '-d',
                   'build_output/SYTOX_Program.jar']
        expected, kind = 'build_output/SYTOX_Program.jar', 'jar'
        runtime = [_command('java'), '-jar', expected]
    elif language == 'typescript':
        tsc = shutil.which('tsc') or str(root / 'node_modules' / '.bin' / 'tsc.cmd')
        if not Path(tsc).is_file() and not shutil.which('tsc'):
            raise RuntimeError('TypeScript-Compiler tsc fehlt. Bitte toolchain_inspect verwenden.')
        command = [tsc, name, '--outDir', 'build_output', '--target', 'ES2020',
                   '--module', 'commonjs', '--skipLibCheck']
        expected, kind = 'build_output/main.js', 'script_js'
        runtime = [_command('node'), expected]
    elif language == 'javascript':
        command = [_command('node'), '--check', name]
        expected, kind = 'build_output/main.js', 'script_js'
        copy_after = name
        runtime = [_command('node'), expected]
    elif language == 'php':
        command = [_command('php'), '-l', name]
        expected, kind = 'build_output/main.php', 'script_php'
        copy_after = name
        runtime = [_command('php'), expected]
    else:
        command = [_command('luac'), '-o', 'build_output/main.luac', name]
        expected, kind = 'build_output/main.luac', 'lua_bytecode'
        runtime = [_command('lua'), expected]

    return {
        'language': language, 'command': command,
        'expected_artifact': expected, 'artifact_kind': kind,
        'copy_after_validation': copy_after,
        'runtime_command': runtime,
        'requires_approval': True,
        'note': ('Nur einfaches Einzeldatei-Projekt. C/C++ erzeugt Windows-x64-EXE. '
                 'Java/Kotlin erzeugen JVM-Bytecode/JAR; JavaScript/TypeScript/PHP/Lua '
                 'werden syntaktisch geprüft bzw. übersetzt und benötigen ihre Laufzeit. '
                 'Alle Build-Ausführungen benötigen eine ausdrückliche Freigabe.'),
    }


def check_artifact(workspace: Path, relative_path: str, kind: str) -> dict:
    """Verify content and compute a hash without executing arbitrary output."""
    root = Path(workspace).resolve()
    if not isinstance(relative_path, str) or len(relative_path) > 350:
        raise ValueError('Ungültiger Artefaktpfad.')
    file = (root / relative_path).resolve()
    if file == root or root not in file.parents or file.is_symlink():
        raise ValueError('Artefaktpfad liegt außerhalb des Projekts oder ist ein Link.')
    if not file.is_file():
        raise FileNotFoundError('Erwartetes Build-Artefakt fehlt.')
    size = file.stat().st_size
    if not 4 <= size <= 1_200_000_000:
        raise ValueError('Ungültige Build-Artefaktgröße.')
    with file.open('rb') as stream:
        header = stream.read(128)
    if kind == 'class' and (file.suffix != '.class' or header[:4] != b'\xca\xfe\xba\xbe'):
        raise ValueError('Keine JVM-Class-Datei.')
    elif kind == 'jar':
        if file.suffix != '.jar' or not zipfile.is_zipfile(file):
            raise ValueError('Keine gültige JAR-Datei.')
        with zipfile.ZipFile(file) as jar:
            if 'META-INF/MANIFEST.MF' not in jar.namelist():
                raise ValueError('JAR-Manifest fehlt.')
    elif kind == 'lua_bytecode' and (file.suffix != '.luac' or header[:4] != b'\x1bLua'):
        raise ValueError('Kein Lua-Bytecode.')
    elif kind == 'script_js' and file.suffix != '.js':
        raise ValueError('Erwartete JavaScript-Datei fehlt.')
    elif kind == 'script_php' and file.suffix != '.php':
        raise ValueError('Erwartete PHP-Datei fehlt.')
    if kind in ('script_js', 'script_php') and size > MAX_SCRIPT_SIZE:
        raise ValueError('Skript ist zu groß.')
    digest = hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return {
        'path': file.relative_to(root).as_posix(), 'size_bytes': size,
        'sha256': digest.hexdigest(), 'format_valid': True,
        'format': {
            'class': 'JVM class', 'jar': 'JVM JAR', 'lua_bytecode': 'Lua bytecode',
            'script_js': 'JavaScript', 'script_php': 'PHP script'
        }[kind],
        'artifact_kind': kind,
        'runtime_tested': False,
        'note': 'Ausgabe überprüft, nicht gestartet. Ein Runtime-Test ist separat erforderlich.',
    }
