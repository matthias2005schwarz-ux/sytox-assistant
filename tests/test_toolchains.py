"""Regression tests for language selection and consent-first compiler setup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sytox.actions import Toolkit, Denied
from sytox.toolchains import TOOLCHAINS, canonical_language, project_language, propose, status


class LanguageDetectionTests(unittest.TestCase):
    def test_windows_program_defaults_to_csharp(self):
        with tempfile.TemporaryDirectory() as d:
            result = propose("Programmiere mir ein Windows-Programm", Path(d))
            self.assertEqual(result["recommendation"], "csharp")
            self.assertEqual(result["toolchain"]["winget_id"], "Microsoft.DotNet.SDK.10")

    def test_existing_project_overrides_vague_request(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Cargo.toml").write_text("[package]\nname='example'\n", encoding="utf-8")
            (Path(d) / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
            self.assertEqual(project_language(Path(d)), "rust")
            self.assertEqual(propose("Erweitere dieses Projekt", Path(d))["recommendation"], "rust")

    def test_explicit_language_overrides_project(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "example.py").write_text("print(1)", encoding="utf-8")
            self.assertEqual(propose("Schreibe es in C++", Path(d))["recommendation"], "cpp")

    def test_ignores_dependency_folder_and_symlinks(self):
        with tempfile.TemporaryDirectory() as d:
            deps = Path(d) / "node_modules"
            deps.mkdir()
            (deps / "fake.ts").write_text("", encoding="utf-8")
            (Path(d) / "real.py").write_text("", encoding="utf-8")
            self.assertEqual(project_language(Path(d)), "python")

    def test_project_local_typescript_is_recognized(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "node_modules" / ".bin"
            folder.mkdir(parents=True)
            (folder / "tsc.cmd").write_text("@echo off", encoding="utf-8")
            with patch("sytox.toolchains.shutil.which", side_effect=lambda exe: {
                    "node": "node.exe", "npm": "npm.cmd"}.get(exe)):
                self.assertTrue(status("typescript", Path(d))["ready"])
                self.assertIn("tsc (projektlokal)", status("typescript", Path(d))["found"])

    def test_arbitrary_package_ids_cannot_be_requested(self):
        for value in ("evil.EvilPackage", "python --id Evil", "../cpp", "", "c++; rm -rf /"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_language(value)
        self.assertEqual(canonical_language("C#"), "csharp")
        self.assertEqual(canonical_language("C++"), "cpp")
        self.assertEqual(TOOLCHAINS["java"].package, "EclipseAdoptium.Temurin.21.JDK")


class InstallationApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.toolkit = object.__new__(Toolkit)
        self.toolkit.workspace = Path(self.temp.name)
        self.toolkit.stop_event = None
        self.prompts = []
        self.toolkit.approval = self._approval
        self.accept = False

    def _approval(self, label, description):
        self.prompts.append((label, description))
        return self.accept

    @patch("sytox.actions.subprocess.Popen")
    @patch("sytox.actions.shutil.which", return_value=r"C:\Windows\winget.exe")
    @patch("sytox.actions.platform.system", return_value="Windows")
    @patch("sytox.actions.status", return_value={"ready": False})
    def test_denial_never_starts_installer(self, _status, _system, _which, popen):
        with self.assertRaises(Denied):
            self.toolkit.action_toolchain_install("python")
        popen.assert_not_called()
        self.assertEqual(len(self.prompts), 1)
        self.assertIn("Python.Python.3.13", self.prompts[0][1])

    @patch("sytox.actions.subprocess.Popen")
    @patch("sytox.actions.shutil.which", return_value=r"C:\Windows\winget.exe")
    @patch("sytox.actions.platform.system", return_value="Windows")
    @patch("sytox.actions.status", side_effect=[{"ready": False}, {"ready": True}])
    def test_approved_uses_exact_package_and_no_shell(self, _status, _system, _which, popen):
        self.accept = True
        proc = Mock()
        proc.communicate.return_value = ("installed", None)
        proc.returncode = 0
        proc.poll.return_value = 0
        popen.return_value = proc
        reply = self.toolkit.action_toolchain_install("java")
        self.assertIn("Compiler erkannt", reply)
        self.assertEqual(len(self.prompts), 1)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [
            r"C:\Windows\winget.exe", "install", "--id", "EclipseAdoptium.Temurin.21.JDK",
            "--exact", "--source", "winget", "--accept-package-agreements",
            "--accept-source-agreements", "--disable-interactivity",
        ])
        self.assertIs(kwargs["shell"], False)

    @patch("sytox.actions.subprocess.Popen")
    @patch("sytox.actions.status", return_value={"ready": True})
    def test_installed_does_not_reinstall(self, _status, popen):
        result = self.toolkit.action_toolchain_install("python")
        self.assertIn("bereits", result)
        self.assertEqual(self.prompts, [])
        popen.assert_not_called()

    @patch("sytox.actions.subprocess.Popen")
    @patch("sytox.actions.platform.system", return_value="Linux")
    @patch("sytox.actions.status", return_value={"ready": False})
    def test_non_windows_never_installs(self, _status, _platform, popen):
        with self.assertRaises(RuntimeError):
            self.toolkit.action_toolchain_install("java")
        self.assertEqual(self.prompts, [])
        popen.assert_not_called()

    @patch("sytox.actions.subprocess.Popen")
    @patch("sytox.actions.status", side_effect=[
        {"ready": False}, {"ready": True}])
    def test_typescript_missing_does_not_reinstall_node(self, _status, popen):
        result = self.toolkit.action_toolchain_install("typescript")
        self.assertIn("npm install --save-dev typescript", result)
        self.assertEqual(self.prompts, [])
        popen.assert_not_called()

    def test_build_evidence_requires_matching_project(self):
        root = self.toolkit.workspace
        (root / "App.cs").write_text("class App {}", encoding="utf-8")
        self.toolkit.unvalidated_paths = {"App.cs"}
        self.assertFalse(self.toolkit._validates_pending_edits("dotnet build", "Exit code: 0\nok"))
        (root / "App.csproj").write_text("<Project/>", encoding="utf-8")
        self.assertTrue(self.toolkit._validates_pending_edits("dotnet build", "Exit code: 0\nok"))
        self.assertFalse(self.toolkit._validates_pending_edits("dotnet build --no-build", "Exit code: 0\nok"))


if __name__ == "__main__":
    unittest.main()
