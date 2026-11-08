"""Windows repairs are opt-in, allowlisted, bounded, and honestly verified."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.windows_repair import (
    identify_error, wants_windows_diagnosis, asks_for_repair,
    choose_unambiguous_fix, repair_windows, WindowsRepairError,
)
from sytox.actions import Toolkit, tool_schema
from sytox.storage import Store


class WindowsDiagnosisAndRepairTests(unittest.TestCase):
    def test_generic_windows_errors_recognized_without_installing(self):
        for message in (
            'Startet nicht: 0xc000007b',
            'VCRUNTIME140.dll wurde nicht gefunden.',
            'Programm startet nicht',
            'Windows Fehlercode 0x80070005',
            'App Absturz beim Start',
        ):
            with self.subTest(message=message):
                self.assertTrue(wants_windows_diagnosis(message))
        self.assertIn('0xc000007b', identify_error('Fehler 0xC000007B')['codes'])
        self.assertEqual(identify_error('0xc0000005')['possible_repairs_not_yet_verified'], [])

    def test_no_repair_from_a_question_negation_or_ambiguous_error(self):
        for question in (
            'Was bedeutet VCRUNTIME140.dll?',
            'Wie kann ich VCRUNTIME140.dll reparieren?',
            'Bitte nicht installieren',
            'Erklär mir den Fehler 0xc000007b',
        ):
            with self.subTest(question=question):
                self.assertFalse(asks_for_repair(question))
        self.assertIsNone(choose_unambiguous_fix('VCRUNTIME140.dll fehlt'))
        self.assertIsNone(choose_unambiguous_fix('0xc000007b x64'))
        self.assertIsNone(choose_unambiguous_fix('MSVCP140.dll x64 und x86'))
        self.assertEqual(choose_unambiguous_fix('VCRUNTIME140.dll fehlt, x64'), 'vc_redist_x64')
        self.assertEqual(choose_unambiguous_fix('VCRUNTIME140.dll fehlt, x86'), 'vc_redist_x86')

    @patch('sytox.windows_repair._require_windows')
    @patch('sytox.windows_repair._winget', return_value='winget.exe')
    def test_package_download_requires_approval_and_check_after_install(self, _winget, _windows):
        commands = []
        approvals = []
        def fake_command(argv, timeout, stop_event):
            commands.append(argv)
            if 'list' in argv:
                count = sum('list' in cmd for cmd in commands)
                return 0, ('No installed package found' if count == 1 else
                           'Microsoft.VCRedist.2015+.x64 version 14.0')
            return 0, 'Successfully installed'
        def approval(label, description):
            approvals.append((label, description))
            return True
        result = repair_windows('vc_redist_x64', approval, command=fake_command)
        self.assertEqual(result['status'], 'package_verified')
        self.assertEqual(result['verification'], 'package_present')
        self.assertEqual(len(approvals), 1)
        self.assertEqual(sum('install' in cmd for cmd in commands), 1)
        self.assertIn('Microsoft.VCRedist.2015+.x64', approvals[0][1])
        self.assertTrue(all('curl' not in cmd and 'powershell' not in cmd for cmd in commands))
        self.assertIn('Betroffenes Programm erneut starten', result['next_step'])

    @patch('sytox.windows_repair._require_windows')
    @patch('sytox.windows_repair._winget', return_value='winget.exe')
    def test_denial_never_runs_installer(self, _winget, _windows):
        calls = []
        def fake(argv, timeout, stop_event):
            calls.append(argv)
            return 0, 'No installed package found'
        result = repair_windows('vc_redist_x86', lambda *_: False, command=fake)
        self.assertEqual(result['status'], 'denied')
        self.assertTrue(calls)
        self.assertFalse(any('install' in cmd for cmd in calls))

    @patch('sytox.windows_repair._require_windows')
    def test_unlisted_fix_is_rejected_without_execution(self, _windows):
        # Test the allowlist itself on every host, as with the adjacent cases.
        calls = []
        def command(*args):
            calls.append(args)
            raise AssertionError('An unlisted repair must never execute a command')
        with self.assertRaisesRegex(ValueError, 'Unbekannte Reparatur-ID'):
            repair_windows('https://evil.invalid/fix.exe', lambda *_: True, command=command)
        self.assertEqual(calls, [])

    @patch('sytox.windows_repair._require_windows')
    @patch('sytox.windows_repair._is_admin', return_value=False)
    def test_admin_only_action_cannot_skip_uac(self, _admin, _windows):
        requests = []
        result = repair_windows('system_files', lambda *args: requests.append(args) or True)
        self.assertEqual(result['status'], 'needs_admin')
        self.assertFalse(requests)


class AgentWindowsToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / 'data.sqlite3')
        self.cid = self.store.create_chat()
        self.approvals = []
        self.tool = Toolkit(self.store, Path(self.tmp.name) / 'project',
                            lambda *args: self.approvals.append(args) or True,
                            threading.Event(), self.cid)
        self.addCleanup(self.tool.close)

    def test_main_agent_schema_exposes_same_repair_as_quick_chat(self):
        tools = {t['function']['name'] for t in tool_schema()}
        self.assertIn('windows_error_diagnose', tools)
        self.assertIn('windows_repair', tools)

    def test_main_agent_uses_shared_safe_diagnostic_and_repair(self):
        with patch('sytox.actions.diagnose_windows', return_value={'codes':['0xc000007b']}) as diagnosis:
            data = json.loads(self.tool.call('windows_error_diagnose', {'error_text':'0xc000007b'}))
        self.assertEqual(data['codes'], ['0xc000007b'])
        diagnosis.assert_called_once()
        with patch('sytox.actions.repair_windows', return_value={'status':'denied'}) as repair:
            result = json.loads(self.tool.call('windows_repair', {'fix_id':'vc_redist_x64'}))
        self.assertEqual(result['status'], 'denied')
        self.assertEqual(repair.call_args.args[0], 'vc_redist_x64')
        self.assertIsNotNone(repair.call_args.kwargs['approve'])


if __name__ == '__main__':
    unittest.main()
