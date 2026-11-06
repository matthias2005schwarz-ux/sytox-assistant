"""Generate the genuine Windows PE and installer icon from the selected SYTOX artwork.

The original PNG remains the source of truth. A multi-resolution .ico is
regenerated before PyInstaller and Inno Setup run, so the taskbar, Explorer,
desktop shortcut and setup executable all use matching branding.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageOps

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
ROOT = Path(__file__).resolve().parents[1]


def build_icon(source: Path, destination: Path) -> Path:
    if not source.is_file():
        raise FileNotFoundError(f"SYTOX app icon PNG missing: {source}")

    with Image.open(source) as original:
        original.load()
        artwork = original.convert("RGBA")

    if not artwork.getbbox():
        raise ValueError("SYTOX icon is fully transparent")
    # Windows uses several icon sizes; keep all in the ICO instead of copying
    # the PNG bytes to a misleading .ico extension.
    fitted = ImageOps.contain(artwork, (256, 256), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    canvas.alpha_composite(
        fitted, ((256 - fitted.width) // 2, (256 - fitted.height) // 2)
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(
        destination, format="ICO", sizes=[(n, n) for n in ICON_SIZES]
    )
    with Image.open(destination) as verified:
        sizes = set(verified.ico.sizes())
    required = {(n, n) for n in ICON_SIZES}
    if not required.issubset(sizes):
        raise RuntimeError(f"Generated ICO is missing sizes: {required - sizes}")
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "assets" / "sytox-app.png")
    parser.add_argument("--output", type=Path, default=ROOT / "assets" / "sytox.ico")
    args = parser.parse_args()
    created = build_icon(args.source, args.output)
    print(f"SYTOX Windows icon: {created} ({created.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
