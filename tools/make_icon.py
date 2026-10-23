# -*- coding: utf-8 -*-
"""生成 assets/icon.png 与 assets/icon.ico（多尺寸 PNG-in-ICO）。"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop.icon import icon_image  # noqa: E402


def png_bytes(size: int) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    icon_image(size).save(buf, "PNG")
    return bytes(buf.data())


def main() -> int:
    app = QGuiApplication([])  # noqa: F841
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    sizes = [16, 32, 48, 256]
    blobs = [(s, png_bytes(s)) for s in sizes]

    (out / "icon.png").write_bytes(dict(blobs)[256])
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries = b""
    for s, data in blobs:
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    (out / "icon.ico").write_bytes(header + entries + b"".join(d for _, d in blobs))
    print(out / "icon.ico", (out / "icon.ico").stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
