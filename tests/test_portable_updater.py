"""Direct in-app update: download verification, traversal safety and rollback."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import zipfile

from sytox import updater
from sytox import portable_update


class FakeResponse:
    def __init__(self, data, url=None):
        self.data = data
        self.status_code = 200
        self.url = url or ("https://github.com/" + updater.REPOSITORY
                           + "/releases/download/v0.3.9/file")
        self.headers = {"Content-Length": str(len(data))}

    def json(self):
        return self.data

    def raise_for_status(self):
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self.data), chunk_size):
            yield self.data[i:i + chunk_size]


def bundle(filelist=None):
    result = io.BytesIO()
    if filelist is None:
        filelist = {
            "SYTOX_Assistant.exe": b"MZ" + b"new app",
            "_internal/python312.dll": b"test",
        }
    with zipfile.ZipFile(result, "w") as archive:
        for name, data in filelist.items():
            archive.writestr(name, data)
    return result.getvalue()


def portable_info():
    version = "0.3.9"
    base = ("https://github.com/" + updater.REPOSITORY
            + "/releases/download/v" + version + "/")
    name = "SYTOX_Assistant_Portable_" + version + ".zip"
    return updater.UpdateInfo(version, base, "", "", "", base + name,
                              base + name + ".sha256", name)


class PortableMetadataAndArchiveTests(unittest.TestCase):
    def test_new_release_can_have_portable_package_without_installer(self):
        info = portable_info()
        data = {"tag_name": "v0.3.9", "draft": False, "prerelease": False,
                "assets": [{"name": info.portable_filename,
                            "browser_download_url": info.portable_url},
                           {"name": info.portable_filename + ".sha256",
                            "browser_download_url": info.portable_checksum_url}]}
        with patch.object(updater.requests, "get", return_value=FakeResponse(data)):
            found = updater.check_for_update("0.3.8")
        self.assertTrue(found.has_portable)
        self.assertEqual(found.version, "0.3.9")
        self.assertEqual(found.installer_url, "")

    def test_hash_verified_zip_unpack_and_invalid_sha_do_not_replace_files(self):
        binary = bundle()
        info = portable_info()
        sidecar = (hashlib.sha256(binary).hexdigest()
                   + "  " + info.portable_filename).encode()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(updater, "update_cache_dir", return_value=root), \
                 patch.object(updater.requests, "get", side_effect=[
                     FakeResponse(sidecar), FakeResponse(binary)]):
                stage = updater.download_verified_portable(info)
                self.assertTrue((stage / "SYTOX_Assistant.exe").is_file())
                self.assertEqual((stage / "SYTOX_Assistant.exe").read_bytes(),
                                 b"MZnew app")
                self.assertEqual((stage / "_internal" / "python312.dll").read_bytes(),
                                 b"test")
            with patch.object(updater, "update_cache_dir", return_value=root), \
                 patch.object(updater.requests, "get", side_effect=[
                     FakeResponse(sidecar), FakeResponse(b"tampered")]):
                with self.assertRaisesRegex(updater.UpdateError, "SHA-256"):
                    updater.download_verified_portable(info)
            self.assertEqual((stage / "SYTOX_Assistant.exe").read_bytes(),
                             b"MZnew app")
            self.assertFalse(list(root.glob("*.part")))

    def test_reject_zip_slip_and_symlink(self):
        evil = [
            {"../outside.txt": b"no", "SYTOX_Assistant.exe": b"MZ"},
            {"/absolute.txt": b"no", "SYTOX_Assistant.exe": b"MZ"},
            {"C:/bad.exe": b"MZ"},
            {"foo\\escape.exe": b"MZ"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(updater, "update_cache_dir", return_value=root):
                for index, entries in enumerate(evil):
                    archive = root / f"SYTOX_Assistant_Portable_0.3.{index}.zip"
                    archive.write_bytes(bundle(entries))
                    with self.subTest(entries=entries), \
                         self.assertRaises(updater.UpdateError):
                        updater.extract_verified_portable(archive)
                self.assertFalse((root.parent / "outside.txt").exists())
                symlink_archive = root / "SYTOX_Assistant_Portable_0.3.8.zip"
                with zipfile.ZipFile(symlink_archive, "w") as z:
                    entry = zipfile.ZipInfo("SYTOX_Assistant.exe")
                    entry.create_system = 3
                    entry.external_attr = (0o120777 << 16)
                    z.writestr(entry, "target")
                with self.assertRaises(updater.UpdateError):
                    updater.extract_verified_portable(symlink_archive)

    def test_non_executable_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "SYTOX_Assistant_Portable_0.3.9.zip"
            archive.write_bytes(bundle({"SYTOX_Assistant.exe": b"not exe",
                                        "_internal/python312.dll": b"py"}))
            with patch.object(updater, "update_cache_dir", return_value=root):
                with self.assertRaisesRegex(updater.UpdateError, "EXE"):
                    updater.extract_verified_portable(archive)
            self.assertFalse(list(root.glob("sytox-stage-*")))


class TransactionalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.cache = self.root / "updates"
        self.cache.mkdir()
        self.stage = self.cache / "sytox-stage-abc123"
        self.stage.mkdir()
        (self.stage / portable_update.APP_EXE).write_bytes(b"MZnew")
        (self.stage / "_internal").mkdir()
        (self.stage / "_internal" / "lib.dll").write_bytes(b"new library")
        self.target = self.root / "SYTOX Assistant"
        self.target.mkdir()
        (self.target / portable_update.APP_EXE).write_bytes(b"MZold")
        (self.target / "unins000.dat").write_bytes(b"inno metadata")
        (self.target / "unins000.exe").write_bytes(b"uninstaller")
        self.cached = patch("sytox.updater.update_cache_dir", return_value=self.cache)
        self.cached.start()

    def tearDown(self):
        self.cached.stop()
        self.dir.cleanup()

    def test_apply_new_files_preserves_uninstaller_and_saves_old_version(self):
        launch = MagicMock()
        launch.poll.return_value = None
        with patch.object(portable_update.subprocess, "run") as smoke, \
             patch.object(portable_update, "_start", return_value=launch):
            smoke.return_value.returncode = 0
            result = portable_update.apply_staged_update(
                self.stage, self.target, startup_grace=0)
        self.assertEqual(result, 0)
        self.assertEqual((self.target / portable_update.APP_EXE).read_bytes(), b"MZnew")
        self.assertEqual((self.target / "unins000.dat").read_bytes(), b"inno metadata")
        self.assertEqual((self.target / "unins000.exe").read_bytes(), b"uninstaller")
        backup = self.target.with_name(self.target.name + portable_update.BACKUP_SUFFIX)
        self.assertEqual((backup / portable_update.APP_EXE).read_bytes(), b"MZold")
        smoke.assert_called_once()
        self.assertIn("--smoke-test", smoke.call_args.args[0])
        self.assertIn("success", (self.cache / "last_portable_update.json").read_text())

    def test_bad_new_exe_is_rolled_back_and_old_one_restarted(self):
        with patch.object(portable_update.subprocess, "run") as smoke, \
             patch.object(portable_update, "_start") as launch:
            smoke.return_value.returncode = 42
            with self.assertRaisesRegex(portable_update.PortableUpdateError,
                                        "rückgängig"):
                portable_update.apply_staged_update(
                    self.stage, self.target, startup_grace=0)
        self.assertEqual((self.target / portable_update.APP_EXE).read_bytes(), b"MZold")
        self.assertEqual((self.target / "unins000.dat").read_bytes(), b"inno metadata")
        self.assertFalse(self.target.with_name(
            self.target.name + portable_update.BACKUP_SUFFIX).exists())
        launch.assert_called_once()
        self.assertIn("rolled_back", (self.cache / "last_portable_update.json").read_text())

    def test_app_crashes_immediately_after_smoke_test_restores_old_version(self):
        failed_app = MagicMock()
        failed_app.poll.return_value = 23
        failed_app.returncode = 23
        with patch.object(portable_update.subprocess, "run") as smoke, \
             patch.object(portable_update, "_start",
                          side_effect=[failed_app, MagicMock()]) as launch:
            smoke.return_value.returncode = 0
            with self.assertRaisesRegex(portable_update.PortableUpdateError,
                                        "rückgängig"):
                portable_update.apply_staged_update(
                    self.stage, self.target, startup_grace=0.1)
        self.assertEqual(launch.call_count, 2)
        self.assertEqual((self.target / portable_update.APP_EXE).read_bytes(), b"MZold")
        self.assertIn("rolled_back", (self.cache / "last_portable_update.json").read_text())

    def test_copy_error_restores_old_app_without_running_new_exe(self):
        with patch.object(portable_update.shutil, "copytree",
                          side_effect=OSError("disk full")), \
             patch.object(portable_update.subprocess, "run") as smoke, \
             patch.object(portable_update, "_start") as launch:
            with self.assertRaisesRegex(portable_update.PortableUpdateError,
                                        "rückgängig"):
                portable_update.apply_staged_update(
                    self.stage, self.target, startup_grace=0)
        smoke.assert_not_called()
        launch.assert_called_once()
        self.assertEqual((self.target / portable_update.APP_EXE).read_bytes(), b"MZold")

    def test_direct_upgrade_requires_installation_and_launches_staged_helper(self):
        with patch.object(updater, "is_installed_app", return_value=False), \
             patch.object(updater.subprocess, "Popen") as popen:
            with self.assertRaises(updater.UpdateError):
                updater.schedule_portable_update(self.stage)
            popen.assert_not_called()
        with patch.object(updater, "is_installed_app", return_value=True), \
             patch.object(updater.sys, "executable", str(self.target / portable_update.APP_EXE)), \
             patch.object(updater.subprocess, "Popen") as popen:
            updater.schedule_portable_update(self.stage)
            args = popen.call_args.args[0]
            self.assertEqual(Path(args[0]).resolve(),
                             (self.stage / portable_update.APP_EXE).resolve())
            self.assertEqual(args[1], "--apply-portable-update")
            self.assertEqual(Path(args[3]).resolve(), self.target.resolve())
            self.assertEqual(args[4], str(updater.os.getpid()))


if __name__ == "__main__":
    unittest.main()
