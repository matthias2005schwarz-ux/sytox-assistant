"""Windows/app error diagnosis and narrowly scoped autonomous repairs.

Diagnosis is read-only. Repairs use fixed, reviewed Windows commands or
well-known Microsoft WinGet packages, never arbitrary model-supplied URLs,
executables, command flags, or package IDs. Each mutation uses the existing
SYTOX approval gate and verifies its result. UAC is never bypassed.
"""
from __future__ import annotations

import ctypes
import json
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Callable


class WindowsRepairError(RuntimeError):
    pass


# Exact Microsoft packages in the community WinGet catalog.
# Never construct package identifiers from untrusted model text.
PACKAGES = {
    "vc_redist_x64": ("Microsoft.VCRedist.2015+.x64",
                      "Microsoft Visual C++ Runtime 2015+ (64 Bit)"),
    "vc_redist_x86": ("Microsoft.VCRedist.2015+.x86",
                      "Microsoft Visual C++ Runtime 2015+ (32 Bit)"),
    "dotnet_desktop_8": ("Microsoft.DotNet.DesktopRuntime.8",
                         "Microsoft .NET Desktop Runtime 8"),
    "dotnet_desktop_9": ("Microsoft.DotNet.DesktopRuntime.9",
                         "Microsoft .NET Desktop Runtime 9"),
    "dotnet_desktop_10": ("Microsoft.DotNet.DesktopRuntime.10",
                          "Microsoft .NET Desktop Runtime 10"),
}
SYSTEM_REPAIRS = {
    "system_files": ("sfc.exe", ["/scannow"],
                     "Windows-Systemdateien mit SFC prüfen und reparieren"),
    "component_store": ("dism.exe", ["/Online", "/Cleanup-Image", "/RestoreHealth"],
                        "Windows-Komponentenspeicher mit DISM reparieren"),
}
KNOWN_FIX_IDS = tuple(PACKAGES) + tuple(SYSTEM_REPAIRS)
ERROR_CODE = re.compile(r"\b0x[0-9a-fA-F]{8}\b")
_RECOMMENDATIONS = (
    (re.compile(r"\b(?:vcruntime140(?:_1)?|msvcp140|concrt140|api-ms-win-crt)[\w.-]*\b",
                re.IGNORECASE),
     "Die Meldung deutet auf fehlende Visual-C++-Laufzeitdateien hin. "
     "Die benötigte Architektur muss geprüft werden.",
     ("vc_redist_x64", "vc_redist_x86")),
    (re.compile(r"\b(?:hostfxr\.dll|hostpolicy\.dll|dotnet desktop runtime)\b",
                re.IGNORECASE),
     "Eine .NET-Laufzeit könnte fehlen. Version und Architektur aus der Fehlermeldung "
     "bestimmen, bevor ein bestimmtes Runtime-Paket installiert wird.", ()),
    (re.compile(r"\b0xc000007b\b", re.IGNORECASE),
     "Eine mögliche Ursache ist eine 32-/64-Bit-Inkompatibilität oder eine defekte "
     "Abhängigkeit. Nicht ohne weitere Prüfung irgendeine DLL nachinstallieren.", ()),
    (re.compile(r"\b0xc0000135\b", re.IGNORECASE),
     "Eine benötigte Laufzeitkomponente könnte fehlen. Genauen Modulnamen "
     "und Programmarchitektur ermitteln.", ()),
    (re.compile(r"\b0xc0000005\b", re.IGNORECASE),
     "Zugriffsverletzung der Anwendung. Mögliche Ursachen sind App-Bugs, "
     "Treiber oder beschädigte Daten. Kein sicherer pauschaler Fix.", ()),
    (re.compile(r"\b0x80070005\b", re.IGNORECASE),
     "Zugriff verweigert: Berechtigungen, Dienststatus und betroffene "
     "Datei prüfen. Rechte nicht automatisch erhöhen.", ()),
    (re.compile(r"\b0x80070002\b", re.IGNORECASE),
     "Datei oder Pfad nicht gefunden: genaue Quelle prüfen.", ()),
    (re.compile(r"\b(?:d3dx9_\d+\.dll|xinput1_3\.dll)\b", re.IGNORECASE),
     "Möglicherweise fehlt eine ältere DirectX-Komponente. Nur die "
     "offizielle Microsoft-Laufzeit passend zum Programm verwenden.", ()),
)


