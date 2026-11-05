"""Unit contracts for additional supported Windows project formats."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sytox.program_build import build_plan, inspect_build_artifact
from sytox.multilang_build import extra_plan
from sytox.actions import Toolkit

FILES = {
    'c': 'main.c', 'cpp': 'main.cpp', 'java': 'Main.java',
    'kotlin': 'Main.kt', 'javascript': 'main.js', 'typescript': 'main.ts',
    'php': 'main.php', 'lua': 'main.lua',
}

class MoreLanguageBuilds(unittest.TestCase):
    def test_every_extra_language_has_deterministic_plan(self):
        with patch('sytox.multilang_build.shutil.which', side_effect=lambda x: 'C:/Test/' + x + '.exe'):
            for language, entry in FILES.items():
                with self.subTest(language=language), tempfile.TemporaryDirectory() as tmp:
                    (Path(tmp) / entry).write_text('sample', encoding='utf-8')
                    plan = build_plan(Path(tmp))
                    self.assertEqual(plan['language'], language)
                    self.assertTrue(plan['requires_approval'])
                    self.assertTrue(plan['command'])
                    self.assertTrue(plan['expected_artifact'].startswith('build_output/'))

    def test_ambiguous_projects_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'main.js').write_text('console.log(1)')
            (Path(tmp) / 'Main.java').write_text('class Main {}')
            with self.assertRaisesRegex(ValueError, 'Mehrere'):
                extra_plan(Path(tmp))

    def test_scripts_not_native_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'build_output'
            dest.mkdir()
            file = dest / 'main.js'
            file.write_text('console.log(1)', encoding='utf-8')
            receipt = inspect_build_artifact(Path(tmp), 'build_output/main.js', 'script_js')
            self.assertEqual(receipt['format'], 'JavaScript')
            tk = object.__new__(Toolkit)
            tk.workspace = Path(tmp)
            tk.built_artifacts = [receipt]
            self.assertTrue(tk.verified_builds())
            self.assertFalse(tk.verified_exe_builds())

    def test_magic_bytes_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'build_output'
            dest.mkdir()
            (dest / 'Main.class').write_bytes(bytes([202,254,186,190]) + bytes(100))
            result = inspect_build_artifact(Path(tmp), 'build_output/Main.class', 'class')
            self.assertEqual(result['format'], 'JVM class')
            (dest / 'Main.class').write_bytes(b'wrong format')
            with self.assertRaises(ValueError):
                inspect_build_artifact(Path(tmp), 'build_output/Main.class', 'class')

    def test_changed_artifact_invalidates_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'build_output'
            dest.mkdir()
            file = dest / 'main.php'
            file.write_text('<?php echo 1;', encoding='utf-8')
            receipt = inspect_build_artifact(Path(tmp), 'build_output/main.php', 'script_php')
            tk = object.__new__(Toolkit)
            tk.workspace = Path(tmp)
            tk.built_artifacts = [receipt]
            self.assertTrue(tk.verified_builds())
            file.write_text('<?php echo 2;', encoding='utf-8')
            self.assertFalse(tk.verified_builds())

if __name__ == '__main__':
    unittest.main()
