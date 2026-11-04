"""Safe Windows development-tool detection and curated installation choices.

Discovery never runs programs or installs anything. Installation is handled
separately by Toolkit, with a fresh user approval for the exact winget package.
"""
from __future__ import annotations

import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Toolchain:
    name: str
    commands: tuple[tuple[str, ...], ...]
    package: str | None = None
    note: str = ""


# Only exact, reviewed winget IDs can be installed, never a model-supplied ID.
TOOLCHAINS: dict[str, Toolchain] = {
    "python": Toolchain("Python", (("py", "python", "python3"),), "Python.Python.3.13"),
    "javascript": Toolchain("JavaScript", (("node",), ("npm",)), "OpenJS.NodeJS.LTS"),
    "typescript": Toolchain("TypeScript", (("node",), ("npm",), ("tsc",)),
                            "OpenJS.NodeJS.LTS",
                            "TypeScript selbst muss zusätzlich projektbezogen über npm installiert werden."),
    "csharp": Toolchain("C#", (("dotnet",),), "Microsoft.DotNet.SDK.10"),
    "java": Toolchain("Java", (("javac",),), "EclipseAdoptium.Temurin.21.JDK"),
    "c": Toolchain("C", (("clang", "gcc", "cl"),), "LLVM.LLVM",
                   "Unter Windows können für vollständige EXE-Builds zusätzliche Linker/SDKs nötig sein."),
    "cpp": Toolchain("C++", (("clang++", "g++", "cl"),), "LLVM.LLVM",
                     "Unter Windows können für vollständige EXE-Builds zusätzliche Linker/SDKs nötig sein."),
    "go": Toolchain("Go", (("go",),), "GoLang.Go"),
    "rust": Toolchain("Rust", (("rustc",), ("cargo",)), "Rustlang.Rustup",
                      "Nach rustup können noch Rust-Toolchains bzw. C++ Build Tools nötig sein."),
    "php": Toolchain("PHP", (("php",),)),
    "lua": Toolchain("Lua", (("lua",),)),
    "kotlin": Toolchain("Kotlin", (("kotlinc",), ("javac",))),
}

ALIASES = {
    "c#": "csharp", "cs": "csharp", "c-sharp": "csharp", ".net": "csharp",
    "c++": "cpp", "cplusplus": "cpp", "c plus plus": "cpp",
    "js": "javascript", "node": "javascript", "ts": "typescript",
    "py": "python", "golang": "go", "rs": "rust", "kt": "kotlin",
}

EXTENSIONS = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".cs": "csharp", ".java": "java", ".c": "c", ".cpp": "cpp",
    ".cc": "cpp", ".cxx": "cpp", ".go": "go", ".rs": "rust",
    ".php": "php", ".lua": "lua", ".kt": "kotlin",
}
MARKERS = (
    ("tsconfig.json", "typescript"), ("Cargo.toml", "rust"),
    ("go.mod", "go"), ("pom.xml", "java"), ("build.gradle", "java"),
    ("build.gradle.kts", "kotlin"), ("CMakeLists.txt", "cpp"),
    ("package.json", "javascript"), ("pyproject.toml", "python"),
)
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "dist", "build",
    "__pycache__", ".idea", ".vs", "target", "vendor", ".next",
}


