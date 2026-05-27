"""Build standalone executable using PyInstaller.

Usage:
    python build.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
DIST_DIR = PROJECT_DIR / "dist"
TEMPLATES_DIR = PROJECT_DIR / "templates"

PYINSTALLER_COMMON = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onedir",
    "--console",
    f"--add-data={TEMPLATES_DIR};templates",
    f"--paths={PROJECT_DIR}",
]

NAME = "RocoPilot"

EXTRA_ARGS = [
    "--collect-all=ultralytics",
    "--collect-all=torch",
    "--collect-all=torchvision",
]


def build() -> None:
    cmd = [*PYINSTALLER_COMMON, f"--name={NAME}", *EXTRA_ARGS, "main.py"]
    print(f"\n{'='*60}")
    print(f"Building {NAME} ...")
    print(f"{'='*60}\n")
    subprocess.check_call(cmd, cwd=PROJECT_DIR)

    out_dir = DIST_DIR / NAME
    for doc in ("README.md", "CHANGELOG.md"):
        src = PROJECT_DIR / doc
        if src.exists():
            shutil.copy2(src, out_dir / doc)

    print(f"\n[OK] {NAME} built -> {out_dir}")


def main() -> None:
    build()
    print(f"\nDone. Output in {DIST_DIR}")


if __name__ == "__main__":
    main()
