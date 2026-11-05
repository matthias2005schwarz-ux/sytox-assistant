"""Real Windows compiler/syntax-check smoke tests for eight more languages."""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sytox.actions import Toolkit
from sytox.program_build import build_plan, inspect_build_artifact

SAMPLES = {
    'c': {'main.c': '#include <stdio.h>\nint main(void){puts("SYTOX_EXTRA_C");return 0;}\n'},
    'cpp': {'main.cpp': '#include <iostream>\nint main(){std::cout<<"SYTOX_EXTRA_CPP"<<std::endl;}\n'},
    'java': {'Main.java': 'public class Main { public static void main(String[] a) { System.out.println("SYTOX_EXTRA_JAVA"); } }\n'},
    'kotlin': {'Main.kt': 'fun main() { println("SYTOX_EXTRA_KOTLIN") }\n'},
    'javascript': {'main.js': 'console.log("SYTOX_EXTRA_JAVASCRIPT");\n'},
    'typescript': {'main.ts': 'const marker: string = "SYTOX_EXTRA_TYPESCRIPT"; console.log(marker);\n'},
    'php': {'main.php': '<?php echo "SYTOX_EXTRA_PHP\\n";\n'},
    'lua': {'main.lua': 'print("SYTOX_EXTRA_LUA")\n'},
}


def run_one(root: Path, language: str, files: dict[str, str]) -> None:
    workspace = root / language
    workspace.mkdir()
    for name, source in files.items():
        file = workspace / name
        file.write_text(source, encoding='utf-8')
    plan = build_plan(workspace)
    if plan['language'] != language:
        raise AssertionError(f'Wrong language: {plan}')
    toolkit = object.__new__(Toolkit)
    toolkit.workspace = workspace.resolve()
    toolkit.approval = lambda *_: True  # Synthetic, nonuser CI project.
    toolkit.stop_event = None
    toolkit.built_artifacts = []
    toolkit.passed_checks = 0
    toolkit.writes = 1
    toolkit.unvalidated_paths = set(files)
    outcome = json.loads(toolkit.action_project_build())
    receipt = outcome['artifact']
    if not receipt['format_valid'] or not toolkit.verified_builds():
        raise AssertionError(f'{language}: no verified build output')
    if receipt['runtime_tested']:
        raise AssertionError('Unexecuted output must not claim runtime success')
    artifact = inspect_build_artifact(workspace, receipt['path'], plan['artifact_kind'])
    if artifact['sha256'] != receipt['sha256']:
        raise AssertionError(f'{language}: unexpected change')
    if language in ('javascript', 'php') and outcome['build'] != 'validated':
        raise AssertionError('Script syntax-check must not count as native compilation')
    if language in ('c', 'cpp') and receipt['format'] != 'Windows PE x64':
        raise AssertionError('C/C++ output was not Windows x64')
    args = [(str(workspace / part) if part.endswith('.exe') else part)
            for part in plan['runtime_command']]
    result = subprocess.run(args, cwd=workspace, capture_output=True,
                            text=True, timeout=45, errors='replace')
    marker = 'SYTOX_EXTRA_' + language.upper()
    if result.returncode != 0 or marker not in result.stdout:
        raise AssertionError(
            f'{language} did not launch: exit={result.returncode}, '
            f'stdout={result.stdout[-600:]}, stderr={result.stderr[-600:]}')
    print(f'PASS {language}: artifact/sha256 + actual runtime', flush=True)


def main() -> None:
    if platform.system() != 'Windows':
        raise RuntimeError('Windows-only integration test')
    with tempfile.TemporaryDirectory(prefix='sytox_extra_builds_') as tmp:
        for language, sample in SAMPLES.items():
            print('Testing ' + language, flush=True)
            run_one(Path(tmp), language, sample)
    print('PASS all eight additional language workflows', flush=True)


if __name__ == '__main__':
    main()
