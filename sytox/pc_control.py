"""Windows-only desktop adapter, separate from the model and UI.

The active window is selected explicitly in each agent run. Every write/click
must be approved by the UI, and the selected window is checked again before
injecting input. No global clipboard, shell, or remote access is used.
"""
from __future__ import annotations

import ctypes
import os
import unicodedata
from ctypes import wintypes
from pathlib import Path, PureWindowsPath


def _app_key(name):
    """Compare whole names, without guessing from words in a window title."""
    return ''.join(character for character in unicodedata.normalize('NFKC', name).casefold()
                   if character.isalnum() or character == '+')


_APP_EXECUTABLES = {}
for _display, _queries, _stems in (
        ('Spotify', ('spotify',), ('spotify',)),
        ('Discord', ('discord',), ('discord',)),
        ('Google Chrome', ('chrome', 'google chrome'), ('chrome',)),
        ('Firefox', ('firefox', 'mozilla firefox'), ('firefox',)),
        ('Microsoft Edge', ('edge', 'microsoft edge'), ('msedge',)),
        ('Visual Studio Code', ('visual studio code', 'vs code', 'vscode'), ('code',)),
        ('Rechner', ('rechner', 'taschenrechner', 'calculator'), ('calculatorapp', 'calculator', 'calc')),
        ('Editor', ('editor', 'notepad'), ('notepad',)),
):
    for _query in _queries:
        _APP_EXECUTABLES[_app_key(_query)] = (_display, frozenset(_stems))


class DesktopUnavailable(EnvironmentError):
    """The desktop cannot be controlled from this process/platform."""


