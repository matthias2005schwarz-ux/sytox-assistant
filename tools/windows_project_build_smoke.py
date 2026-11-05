"""Windows end-to-end check: compile actual user-style projects, validate and launch EXEs.

Each program is intentionally tiny, writes only inside TemporaryDirectory, and
exits immediately with a fixed marker. No untrusted repository projects are run.
This test exercises Toolkit.action_project_build, not a mocked compiler.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sytox.actions import Toolkit  # noqa: E402
from sytox.program_build import build_plan, inspect_windows_executable  # noqa: E402


SAMPLES = {
    "python": {
        "main.py": "print('SYTOX_REAL_BUILD_PYTHON')\n",
    },
    "csharp": {
        "Hello.csproj": (
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            '  <PropertyGroup>\n'
            '    <OutputType>Exe</OutputType>\n'
            '    <TargetFramework>net10.0</TargetFramework>\n'
            '    <UseAppHost>true</UseAppHost>\n'
            '  </PropertyGroup>\n'
            '</Project>\n'
        ),
        "Program.cs": 'System.Console.WriteLine("SYTOX_REAL_BUILD_CSHARP");\n',
    },
    "go": {
        "go.mod": "module example.org/sytox-example\n\ngo 1.24\n",
        "main.go": (
            'package main\n'
            'import "fmt"\n'
            'func main() { fmt.Println("SYTOX_REAL_BUILD_GO") }\n'
        ),
    },
    "rust": {
        "Cargo.toml": (
            '[package]\n'
            'name = "sytox_example"\n'
            'version = "0.1.0"\n'
            'edition = "2021"\n'
        ),
        "src/main.rs": 'fn main() { println!("SYTOX_REAL_BUILD_RUST"); }\n',
    },
}


def check_project(root: Path, language: str, files: dict[str, str]) -> None:
    workspace = root / language
    workspace.mkdir()
    for relative_path, source in files.items():
        target = workspace / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")

    plan = build_plan(workspace)
    if plan["language"] != language:
        raise AssertionError(f"{language}: wrong detected language: {plan!r}")

    agent = object.__new__(Toolkit)
    agent.workspace = workspace.resolve()
    agent.approval = lambda *_: True  # CI-only synthetic project; no user data
    agent.stop_event = None
    agent.built_artifacts = []
    agent.unvalidated_paths = set(files)
    agent.passed_checks = 0
    agent.writes = len(files)

    built = json.loads(agent.action_project_build())
    if built["build"] != "compiled":
        raise AssertionError(f"{language}: build was not marked compiled")
    receipt = built["artifact"]
    if not receipt["format_valid"] or receipt["format"] != "Windows PE x64":
        raise AssertionError(f"{language}: not a genuine x64 PE")
    if receipt["runtime_tested"]:
        raise AssertionError("Build receipt must not claim a runtime test")
    if receipt not in agent.verified_builds() or agent.passed_checks != 1:
        raise AssertionError(f"{language}: build receipt verification failed")
    if len(receipt["sha256"]) != 64:
        raise AssertionError(f"{language}: no SHA-256")

    exe = workspace / receipt["path"]
    if not exe.is_file():
        raise AssertionError(f"{language}: EXE missing after successful build")
    verify = inspect_windows_executable(workspace, receipt["path"])
    if verify["sha256"] != receipt["sha256"]:
        raise AssertionError(f"{language}: EXE hash changed")

    run = subprocess.run(
        [str(exe)],
        cwd=str(exe.parent),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=50,
        check=False,
    )
    marker = "SYTOX_REAL_BUILD_" + language.upper()
    if run.returncode != 0 or marker not in run.stdout:
        raise AssertionError(
            f"{language}: EXE runtime test failed: exit={run.returncode}, "
            f"stdout={run.stdout[-600:]!r}, stderr={run.stderr[-600:]!r}"
        )
    print(f"PASS {language}: compiled + PE x64 + SHA-256 + launched successfully", flush=True)


def main() -> None:
    if platform.system() != "Windows":
        raise SystemExit("This end-to-end smoke test requires Windows")
    with tempfile.TemporaryDirectory(prefix="sytox_real_build_") as temp:
        for language, files in SAMPLES.items():
            print("Checking actual Windows compiler: " + language, flush=True)
            check_project(Path(temp), language, files)
    print("PASS: All four supported project types compiled and ran", flush=True)


if __name__ == "__main__":
    main()
