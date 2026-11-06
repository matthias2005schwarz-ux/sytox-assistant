"""Actual Windows onedir-file replacement and rollback on an isolated CI runner.

No mocks of the swap, the PyInstaller EXE, or the smoke test. The script uses a
temporary APPDATA profile and a synthetic install with isolated Inno metadata.
It must never run on a real user's machine; it neither installs to Program
Files nor touches registry or the user's existing application.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch

from sytox import portable_update


def main():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        raise RuntimeError("Real update integration test is only allowed on Windows GitHub Actions runners.")

    src = Path("dist/SYTOX_Assistant").resolve()
    if not (src / portable_update.APP_EXE).is_file():
        raise RuntimeError("Build the Windows EXE before testing real updates.")

    with tempfile.TemporaryDirectory(prefix="sytox_update_integration_") as temp:
        root = Path(temp).resolve()
        profile = root / "profile"
        profile.mkdir()
        env = os.environ.copy()
        env["APPDATA"] = str(profile)
        env["QT_QPA_PLATFORM"] = "offscreen"
        old_appdata = os.environ.get("APPDATA")
        old_qt = os.environ.get("QT_QPA_PLATFORM")
        os.environ["APPDATA"] = str(profile)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        processes = []

        def launch_real_exe(exe):
            # Start the actual built application (not --smoke-test) and make
            # sure it remains running through the update grace period.
            p = subprocess.Popen([str(exe), "--background"],
                                 cwd=str(exe.parent), env=env,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            processes.append(p)
            return p

        def close_apps():
            for p in processes:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait(timeout=15)
            processes.clear()

        try:
            from sytox.updater import update_cache_dir
            update_cache = update_cache_dir()
            update_cache.mkdir(parents=True, exist_ok=True)
            stage = update_cache / "sytox-stage-live"
            print("[TEST] Prepare a full, real built onedir package")
            shutil.copytree(src, stage)
            target = root / "Install" / "SYTOX Assistant"
            target.parent.mkdir(parents=True)
            shutil.copytree(src, target)
            (target / "unins000.dat").write_bytes(b"isolated INNO metadata")
            (target / "unins000.exe").write_bytes(b"isolated INNO uninstaller")
            # Representative non-installation data, stored outside install.
            chat = profile / "SytoxAssistant" / "chats_test_preserve.txt"
            chat.parent.mkdir(parents=True, exist_ok=True)
            chat.write_text("keep my chat and Qwen projects", encoding="utf-8")

            print("[TEST] Real filesystem replace, real Windows EXE smoke, real app launch")
            with patch.object(portable_update, "_start", side_effect=launch_real_exe):
                code = portable_update.apply_staged_update(
                    stage, target, smoke_timeout=90, startup_grace=3.0)
            if code != 0:
                raise AssertionError("Successful update had a nonzero return code")
            if (target / portable_update.APP_EXE).read_bytes() != (src / portable_update.APP_EXE).read_bytes():
                raise AssertionError("Installed EXE does not match new package")
            if not (target / "unins000.dat").exists():
                raise AssertionError("Uninstall metadata lost during direct update")
            if not (target.with_name(target.name + portable_update.BACKUP_SUFFIX)
                    / portable_update.APP_EXE).exists():
                raise AssertionError("The previous installed version was not backed up")
            if not any(p.poll() is None for p in processes):
                raise AssertionError("The new Windows EXE did not remain running")
            if chat.read_text(encoding="utf-8") != "keep my chat and Qwen projects":
                raise AssertionError("Direct update changed user data")
            close_apps()

            print("[TEST] Real rollback after a deliberately corrupted new EXE")
            broken_stage = update_cache / "sytox-stage-broken"
            shutil.copytree(src, broken_stage)
            (broken_stage / portable_update.APP_EXE).write_bytes(b"MZ\x00broken-do-not-run")
            before = (target / portable_update.APP_EXE).read_bytes()
            with patch.object(portable_update, "_start", side_effect=launch_real_exe):
                try:
                    portable_update.apply_staged_update(
                        broken_stage, target, smoke_timeout=45, startup_grace=1.0)
                except portable_update.PortableUpdateError as exc:
                    if "rückgängig" not in str(exc):
                        raise
                else:
                    raise AssertionError("Broken EXE incorrectly installed as success")
            if (target / portable_update.APP_EXE).read_bytes() != before:
                raise AssertionError("Failed update did not restore the previous app")
            if chat.read_text(encoding="utf-8") != "keep my chat and Qwen projects":
                raise AssertionError("Failed update changed user data")
            if not (target / "unins000.exe").is_file():
                raise AssertionError("Rollback lost uninstaller")
            print("[OK] Real Windows in-app update + app launch + rollback, data preserved")
        finally:
            close_apps()
            if old_appdata is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = old_appdata
            if old_qt is None:
                os.environ.pop("QT_QPA_PLATFORM", None)
            else:
                os.environ["QT_QPA_PLATFORM"] = old_qt


if __name__ == "__main__":
    main()
