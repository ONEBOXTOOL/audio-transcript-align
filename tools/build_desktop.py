# -*- coding: utf-8 -*-
"""构建 Windows 桌面版（PyInstaller onedir）。

用法：
    .venv\\Scripts\\python.exe tools\\build_desktop.py            # 带模型
    .venv\\Scripts\\python.exe tools\\build_desktop.py --no-model # 只验证 UI/依赖
    .venv\\Scripts\\python.exe tools\\build_desktop.py --zip      # 额外打绿色 zip
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-model", action="store_true", help="不把 models/ 打进产物")
    ap.add_argument("--zip", action="store_true", help="构建后生成绿色 zip")
    args = ap.parse_args()

    model_dir = ROOT / "models" / "small.en"
    if not args.no_model and not (model_dir / "model.bin").exists():
        print(f"ERROR: 缺少模型 {model_dir}", file=sys.stderr)
        return 1

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", "AudioAlign",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        "--collect-all", "ctranslate2",
        "--collect-all", "av",
        "--collect-all", "onnxruntime",
        "--collect-all", "faster_whisper",
        "--collect-all", "tokenizers",
        "--copy-metadata", "faster-whisper",
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "PySide6.QtQuick3D",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "PySide6.QtCharts",
        "--exclude-module", "PySide6.QtDataVisualization",
        "--exclude-module", "PySide6.QtPdf",
    ]
    if not args.no_model:
        cmd += ["--add-data", f"{model_dir}{os.pathsep}{os.path.join('models', 'small.en')}"]
    icon = ROOT / "assets" / "icon.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]
    cmd.append("run_desktop.py")

    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)

    exe = ROOT / "dist" / "AudioAlign" / "AudioAlign.exe"
    if not exe.exists():
        print(f"ERROR: 没找到 {exe}", file=sys.stderr)
        return 1
    for name in ("THIRD_PARTY_NOTICES.md", "docs/desktop-quickstart.txt"):
        src = ROOT / name
        if src.exists():
            dst = exe.parent / ("使用说明.txt" if name.endswith("quickstart.txt") else src.name)
            shutil.copy2(src, dst)
    print(f"OK: {exe}")

    if args.zip:
        archive = shutil.make_archive(
            str(ROOT / "dist" / "AudioAlign-win64"), "zip",
            root_dir=ROOT / "dist", base_dir="AudioAlign",
        )
        print(f"ZIP: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
