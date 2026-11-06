"""Regression checks for generating a real multi-resolution Windows icon."""
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from tools.build_icon import ICON_SIZES, build_icon

ROOT = Path(__file__).resolve().parents[1]


class WindowsIconTests(unittest.TestCase):
    def test_user_icon_is_a_real_png_and_builds_all_windows_sizes(self):
        source = ROOT / "assets" / "sytox-app.png"
        self.assertTrue(source.is_file())
        with Image.open(source) as artwork:
            self.assertEqual(artwork.format, "PNG")
            self.assertEqual(artwork.width, artwork.height)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sytox.ico"
            self.assertEqual(build_icon(source, target), target)
            self.assertGreater(target.stat().st_size, 1000)
            with Image.open(target) as icon:
                self.assertEqual(icon.format, "ICO")
                self.assertTrue({(n, n) for n in ICON_SIZES}.issubset(icon.ico.sizes()))

    def test_missing_source_fails_before_overwriting_existing_icon(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "sytox.ico"
            target.write_bytes(b"original")
            with self.assertRaises(FileNotFoundError):
                build_icon(Path(directory) / "not-found.png", target)
            self.assertEqual(target.read_bytes(), b"original")

    def test_exe_and_installer_use_same_generated_icon(self):
        exe = (ROOT / "Build_EXE.ps1").read_text(encoding="utf-8")
        installer = (ROOT / "Windows_Installer.iss").read_text(encoding="utf-8")
        self.assertIn("tools\\build_icon.py", exe)
        self.assertIn("--source assets\\sytox-app.png --output assets\\sytox.ico", exe)
        self.assertLess(exe.index("tools\\build_icon.py"), exe.index("-m PyInstaller"))
        self.assertIn("--icon assets\\sytox.ico", exe)
        self.assertIn("SetupIconFile=assets\\sytox.ico", installer)


if __name__ == "__main__":
    unittest.main()
