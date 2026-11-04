"""Offline updater regression tests: no remote request can execute an installer."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sytox import updater


class FakeResponse:
    def __init__(self, data=b"", status_code=200, url="https://github.com/" + updater.REPOSITORY + "/releases/download/v0.3.4/file"):
        self.data = data
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Length": str(len(data))}

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def iter_content(self, chunk_size=1024):
        for index in range(0, len(self.data), chunk_size):
            yield self.data[index:index + chunk_size]


def release(version="0.3.4", with_checksum=True):
    base = "https://github.com/" + updater.REPOSITORY + "/releases/download/v" + version + "/"
    filename = "SYTOX_Assistant_Setup_" + version + ".exe"
    assets = [{"name": filename, "browser_download_url": base + filename}]
    if with_checksum:
        assets.append({"name": filename + ".sha256",
                       "browser_download_url": base + filename + ".sha256"})
    return {"tag_name": "v" + version, "draft": False, "prerelease": False,
            "assets": assets}


class UpdateTests(unittest.TestCase):
    def test_version_comparison_and_stable_release_only(self):
        with patch.object(updater.requests, "get", return_value=FakeResponse(release())):
            info = updater.check_for_update("0.3.3")
            self.assertEqual(info.version, "0.3.4")
            self.assertIsNone(updater.check_for_update("0.3.4"))
        with patch.object(updater.requests, "get", return_value=FakeResponse(release(with_checksum=False))):
            self.assertIsNone(updater.check_for_update("0.3.3"))
        draft = release()
        draft["draft"] = True
        with patch.object(updater.requests, "get", return_value=FakeResponse(draft)):
            self.assertIsNone(updater.check_for_update("0.3.3"))

    def test_404_means_no_release(self):
        with patch.object(updater.requests, "get", return_value=FakeResponse(status_code=404)):
            self.assertIsNone(updater.check_for_update("0.3.3"))

    def test_untrusted_installer_rejected(self):
        data = release()
        data["assets"][0]["browser_download_url"] = "https://example.com/evil.exe"
        with patch.object(updater.requests, "get", return_value=FakeResponse(data)):
            with self.assertRaises(updater.UpdateError):
                updater.check_for_update("0.3.3")

    def test_verified_download_and_corrupted_download_removed(self):
        binary = b"MZ" + b"fixture" * 180
        filename = "SYTOX_Assistant_Setup_0.3.4.exe"
        sha = hashlib.sha256(binary).hexdigest()
        info = updater.UpdateInfo("0.3.4", "https://github.com/",
            "https://github.com/" + updater.REPOSITORY + "/releases/download/v0.3.4/" + filename,
            "https://github.com/" + updater.REPOSITORY + "/releases/download/v0.3.4/" + filename + ".sha256",
            filename)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updater, "update_cache_dir", return_value=Path(folder)):
                with patch.object(updater.requests, "get",
                                  side_effect=[FakeResponse((sha + "  " + filename).encode()),
                                               FakeResponse(binary)]):
                    path = updater.download_verified_installer(info)
                    self.assertEqual(path.read_bytes(), binary)
                with patch.object(updater.requests, "get",
                                  side_effect=[FakeResponse((sha + "  " + filename).encode()),
                                               FakeResponse(b"tampered")]):
                    with self.assertRaisesRegex(updater.UpdateError, "SHA-256"):
                        updater.download_verified_installer(info)
                self.assertEqual(path.read_bytes(), binary)
                self.assertFalse(any(p.suffix == ".part" for p in Path(folder).iterdir()))

    def test_no_execution_outside_installed_windows_exe(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updater, "update_cache_dir", return_value=Path(folder)):
                installer = Path(folder) / "SYTOX_Assistant_Setup_0.3.4.exe"
                installer.write_bytes(b"test")
                with patch.object(updater, "is_installed_app", return_value=False):
                    with patch.object(updater.subprocess, "Popen") as popen:
                        with self.assertRaises(updater.UpdateError):
                            updater.schedule_installer(installer)
                        popen.assert_not_called()
                with self.assertRaises(updater.UpdateError):
                    updater._valid_cached_installer(Path(folder).parent / installer.name)


if __name__ == "__main__":
    unittest.main()