def identify_error(text: str) -> dict:
    """Explain known patterns without inventing a deterministic repair."""
    if not isinstance(text, str) or len(text) > 6000:
        raise ValueError("Fehlermeldung muss Text mit höchstens 6000 Zeichen sein.")
    codes = list(dict.fromkeys(c.lower() for c in ERROR_CODE.findall(text)))[:12]
    suggestions, fixes = [], []
    for pattern, hint, candidates in _RECOMMENDATIONS:
        if pattern.search(text):
            suggestions.append(hint)
            for candidate in candidates:
                if candidate not in fixes:
                    fixes.append(candidate)
    if not suggestions:
        suggestions = [
            "Noch keine verlässliche Ursache erkennbar. Exakten Fehlertext, "
            "betroffenes Programm und Ereignisprotokoll prüfen. Keine "
            "Software auf Verdacht herunterladen."
        ]
    return {
        "codes": codes, "interpretation": suggestions,
        "possible_repairs_not_yet_verified": fixes,
        "repair_options": list(KNOWN_FIX_IDS),
        "caution": "Vorschläge sind Hypothesen, keine bestätigte Diagnose. "
                   "Systemeingriffe benötigen vorab die Nutzerfreigabe.",
    }



# Shared with the quick-conversation model: it can diagnose and safely repair
# the same operating-system errors without switching to the larger code model.
_WINDOWS_HELP = re.compile(
    r"\\b(?:0x[0-9a-f]{8}|0x800[0-9a-f]{5}|\\w+\\.dll|"
    r"fehler(?:code|meldung)?|error(?:\\s*code)?|absturz|"
    r"stürzt\\s+ab|funktioniert\\s+nicht|startet\\s+nicht|"
    r"reparier\\w*|beheb\\w*|fehlende\\s+datei|"
    r"windows[- ]?problem)\\b", re.IGNORECASE
)
_REPAIR_WISH = re.compile(
    r"\\b(?:beheb\\w*|reparier\\w*|fix\\w*|"
    r"installier\\w*|lade\\s+.{0,12}herunter|"
    r"mach\\s+(?:es|das|den\\s+fehler)\\s+(?:wieder\\s+)?(?:heil|weg|ganz)|"
    r"bring\\s+.{0,30}zum\\s+laufen)\\b", re.IGNORECASE
)
_REPAIR_NEGATION = re.compile(
    r"\\b(?:nicht|niemals|nie|ohne|keine?)\\b.{0,35}"
    r"(?:beheb|reparier|fix|installier|lade|herunter)", re.IGNORECASE
)


def wants_windows_diagnosis(text: str) -> bool:
    """Recognize a support request, without creating a second chat mode."""
    return bool(_WINDOWS_HELP.search(str(text or "")[:6000]))


def asks_for_repair(text: str) -> bool:
    """A question about a fix is not permission to install something."""
    phrase = str(text or "")[:1500]
    if any(marker in phrase.casefold() for marker in (
        "wie kann ich", "was bedeutet", "was würde", "wenn ich sage", "zum beispiel",
        "wie repariert man", "erklär mir", "erkläre mir",
    )):
        return False
    return bool(_REPAIR_WISH.search(phrase)) and not bool(_REPAIR_NEGATION.search(phrase))