def canonical_language(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Ungültige Programmiersprache.")
    key = value.strip().lower()
    key = ALIASES.get(key, key)
    if key not in TOOLCHAINS:
        raise ValueError("Unbekannte Programmiersprache. Zulässig: " +
                         ", ".join(TOOLCHAINS))
    return key


def _executable(name: str) -> str | None:
    path = shutil.which(name)
    if path and name in ("python", "python3") and "windowsapps" in path.lower():
        # Windows App Execution Alias can be a Microsoft Store stub.
        return None
    return path


def status(language: str, workspace: Path | None = None) -> dict:
    key = canonical_language(language)
    spec = TOOLCHAINS[key]
    found, missing = [], []
    for alternatives in spec.commands:
        executable = next(((name, path) for name in alternatives
                           if (path := _executable(name))), None)
        if executable:
            found.append(executable[0])
        elif key == "typescript" and "tsc" in alternatives and workspace is not None and (
                (Path(workspace) / "node_modules" / ".bin" / "tsc.cmd").is_file()
                or (Path(workspace) / "node_modules" / ".bin" / "tsc").is_file()):
            found.append("tsc (projektlokal)")
        else:
            missing.append(" oder ".join(alternatives))
    return {
        "language": key, "name": spec.name, "ready": not missing,
        "found": found, "missing": missing,
        "winget_id": spec.package, "note": spec.note,
    }


def project_language(workspace: Path) -> str | None:
    """Bounded scan; never follow symlinks or inspect file contents."""
    root = Path(workspace)
    if not root.is_dir():
        return None
    counts: Counter[str] = Counter()
    seen = 0
    for dirname, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS
                   and not (Path(dirname) / d).is_symlink()]
        seen += 1
        if seen > 70:
            break
        for filename in files[:200]:
            if (Path(dirname) / filename).is_symlink():
                continue
            for marker, lang in MARKERS:
                if filename == marker:
                    counts[lang] += 7
            if filename.endswith(".csproj") or filename.endswith(".sln"):
                counts["csharp"] += 7
            lang = EXTENSIONS.get(Path(filename).suffix.lower())
            if lang:
                counts[lang] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def requested_language(task: str) -> str | None:
    if not isinstance(task, str):
        return None
    lower = task.lower()[:1000]
    expressions = (
        (r"c\+\+|unreal", "cpp"),
        (r"c#|c-sharp|\.net|unity", "csharp"),
        (r"\btypescript\b", "typescript"),
        (r"\bjavascript\b|\bnode\.?js\b", "javascript"),
        (r"\bpython\b|\bpyside\b", "python"),
        (r"\bphp\b|pocketmine", "php"),
        (r"\bkotlin\b", "kotlin"),
        (r"\brust\b", "rust"),
        (r"\bgolang\b|\bgo sprache\b", "go"),
        (r"\blua\b", "lua"),
        (r"\bjava\b", "java"),
        (r"\bc sprache\b", "c"),
    )
    for pattern, language in expressions:
        if re.search(pattern, lower):
            return language
    return None


def propose(task: str, workspace: Path) -> dict:
    """Provide a recommendation; never claim a program has been built."""
    explicit = requested_language(task)
    existing = project_language(workspace)
    lower = (task if isinstance(task, str) else "").lower()
    if explicit:
        choice, reason = explicit, "Programmiersprache aus dem Auftrag erkannt"
    elif existing:
        choice, reason = existing, "vorhandene Projektstruktur erkannt"
    elif "minecraft" in lower:
        choice, reason = "java", "Minecraft-Plugin ohne weitere Serverangaben"
    elif any(term in lower for term in ("windows", "desktop", "exe", "winforms", "wpf")):
        choice, reason = "csharp", "native Windows-Anwendung"
    elif any(term in lower for term in ("webseite", "website", "webapp", "frontend", "browser")):
        choice, reason = "javascript", "Webanwendung"
    else:
        choice, reason = "python", "allgemeine Automatisierung oder Anwendung"
    return {
        "recommendation": choice, "reason": reason,
        "existing_project_language": existing,
        "toolchain": status(choice, workspace),
        "supported_languages": list(TOOLCHAINS),
        "windows_package_manager": bool(_executable("winget")),
        "instructions": (
            "Fehlende Compiler nur mit toolchain_install und gesonderter Nutzerfreigabe "
            "einrichten. Danach erneut prüfen. Auch bei vorhandener Toolchain müssen "
            "Build und Tests separat ausgeführt und überprüft werden."
        ),
    }