class WindowsDesktop:
    def _api(self):
        if os.name != 'nt':
            raise DesktopUnavailable('PC-Steuerung ist nur unter Windows verfügbar.')
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        return user32

    @staticmethod
    def _window_title(api, hwnd):
        size = api.GetWindowTextLengthW(hwnd)
        if not size:
            return ''
        buffer = ctypes.create_unicode_buffer(min(size, 250) + 1)
        api.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value.strip()

    def windows(self):
        api = self._api()
        result = []
        foreground = int(api.GetForegroundWindow() or 0)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def collect(hwnd, _):
            if len(result) >= 100 or not api.IsWindowVisible(hwnd):
                return True
            title = self._window_title(api, hwnd)
            if not title:
                return True
            bounds = wintypes.RECT()
            if not api.GetWindowRect(hwnd, ctypes.byref(bounds)):
                return True
            if bounds.right <= bounds.left or bounds.bottom <= bounds.top:
                return True
            result.append({'id': int(hwnd), 'title': title,
                           'rect': [bounds.left, bounds.top, bounds.right, bounds.bottom],
                           'active': int(hwnd) == foreground})
            return True

        callback = callback_type(collect)
        api.EnumWindows(callback, 0)
        return result

    @staticmethod
    def _window_executable(hwnd):
        """Read the owning process image with limited rights; never execute it.

        Protected/closed processes can disappear between enumeration and this
        query. They are unavailable evidence, not a reason to guess from titles.
        """
        if os.name != 'nt':
            raise DesktopUnavailable('App-Fenstersuche ist nur unter Windows verfügbar.')
        handle = None
        kernel32 = None
        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            process_id = wintypes.DWORD()
            if not user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id)) or not process_id.value:
                return None
            handle = kernel32.OpenProcess(0x1000, False, process_id.value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            length = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(length.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                return None
            executable = buffer.value
            return executable if executable and len(executable) <= length.value else None
        except (OSError, AttributeError, ValueError):
            return None
        finally:
            if handle and kernel32 is not None:
                kernel32.CloseHandle(handle)

    def find_app_windows(self, query):
        """Find existing app windows by their owning executable, never title text.

        A browser tab called Spotify is a Chrome window, not a Spotify match.
        Unknown app names require an exact normalized executable stem. Multiple
        matching windows remain separate so the caller can ask the user.
        """
        query = str(query or '').strip()
        if not 2 <= len(query) <= 80:
            raise ValueError('Programmname muss zwischen 2 und 80 Zeichen lang sein.')
        key = _app_key(query)
        if not key:
            raise ValueError('Ein Programmname wird benötigt.')
        display, stems = _APP_EXECUTABLES.get(key, (query, frozenset((key,))))
        matches, seen = [], set()
        for entry in self.windows()[:100]:
            hwnd = entry['id']
            if hwnd in seen:
                continue
            seen.add(hwnd)
            try:
                executable = self._window_executable(hwnd)
            except (OSError, ValueError, AttributeError):
                continue
            if not executable:
                continue
            image = PureWindowsPath(executable)
            if image.suffix.casefold() != '.exe' or _app_key(image.stem) not in stems:
                continue
            matches.append({**entry, 'app_name': display, 'executable': executable})
            if len(matches) >= 30:
                break
        return matches

    @staticmethod
    def find_apps(query):
        """Search Start Menu/Desktop shortcuts without executing or crawling drives."""
        if os.name != 'nt':
            raise DesktopUnavailable('App-Suche ist nur unter Windows verfügbar.')
        query = str(query or '').strip().casefold()
        if not 2 <= len(query) <= 80:
            raise ValueError('Suchbegriff muss zwischen 2 und 80 Zeichen lang sein.')
        roots = []
        for variable, relative in (
                ('APPDATA', 'Microsoft/Windows/Start Menu/Programs'),
                ('PROGRAMDATA', 'Microsoft/Windows/Start Menu/Programs'),
                ('USERPROFILE', 'Desktop'), ('PUBLIC', 'Desktop')):
            value = os.environ.get(variable)
            if value and Path(value).is_absolute():
                roots.append(Path(value) / relative)
        found = []
        seen = set()
        for root in roots:
            if not root.is_dir():
                continue
            for shortcut in root.rglob('*.lnk'):
                if query not in shortcut.stem.casefold():
                    continue
                normalized = str(shortcut.resolve()).casefold()
                if normalized in seen:
                    continue
                seen.add(normalized)
                found.append({'name': shortcut.stem[:100], 'path': str(shortcut)})
                if len(found) >= 30:
                    return found
        return found

    def window(self, hwnd):
        try:
            hwnd = int(hwnd)
        except (ValueError, TypeError):
            raise ValueError('Ungültige Fenster-ID.') from None
        entry = next((w for w in self.windows() if w['id'] == hwnd), None)
        if entry is None:
            raise LookupError('Fenster ist nicht mehr verfügbar. Bitte Fensterliste aktualisieren.')
        return entry

    def foreground_id(self):
        return int(self._api().GetForegroundWindow() or 0)

    def activate(self, hwnd):
        entry = self.window(hwnd)
        api = self._api()
        if api.IsIconic(hwnd):
            api.ShowWindow(hwnd, 9)  # SW_RESTORE
        api.SetForegroundWindow(hwnd)
        if self.foreground_id() != hwnd:
            raise DesktopUnavailable('Windows hat den Fokuswechsel abgelehnt. Bitte Ziel-App selbst aktivieren.')
        return entry

    @staticmethod
    def _control_info(wrapper, index):
        info = wrapper.element_info
        rect = wrapper.rectangle()
        return {'id': index,
                'name': str(wrapper.window_text() or '')[:140],
                'type': str(info.control_type or '')[:40],
                'automation_id': str(info.automation_id or '')[:80],
                'rect': [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)]}

    def inspect(self, hwnd):
        self.window(hwnd)
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise DesktopUnavailable('Windows-Bedienelemente benötigen pywinauto (Setup erneut ausführen).') from exc
        root = Desktop(backend='uia').window(handle=hwnd).wrapper_object()
        entries = []
        controls = {}
        for child in root.descendants()[:130]:
            try:
                if not child.is_visible():
                    continue
                item = self._control_info(child, len(entries) + 1)
                if item['type'] not in ('Button', 'Edit', 'CheckBox', 'RadioButton', 'ComboBox', 'TabItem',
                                        'Text', 'Hyperlink', 'ListItem', 'MenuItem'):
                    continue
                if not (item['name'] or item['automation_id']):
                    continue
                entries.append(item)
                controls[item['id']] = child
                if len(entries) >= 75:
                    break
            except Exception:
                continue  # Some controls disappear while inspecting the app.
        return entries, controls

    def click_control(self, wrapper):
        if not wrapper.is_visible() or not wrapper.is_enabled():
            raise LookupError('Bedienelement ist nicht mehr sichtbar oder ist deaktiviert.')
        wrapper.click_input()

    @staticmethod
    def type_unicode(text, ensure_focused):
        """Use Unicode keyboard events; unlike pyautogui.write this handles ä, ö, ß and emoji.

        No clipboard data is read or overwritten. Focus is checked during the input.
        """
        if os.name != 'nt':
            raise DesktopUnavailable('Unicode-Eingabe ist nur unter Windows verfügbar.')
        import struct
        from ctypes import wintypes as wt

        ULONG_PTR = ctypes.c_size_t
        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [('wVk', wt.WORD), ('wScan', wt.WORD), ('dwFlags', wt.DWORD),
                        ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]
        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('mouseData', wt.DWORD),
                        ('dwFlags', wt.DWORD), ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]
        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [('uMsg', wt.DWORD), ('wParamL', wt.WORD), ('wParamH', wt.WORD)]
        class INPUT_UNION(ctypes.Union):
            _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]
        class INPUT(ctypes.Structure):
            _fields_ = [('type', wt.DWORD), ('data', INPUT_UNION)]
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wt.UINT
        utf16 = text.encode('utf-16-le')
        for pos in range(0, len(utf16), 2):
            ensure_focused()
            unit = struct.unpack_from('<H', utf16, pos)[0]
            events = (INPUT(1, INPUT_UNION(ki=KEYBDINPUT(0, unit, 0x0004, 0, 0))),
                      INPUT(1, INPUT_UNION(ki=KEYBDINPUT(0, unit, 0x0004 | 0x0002, 0, 0))))
            for event in events:
                if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
                    raise DesktopUnavailable('Windows hat die Unicode-Tastatureingabe blockiert.')

    @staticmethod
    def hotkey(keys):
        import pyautogui
        pyautogui.hotkey(*keys, interval=0.06)

    @staticmethod
    def click(x, y):
        import pyautogui
        pyautogui.click(x, y)

    @staticmethod
    def open_app(path):
        os.startfile(str(path))