def choose_unambiguous_fix(error_text: str) -> str | None:
    """Never guess architecture from a model answer or from Windows bitness.

    Some 64-bit systems still run 32-bit programs. For VC++ packages, require
    a concrete missing runtime DLL AND an explicit architecture in evidence.
    Unknown codes and generic access violations cannot authorize a download.
    """
    text = str(error_text or "")[:6000].lower()
    if not re.search(r"\\b(?:vcruntime140(?:_1)?|msvcp140|concrt140|api-ms-win-crt)[\\w.-]*\\b",
                     text):
        return None
    is_x64 = bool(re.search(r"\\b(?:x64|64[ -]?bit|amd64)\\b", text))
    is_x86 = bool(re.search(r"\\b(?:x86|32[ -]?bit|win32)\\b", text))
    if is_x64 == is_x86:
        return None
    return "vc_redist_x64" if is_x64 else "vc_redist_x86"


def _require_windows():
    if platform.system() != "Windows":
        raise WindowsRepairError("Windows-Diagnose und Reparatur sind nur auf Windows verfügbar.")


def _check_stop(stop_event):
    if stop_event is not None and stop_event.is_set():
        raise WindowsRepairError("Aktion vom Benutzer abgebrochen.")


def _command(argv: list[str], timeout: int, stop_event=None) -> tuple[int, str]:
    """Bounded shell-free subprocess with cancellation. Do not execute raw model input."""
    _check_stop(stop_event)
    process = subprocess.Popen(
        argv, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        started = time.monotonic()
        while True:
            if stop_event is not None and stop_event.is_set():
                process.kill()
                process.communicate()
                raise WindowsRepairError(
                    "Abgebrochen; bereits gestartete separate Installer können weiterlaufen."
                )
            if time.monotonic() - started > timeout:
                process.kill()
                process.communicate()
                raise WindowsRepairError("Zeitlimit für Windows-Aktion überschritten.")
            try:
                output, _ = process.communicate(timeout=0.5)
                return process.returncode, output[-9000:]
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()


_EVENT_SCRIPT = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$items=Get-WinEvent -FilterHashtable "
    "@{LogName='Application';StartTime=(Get-Date).AddHours(-6)} "
    "-ErrorAction SilentlyContinue | "
    "Where-Object {$_.Id -in @(1000,1001,1026,33,59)} | "
    "Select-Object -First 10 TimeCreated,Id,ProviderName,Message;"
    "@($items)|ConvertTo-Json -Compress -Depth 3"
)


def diagnose_windows(error_text: str = "", recent_events: bool = True,
                     stop_event=None, command: Callable = _command) -> dict:
    """Read non-sensitive Windows metadata and recent app failures, no mutations."""
    _require_windows()
    result = identify_error(error_text)
    result["platform"] = platform.platform()
    result["recent_events"] = []
    result["event_status"] = "Nicht angefordert"
    if recent_events:
        powershell = shutil.which("powershell.exe")
        if not powershell:
            result["event_status"] = "Windows PowerShell nicht gefunden"
        else:
            _check_stop(stop_event)
            code, output = command(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", _EVENT_SCRIPT],
                20, stop_event,
            )
            if code:
                result["event_status"] = "Ereignisprotokoll nicht abrufbar (Exitcode "
                result["event_status"] += str(code) + ")"
            else:
                try:
                    parsed = json.loads(output or "[]")
                    if isinstance(parsed, dict):
                        parsed = [parsed]
                    for item in parsed[:10] if isinstance(parsed, list) else []:
                        if isinstance(item, dict):
                            result["recent_events"].append({
                                "id": item.get("Id"),
                                "provider": str(item.get("ProviderName") or "")[:100],
                                "time": str(item.get("TimeCreated") or "")[:80],
                                "details": str(item.get("Message") or "")[:450],
                            })
                    result["event_status"] = "Erfolgreich"
                except (ValueError, TypeError):
                    result["event_status"] = "Ereignisprotokoll antwortete ungültig"
    return result


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _winget() -> str:
    cmd = shutil.which("winget")
    if not cmd:
        raise WindowsRepairError(
            "Windows-Paketmanager winget fehlt. Microsoft App Installer prüfen."
        )
    return cmd


