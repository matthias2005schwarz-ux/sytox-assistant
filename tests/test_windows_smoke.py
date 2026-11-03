"""Startup contract and Windows test pipeline coverage (cross-platform mocks).

These tests do not falsely claim native Windows execution on Linux.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import main


class SmokeEntryTests(unittest.TestCase):
    def setUp(self):
        qtcore = types.ModuleType('PySide6.QtCore')
        qtwidgets = types.ModuleType('PySide6.QtWidgets')
        ui = types.ModuleType('sytox.ui')
        qtcore.QTimer = MagicMock()
        qtwidgets.QApplication = MagicMock()
        qtwidgets.QApplication.return_value.exec.return_value = 0
        qtwidgets.QSystemTrayIcon = MagicMock()
        ui.MainWindow = MagicMock()
        instance = types.ModuleType('sytox.instance')
        instance.InstanceBridge = MagicMock()
        self.instance = instance
        self.qtcore, self.qtwidgets, self.ui = qtcore, qtwidgets, ui
        modules = {'PySide6': types.ModuleType('PySide6'),
                   'PySide6.QtCore': qtcore, 'PySide6.QtWidgets': qtwidgets,
                   'sytox.ui': ui, 'sytox.instance': instance}
        self.patch_modules = patch.dict(sys.modules, modules)
        self.patch_modules.start()
        self.addCleanup(self.patch_modules.stop)

    def test_smoke_creates_main_window_and_exits_without_running_jobs(self):
        with patch.object(sys, 'argv', ['main.py','--smoke-test']):
            self.assertEqual(main.main(), 0)
        self.ui.MainWindow.assert_called_once_with()
        self.qtcore.QTimer.singleShot.assert_called_once()
        self.assertEqual(self.qtcore.QTimer.singleShot.call_args.args[0], 350)
        self.ui.MainWindow.return_value.show.assert_called_once()

    def test_normal_mode_shows_main_window(self):
        with patch.object(sys, 'argv', ['main.py']):
            self.assertEqual(main.main(), 0)
        self.ui.MainWindow.return_value.show.assert_called_once()
        self.qtcore.QTimer.singleShot.assert_not_called()

    def test_background_starts_hidden_when_tray_exists(self):
        self.qtwidgets.QSystemTrayIcon.isSystemTrayAvailable.return_value = True
        with patch.object(sys, 'argv', ['main.py', '--background']):
            self.assertEqual(main.main(), 0)
        self.ui.MainWindow.assert_called_once_with()
        self.ui.MainWindow.return_value.show.assert_not_called()
        self.instance.InstanceBridge.return_value.listen_or_signal.assert_called_once_with(show=False)

    def test_background_shows_window_when_tray_unavailable(self):
        self.qtwidgets.QSystemTrayIcon.isSystemTrayAvailable.return_value = False
        with patch.object(sys, 'argv', ['main.py', '--background']):
            self.assertEqual(main.main(), 0)
        self.ui.MainWindow.return_value.show.assert_called_once()

    def test_second_launch_only_signals_first_window(self):
        self.instance.InstanceBridge.return_value.listen_or_signal.return_value = False
        with patch.object(sys, 'argv', ['main.py']):
            self.assertEqual(main.main(), 0)
        self.instance.InstanceBridge.return_value.listen_or_signal.assert_called_once_with(show=True)
        self.ui.MainWindow.assert_not_called()
        self.qtwidgets.QApplication.return_value.exec.assert_not_called()

    def test_smoke_test_does_not_start_instance_socket(self):
        with patch.object(sys, 'argv', ['main.py','--smoke-test']):
            self.assertEqual(main.main(), 0)
        self.instance.InstanceBridge.assert_not_called()

    def test_unknown_switch_is_rejected(self):
        with patch.object(sys, 'argv', ['main.py', '--unrecognized']):
            with self.assertRaises(SystemExit):
                main.main()
        self.ui.MainWindow.assert_not_called()


class WindowsPackageContracts(unittest.TestCase):
    def test_script_has_real_exe_exit_check(self):
        text = (Path(__file__).resolve().parents[1] / 'Windows_Smoke_Test.ps1').read_text(encoding='utf-8')
        self.assertIn('WaitForExit(30000)', text)
        self.assertIn('APPDATA', text)
        self.assertIn("'--smoke-test'", text)
        self.assertIn('Win32', text)

    def test_installer_has_optional_autostart_and_user_data_preservation(self):
        installer = (Path(__file__).resolve().parents[1] / 'Windows_Installer.iss').read_text(encoding='utf-8')
        self.assertIn('PrivilegesRequired=lowest', installer)
        self.assertIn('Name: "autostart"', installer)
        self.assertIn('Name: "desktopicon"', installer)
        self.assertIn('--background', installer)
        self.assertIn('AppMutex=Local\\SYTOX_Assistant_8B5756C1', installer)
        self.assertNotIn('DelTree', installer)

    def test_installer_build_rebuilds_binary_by_default(self):
        installer_build = (Path(__file__).resolve().parents[1] / 'Build_Installer.ps1').read_text(encoding='utf-8')
        self.assertIn('SkipExeBuild', installer_build)
        self.assertIn('Build_EXE.ps1', installer_build)
        self.assertIn('Inno Setup', installer_build)

    def test_build_includes_full_source_bundle(self):
        text = (Path(__file__).resolve().parents[1] / 'Build_EXE.ps1').read_text(encoding='utf-8')
        for name in ('tests', 'sytox', 'main.py', 'Setup_Windows.ps1', 'Windows_Smoke_Test.ps1'):
            self.assertIn(name, text)


if __name__ == '__main__':
    unittest.main()
