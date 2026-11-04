"""Cross-platform verification of Windows release contracts; not native Windows tests."""
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main

ROOT = Path(__file__).resolve().parents[1]


def content(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


class WindowsReleaseContracts(unittest.TestCase):
    def test_all_windows_package_versions_match_project(self):
        version = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", content('sytox/__init__.py')).group(1)
        self.assertEqual(version, '0.3.3')
        for name in ('Windows_Installer.iss', 'Build_Installer.ps1', '.github/workflows/windows-ci.yml',
                     'Installer_Install_Smoke_Test.ps1'):
            with self.subTest(name=name):
                self.assertIn('0.3.3', content(name))
                self.assertNotIn('0.2.5', content(name))

    def test_installer_ci_tests_installed_exe_and_retains_profile_data(self):
        script = content('Installer_Install_Smoke_Test.ps1')
        self.assertIn('GITHUB_ACTIONS', script)
        self.assertIn('RUNNER_OS', script)
        self.assertIn('/VERYSILENT', script)
        self.assertIn('--smoke-test', script)
        self.assertIn('preserve_on_uninstall.txt', script)
        self.assertIn('unins000.exe', script)
        self.assertIn('ExitCode', script)
        self.assertIn('finally {', script)
        workflow = content('.github/workflows/windows-ci.yml')
        self.assertIn('runs-on: windows-latest', workflow)
        self.assertIn('Installer_Install_Smoke_Test.ps1', workflow)
        self.assertIn('actions/upload-artifact', workflow)
        self.assertIn('installer/SYTOX_Assistant_Setup_0.3.3.exe', workflow)
        self.assertIn('dist/SYTOX_Assistant/', workflow)

    def test_bundle_contains_required_release_scripts(self):
        script = content('Build_EXE.ps1')
        for name in ('Build_Installer.ps1', 'Installer_Install_Smoke_Test.ps1',
                     'Windows_Installer.iss', 'sytox;source_bundle/sytox'):
            with self.subTest(name=name):
                self.assertIn(name, script)


class WindowsInstallerTimeoutTests(unittest.TestCase):
    def test_installer_checks_are_bounded_and_kill_process_tree(self):
        script = content('Installer_Install_Smoke_Test.ps1')
        self.assertIn('function Invoke-BoundedProcess', script)
        self.assertIn('WaitForExit($TimeoutSeconds * 1000)', script)
        self.assertIn('taskkill.exe /PID', script)
        self.assertIn('Invoke-BoundedProcess $installer $installArgs 180', script)
        self.assertIn("Invoke-BoundedProcess $exe @('--smoke-test') 45", script)
        self.assertIn('Invoke-BoundedProcess $uninstaller', script)
        self.assertNotIn("Start-Process -FilePath $exe -ArgumentList '--smoke-test' -Wait", script)

    def test_ci_has_explicit_timeout_and_preserves_release_artifact(self):
        workflow = content('.github/workflows/windows-ci.yml')
        self.assertIn('timeout-minutes: 35', workflow)
        self.assertIn('actions/upload-artifact@v4', workflow)
        self.assertIn('SYTOX_Assistant_Setup_0.3.3.exe', workflow)


class FatalStartupReportTests(unittest.TestCase):
    def test_startup_error_has_nonzero_exit_and_local_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            with patch.object(main, 'main', side_effect=RuntimeError('fake startup failure')):
                with patch('sytox.storage.default_data_dir', return_value=p):
                    with patch.object(sys, 'stderr', io.StringIO()) as printed:
                        self.assertEqual(main.run_with_startup_report(), 1)
                        self.assertIn('fake startup failure', printed.getvalue())
            report = p / 'startup_error.log'
            self.assertTrue(report.exists())
            self.assertIn('fake startup failure', report.read_text(encoding='utf-8'))

    def test_successful_start_preserves_exit_code_and_no_log(self):
        with patch.object(main, 'main', return_value=0):
            self.assertEqual(main.run_with_startup_report(), 0)


if __name__ == '__main__':
    unittest.main()