def _installed_package(winget: str, package: str, command, stop_event) -> bool | None:
    code, output = command(
        [winget, "list", "--id", package, "--exact",
         "--disable-interactivity"], 40, stop_event)
    if code:
        return None
    output = output.lower()
    if "no installed package" in output or "kein installiertes paket" in output:
        return False
    return package.lower() in output


def repair_windows(fix_id: str, approve: Callable, stop_event=None,
                   command: Callable = _command) -> dict:
    """One safe repair at a time, with explicit approval and post-install checks."""
    _require_windows()
    if not isinstance(fix_id, str) or fix_id not in KNOWN_FIX_IDS:
        raise ValueError("Unbekannte Reparatur-ID. Nur feste, geprüfte Aktionen erlaubt.")
    _check_stop(stop_event)
    if fix_id in PACKAGES:
        package, title = PACKAGES[fix_id]
        winget = _winget()
        argv = [winget, "install", "--id", package, "--exact",
                "--source", "winget", "--silent",
                "--accept-package-agreements", "--accept-source-agreements",
                "--disable-interactivity", "--no-upgrade"]
        before = _installed_package(winget, package, command, stop_event)
        if before is True:
            return {
                "fix_id": fix_id, "status": "already_installed",
                "detail": "Paket ist laut winget bereits installiert. "
                          "Nur dadurch ist der ursprüngliche Fehler nicht behoben.",
                "verification": "package_present",
            }
        description = (
            "SYTOX wird über den Windows-Paketmanager folgendes Paket "
            "herunterladen und installieren:\n"
            + title + "\nPaket-ID: " + package
            + "\nQuelle: winget (Microsoft-WinGet-Katalog)."
            "\nStille Installation ohne eigenen Download-Link und ohne "
            "deaktivierte Sicherheitsprüfungen."
            "\nWindows kann eine Administratorfreigabe verlangen. "
            "Bei Ablehnung nicht fortfahren."
        )
        if not approve("Windows-Reparatur: " + title, description):
            return {"fix_id": fix_id, "status": "denied",
                    "detail": "Installation vom Benutzer abgelehnt."}
        _check_stop(stop_event)
        code, output = command(argv, 900, stop_event)
        if code:
            return {
                "fix_id": fix_id, "status": "failed",
                "detail": f"winget-Installation meldete Exitcode {code}. "
                          "Keine erfolgreiche Reparatur behaupten.",
                "diagnostic": output[-1400:],
            }
        after = _installed_package(winget, package, command, stop_event)
        return {
            "fix_id": fix_id,
            "status": "package_verified" if after is True else "unverified",
            "detail": "Installation beendet. "
                      + ("Paket in winget erkannt." if after is True else
                         "Paketinstallation noch nicht sicher nachgewiesen."),
            "verification": ("package_present" if after is True else "not_confirmed"),
            "next_step": "Betroffenes Programm erneut starten und ursprüngliche "
                         "Fehlermeldung prüfen; ggf. Windows-Neustart manuell freigeben.",
        }

    executable, args, title = SYSTEM_REPAIRS[fix_id]
    if not _is_admin():
        return {
            "fix_id": fix_id, "status": "needs_admin",
            "detail": "Für diesen Windows-Reparaturbefehl sind Administratorrechte "
                      "erforderlich. Sytox umgeht die Windows-UAC nicht.",
        }
    argv = [executable, *args]
    if not approve("Windows-Systemreparatur: " + title,
                   "Folgender Windows-Systembefehl kann Dateien reparieren "
                   "und Änderungen verursachen:\n"
                   + " ".join(argv)
                   + "\nEs gibt keinen automatischen Neustart und keine UAC-Umgehung."):
        return {"fix_id": fix_id, "status": "denied", "detail": "Nicht freigegeben."}
    _check_stop(stop_event)
    code, output = command(argv, 2400, stop_event)
    return {
        "fix_id": fix_id,
        "status": "command_completed" if code == 0 else "failed",
        "detail": f"Systemreparatur Exitcode {code}. Erfolg des ursprünglichen "
                  "Programms muss noch unabhängig geprüft werden.",
        "diagnostic": output[-1800:],
    }
