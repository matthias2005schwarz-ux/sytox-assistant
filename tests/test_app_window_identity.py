"""Process-backed application identity; no real Windows desktop is touched."""
import ctypes
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from sytox.pc_control import DesktopUnavailable, WindowsDesktop


def window(handle, title):
    return {'id': handle, 'title': title, 'active': False, 'rect': [0, 0, 800, 600]}


class AppWindowIdentityTests(unittest.TestCase):
    def desktop(self, windows, images):
        desktop = WindowsDesktop()
        desktop.windows = MagicMock(return_value=windows)
        desktop._window_executable = MagicMock(side_effect=lambda handle: images.get(handle))
        return desktop

    def test_spotify_uses_process_identity_instead_of_a_browser_tab_title(self):
        desktop = self.desktop(
            [window(1, 'Spotify - Google Chrome'), window(2, 'Song – Artist')],
            {1: r'C:\Program Files\Google\Chrome\chrome.exe',
             2: r'C:\Users\Test\AppData\Roaming\Spotify\Spotify.exe'})
        matches = desktop.find_app_windows('Spotify')
        self.assertEqual([entry['id'] for entry in matches], [2])
        self.assertEqual(matches[0]['app_name'], 'Spotify')
        self.assertEqual(matches[0]['title'], 'Song – Artist')
        self.assertEqual(matches[0]['executable'],
                         r'C:\Users\Test\AppData\Roaming\Spotify\Spotify.exe')

    def test_known_names_match_exact_executable_aliases(self):
        examples = (
            ('Google Chrome', 'chrome.exe', 'Google Chrome'),
            ('Chrome', 'chrome.exe', 'Google Chrome'),
            ('Microsoft Edge', 'msedge.exe', 'Microsoft Edge'),
            ('Visual Studio Code', 'Code.exe', 'Visual Studio Code'),
            ('VS Code', 'Code.exe', 'Visual Studio Code'),
            ('Taschenrechner', 'CalculatorApp.exe', 'Rechner'),
            ('Rechner', 'calc.exe', 'Rechner'),
            ('Editor', 'notepad.exe', 'Editor'),
            ('Notepad', 'notepad.exe', 'Editor'),
        )
        for query, executable, display in examples:
            with self.subTest(query=query):
                desktop = self.desktop([window(5, 'Any title')], {5: 'C:\\Apps\\' + executable})
                matches = desktop.find_app_windows(query)
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]['app_name'], display)

    def test_unknown_names_are_whole_normalized_stems_and_not_prefix_matches(self):
        desktop = self.desktop(
            [window(1, 'Music Box'), window(2, 'MusicBox'), window(3, 'Spotify')],
            {1: r'C:\Apps\MusicBoxHelper.exe', 2: r'C:\Apps\MusicBox.exe',
             3: r'C:\Apps\SpotifyUpdater.exe'})
        self.assertEqual([entry['id'] for entry in desktop.find_app_windows('Music Box')], [2])
        self.assertEqual(desktop.find_app_windows('Spotify'), [])

    def test_multiple_real_windows_remain_distinct_for_user_selection(self):
        desktop = self.desktop([window(1, 'One'), window(2, 'Two'), window(1, 'Duplicate')],
                               {1: r'C:\Chrome\chrome.exe', 2: r'C:\Chrome\chrome.exe'})
        self.assertEqual([entry['id'] for entry in desktop.find_app_windows('Chrome')], [1, 2])
        self.assertEqual(desktop._window_executable.call_count, 2)

    def test_unreadable_and_disappearing_processes_are_skipped(self):
        desktop = self.desktop([window(1, 'Spotify'), window(2, 'Spotify'), window(3, 'Song')], {})
        desktop._window_executable.side_effect = [PermissionError('protected'), None, r'C:\Apps\Spotify.exe']
        self.assertEqual([entry['id'] for entry in desktop.find_app_windows('Spotify')], [3])

    def test_invalid_names_do_not_even_enumerate_windows(self):
        desktop = self.desktop([], {})
        for query in ('', 'A', ' ' * 10, 'x' * 81, '!!'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                desktop.find_app_windows(query)
        desktop.windows.assert_not_called()

    def test_repeated_lookup_uses_current_process_identity_for_confirmation(self):
        desktop = self.desktop([window(7, 'Spotify')], {})
        desktop._window_executable.side_effect = [r'C:\Spotify\Spotify.exe', r'C:\Chrome\chrome.exe']
        self.assertEqual(len(desktop.find_app_windows('Spotify')), 1)
        self.assertEqual(desktop.find_app_windows('Spotify'), [])


class WindowExecutableApiTests(unittest.TestCase):
    def apis(self, *, pid=123, handle=0x123456789):
        user = SimpleNamespace(GetWindowThreadProcessId=MagicMock())
        kernel = SimpleNamespace(OpenProcess=MagicMock(return_value=handle),
                                 QueryFullProcessImageNameW=MagicMock(), CloseHandle=MagicMock())

        def get_process(_hwnd, pointer):
            pointer._obj.value = pid
            return 42 if pid else 0

        user.GetWindowThreadProcessId.side_effect = get_process
        return user, kernel

    def execute(self, user, kernel):
        with patch('sytox.pc_control.os', SimpleNamespace(name='nt')), \
             patch.object(ctypes, 'WinDLL', create=True,
                          side_effect=lambda name, **_kwargs: user if name == 'user32' else kernel):
            return WindowsDesktop._window_executable(17)

    def test_reads_full_image_path_with_limited_access_and_closes_wide_handle(self):
        user, kernel = self.apis()
        executable = r'C:\Program Files\Spotify\Spotify.exe'

        def query(handle, flags, buffer, length):
            self.assertEqual(handle, 0x123456789)
            self.assertEqual(flags, 0)
            self.assertEqual(length._obj.value, 32768)
            buffer.value = executable
            length._obj.value = len(executable)
            return True

        kernel.QueryFullProcessImageNameW.side_effect = query
        self.assertEqual(self.execute(user, kernel), executable)
        kernel.OpenProcess.assert_called_once_with(0x1000, False, 123)
        kernel.CloseHandle.assert_called_once_with(0x123456789)
        self.assertIs(kernel.OpenProcess.restype, ctypes.wintypes.HANDLE)
        self.assertIs(kernel.QueryFullProcessImageNameW.restype, ctypes.wintypes.BOOL)

    def test_failed_image_query_still_closes_handle(self):
        user, kernel = self.apis()
        kernel.QueryFullProcessImageNameW.return_value = False
        self.assertIsNone(self.execute(user, kernel))
        kernel.CloseHandle.assert_called_once_with(0x123456789)

    def test_query_exception_still_closes_handle(self):
        user, kernel = self.apis()
        kernel.QueryFullProcessImageNameW.side_effect = OSError('process exited')
        self.assertIsNone(self.execute(user, kernel))
        kernel.CloseHandle.assert_called_once_with(0x123456789)

    def test_denied_open_and_disappeared_windows_do_not_close_an_invalid_handle(self):
        for pid, handle in ((123, 0), (0, 0x123456789)):
            with self.subTest(pid=pid):
                user, kernel = self.apis(pid=pid, handle=handle)
                self.assertIsNone(self.execute(user, kernel))
                kernel.QueryFullProcessImageNameW.assert_not_called()
                kernel.CloseHandle.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Only the unsupported-platform branch is tested here')
    def test_non_windows_backend_reports_unavailable(self):
        with self.assertRaises(DesktopUnavailable):
            WindowsDesktop._window_executable(17)
        with self.assertRaises(DesktopUnavailable):
            WindowsDesktop().find_app_windows('Spotify')


class AppShortcutRootsTests(unittest.TestCase):
    def test_missing_or_relative_environment_roots_never_search_the_current_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for parent in (root / 'Desktop', root / 'profile/Microsoft/Windows/Start Menu/Programs'):
                parent.mkdir(parents=True)
                (parent / 'Spotify.lnk').write_bytes(b'not an installed program')
            previous = os.getcwd()
            try:
                os.chdir(root)
                for environment in ({}, {'APPDATA': 'profile', 'USERPROFILE': '.'}):
                    with self.subTest(environment=environment), \
                         patch('sytox.pc_control.os', SimpleNamespace(name='nt', environ=environment)):
                        self.assertEqual(WindowsDesktop.find_apps('Spotify'), [])
            finally:
                os.chdir(previous)

    def test_absolute_start_menu_root_still_finds_the_installed_shortcut(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            programs = root / 'Microsoft/Windows/Start Menu/Programs'
            programs.mkdir(parents=True)
            shortcut = programs / 'Spotify.lnk'
            shortcut.write_bytes(b'inert shortcut')
            with patch('sytox.pc_control.os', SimpleNamespace(name='nt', environ={'APPDATA': str(root)})):
                self.assertEqual(WindowsDesktop.find_apps('spotify'),
                                 [{'name': 'Spotify', 'path': str(shortcut)}])


if __name__ == '__main__':
    unittest.main()
