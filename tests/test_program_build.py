"""Non-destructive tests for the consent-first Windows project builder."""
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from sytox.program_build import build_plan, inspect_windows_executable, needs_compiled_artifact
from sytox.actions import Toolkit, Denied
from sytox.agent import Agent
from sytox.storage import Store


def write_fake_pe(path, x64=True):
    """Synthetic *header* for verification tests, not a runnable EXE."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = bytearray(1024)
    payload[:2] = b'MZ'
    struct.pack_into('<I', payload, 0x3c, 0x80)
    payload[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', payload, 0x84, 0x8664 if x64 else 0x14c)
    struct.pack_into('<H', payload, 0x98, 0x20b if x64 else 0x10b)
    path.write_bytes(payload)


def fake_compiler():
    proc = Mock()
    proc.communicate.return_value = ('Build succeeded.', None)
    proc.returncode = 0
    proc.poll.return_value = 0
    return proc


class BuildPlanTests(unittest.TestCase):
    def test_compile_requirement(self):
        self.assertEqual(needs_compiled_artifact('Erstelle eine Windows-EXE'), 'exe')
        self.assertEqual(needs_compiled_artifact('Windows-Programm bauen'), 'exe')
        self.assertEqual(needs_compiled_artifact('Erstelle einen Installer'), 'installer')
        self.assertEqual(needs_compiled_artifact('Schreibe Python-Code'), '')

    def test_csharp_build_is_explicit_publish(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'App.csproj').write_text('<Project/>', encoding='utf-8')
            info = build_plan(Path(d))
            self.assertEqual(info['language'], 'csharp')
            self.assertEqual(info['command'][:2], ['dotnet', 'publish'])
            self.assertIn('win-x64', info['command'])
            self.assertEqual(info['expected_executable'], 'build_output/App.exe')
            self.assertTrue(info['requires_approval'])

    def test_go_and_rust_builds(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'go.mod').write_text('module example.org/app\n', encoding='utf-8')
            info = build_plan(root)
            self.assertEqual(info['command'][:2], ['go', 'build'])
            self.assertEqual(info['expected_executable'], 'build_output/SYTOX_Program.exe')
            (root / 'go.mod').unlink()
            (root / 'Cargo.toml').write_text('[package]\nname = "demo"\nversion="0.1.0"\n', encoding='utf-8')
            self.assertEqual(build_plan(root)['expected_executable'], 'target/release/demo.exe')

    def test_ambiguous_projects_are_not_built(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('App.csproj', 'Other.csproj'):
                (Path(d) / name).write_text('<Project/>', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Mehrere'):
                build_plan(Path(d))

    def test_no_arbitrary_shell_command_for_unknown_project(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'index.js').write_text('console.log(1)', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'noch keinen'):
                build_plan(Path(d))

    def test_inspect_real_pe_layout_and_hash_without_running(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'build_output' / 'Program.exe'
            write_fake_pe(path)
            result = inspect_windows_executable(Path(d), 'build_output/Program.exe')
            self.assertTrue(result['format_valid'])
            self.assertEqual(len(result['sha256']), 64)
            self.assertFalse(result['runtime_tested'])
            path.write_bytes(b'MZ' + b'\0' * 1024)
            with self.assertRaises(ValueError):
                inspect_windows_executable(Path(d), 'build_output/Program.exe')

    def test_wrong_architecture_and_workspace_escape_rejected(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            path = Path(d) / 'sample.exe'
            write_fake_pe(path, x64=False)
            with self.assertRaisesRegex(ValueError, 'x64'):
                inspect_windows_executable(Path(d), 'sample.exe')
            write_fake_pe(Path(outside) / 'outside.exe')
            with self.assertRaises(ValueError):
                inspect_windows_executable(Path(d), str(Path(outside) / 'outside.exe'))


class ApprovalBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'go.mod').write_text('module example.org/app\n', encoding='utf-8')
        self.toolkit = object.__new__(Toolkit)
        self.toolkit.workspace = self.root
        self.toolkit.approval = lambda *_: False
        self.toolkit.stop_event = None
        self.toolkit.built_artifacts = []
        self.toolkit.unvalidated_paths = {'main.go'}
        self.toolkit.passed_checks = 0
        self.toolkit.writes = 1

    @patch('sytox.actions.platform.system', return_value='Windows')
    @patch('sytox.actions.subprocess.Popen')
    def test_denied_never_launches_build(self, popen, system):
        with self.assertRaises(Denied):
            self.toolkit.action_project_build()
        popen.assert_not_called()
        self.assertEqual(self.toolkit.built_artifacts, [])

    @patch('sytox.actions.platform.system', return_value='Windows')
    @patch('sytox.actions.subprocess.Popen')
    def test_approved_compiler_and_pe_receipt(self, popen, system):
        self.toolkit.approval = lambda *_: True

        def build(argv, **kwargs):
            write_fake_pe(self.root / 'build_output' / 'SYTOX_Program.exe')
            return fake_compiler()

        popen.side_effect = build
        result = json.loads(self.toolkit.action_project_build())
        self.assertEqual(result['build'], 'compiled')
        self.assertTrue(result['artifact']['format_valid'])
        self.assertFalse(result['artifact']['runtime_tested'])
        self.assertTrue(self.toolkit.verified_builds())
        self.assertEqual(self.toolkit.unvalidated_paths, set())
        self.assertEqual(self.toolkit.passed_checks, 1)
        self.assertEqual(popen.call_args.kwargs['shell'], False)
        self.assertEqual(popen.call_args.args[0], [
            'go', 'build', '-o', 'build_output/SYTOX_Program.exe', '.'
        ])

    @patch('sytox.actions.platform.system', return_value='Windows')
    @patch('sytox.actions.subprocess.Popen')
    def test_no_success_on_nonzero_compiler(self, popen, system):
        self.toolkit.approval = lambda *_: True
        proc = fake_compiler()
        proc.returncode = 1
        popen.return_value = proc
        with self.assertRaisesRegex(RuntimeError, 'Compiler-Fehler'):
            self.toolkit.action_project_build()
        self.assertEqual(self.toolkit.built_artifacts, [])

    @patch('sytox.actions.platform.system', return_value='Windows')
    @patch('sytox.actions.subprocess.Popen')
    def test_corrupt_exe_is_not_accepted(self, popen, system):
        self.toolkit.approval = lambda *_: True

        def build(*_args, **_kwargs):
            output = self.root / 'build_output' / 'SYTOX_Program.exe'
            output.parent.mkdir()
            output.write_bytes(b'not an executable')
            return fake_compiler()

        popen.side_effect = build
        with self.assertRaises(ValueError):
            self.toolkit.action_project_build()
        self.assertFalse(self.toolkit.verified_builds())

    @patch('sytox.actions.platform.system', return_value='Windows')
    @patch('sytox.actions.subprocess.Popen')
    def test_post_build_tampering_invalidates_receipt(self, popen, system):
        self.toolkit.approval = lambda *_: True

        def build(*_args, **_kwargs):
            write_fake_pe(self.root / 'build_output' / 'SYTOX_Program.exe')
            return fake_compiler()

        popen.side_effect = build
        self.toolkit.action_project_build()
        file = self.root / 'build_output' / 'SYTOX_Program.exe'
        with file.open('ab') as f:
            f.write(b'tampered')
        self.assertEqual(self.toolkit.verified_builds(), [])

    def test_linux_build_is_rejected(self):
        with patch('sytox.actions.platform.system', return_value='Linux'):
            with self.assertRaises(RuntimeError):
                self.toolkit.action_project_build()


class CompletionGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'database.db')
        self.chat = self.store.create_chat('Demo')

    def agent(self, goal, responses):
        self.store.add_message(self.chat, 'user', goal)
        worker = Agent(self.store, 'mock', 'http://unused', self.root / 'project',
                       lambda *_: True, lambda *_: None)
        worker.client.chat = Mock(side_effect=responses)
        return worker

    def test_cannot_claim_exe_finished_without_file(self):
        agent = self.agent('Erstelle ein Windows-Programm als EXE', [
            {'role': 'assistant', 'content': 'Fertig, hier ist die EXE!'}
        ])
        result = agent.run(self.chat, 'once')
        self.assertEqual(result['status'], 'paused')
        self.assertIn('nicht durch einen erfolgreichen Build', result['content'])

    def test_cannot_claim_installer_finished_from_program_build(self):
        def tool(name, **arguments):
            return {'role': 'assistant', 'content': '',
                    'tool_calls': [{'function': {'name': name, 'arguments': arguments}}]}
        agent = self.agent('Programmiere eine App mit Installer', [
            tool('write_file', path='main.py', content='print(1)'),
            tool('run_command', command='python -m compileall main.py'),
            tool('complete_task', summary='Installer fertig', evidence='compileall'),
            tool('report_blocker', reason='Installer noch nicht gebaut'),
        ])
        result = agent.run(self.chat, 'until_done')
        self.assertEqual(result['status'], 'paused')


if __name__ == '__main__':
    unittest.main()
