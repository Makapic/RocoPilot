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
BUILD_DIR = PROJECT_DIR / "build"
TEMPLATES_DIR = PROJECT_DIR / "templates"
MODELS_DIR = PROJECT_DIR / "models"
LUOKE_OUT_DIR = PROJECT_DIR / "luoke_location_src" / "out"
LUOKE_SRC_DIR = PROJECT_DIR / "luoke_location_src"
CRUISE_CAPTURE_DIR = PROJECT_DIR / "cruise_capture"

PYINSTALLER_COMMON = [
    sys.executable, "-m", "PyInstaller",
    "--noconfirm",
    "--onedir",
    "--console",
    f"--add-data={TEMPLATES_DIR};templates",
    f"--paths={PROJECT_DIR}",
    "--clean",
]

NAME = "RocoPilot"

EXTRA_ARGS = [
    "--collect-all=ultralytics",
    "--collect-all=torch",
    "--collect-all=torchvision",
    "--hidden-import=luoke_location_src.cruise_main",
    "--hidden-import=luoke_location_src.config",
    "--hidden-import=luoke_location_src.main_sift",
    "--hidden-import=luoke_location_src.map_mask",
    "--hidden-import=luoke_location_src.screen_pick",
    "--hidden-import=cruise_capture.cruise_controller",
    f"--paths={LUOKE_SRC_DIR.parent}",
]


def _rmtree(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)


def _cleanup_build(out_dir: Path) -> None:
    """Remove files not needed at runtime to reduce package size."""
    internal = out_dir / "_internal"

    # Static import libraries (only needed for C++ compilation, not runtime)
    for lib in internal.rglob("*.lib"):
        lib.unlink()
        print(f"  Removed: {lib.relative_to(out_dir)}")

    # C++ headers bundled by torch
    for hdr_dir in [internal / "torch" / "include"]:
        if hdr_dir.exists():
            _rmtree(hdr_dir)
            print(f"  Removed: {hdr_dir.relative_to(out_dir)}")

    # Debug symbols
    for pat in ("*.pdb", "*.exp", "*.ilk"):
        for f in internal.rglob(pat):
            f.unlink()
            print(f"  Removed: {f.relative_to(out_dir)}")

    # Bytecode caches (not needed; .pyc files are handled by PyInstaller)
    for cache in internal.rglob("__pycache__"):
        _rmtree(cache)

    # ONNX Runtime — only used for model export, not inference
    onnx_dir = internal / "onnxruntime"
    if onnx_dir.exists():
        _rmtree(onnx_dir)
        print(f"  Removed: onnxruntime/")


def build() -> None:
    _rmtree(BUILD_DIR)
    _rmtree(DIST_DIR / NAME)

    cmd = [*PYINSTALLER_COMMON, f"--name={NAME}", *EXTRA_ARGS, "main.py"]
    print(f"\n{'='*60}")
    print(f"Building {NAME} ...")
    print(f"{'='*60}\n")
    subprocess.check_call(cmd, cwd=PROJECT_DIR)

    out_dir = DIST_DIR / NAME

    # ── Copy data directories next to the exe ──
    # models/ — YOLO pet detection models (resolved via _exe_dir())
    if MODELS_DIR.is_dir():
        dst = out_dir / "models"
        _rmtree(dst)
        shutil.copytree(MODELS_DIR, dst)
        print(f"[OK] Copied models/ -> {dst}")

    # out/ — SIFT map data for cruise mode (resolved via _runtime_base_dir())
    if LUOKE_OUT_DIR.is_dir():
        dst = out_dir / "out"
        _rmtree(dst)
        shutil.copytree(LUOKE_OUT_DIR, dst)
        print(f"[OK] Copied luoke_location_src/out/ -> {dst}")

    # luoke_location_src/ — Python sources for cruise subprocess (mode 3)
    # Copy to _internal/ so _find_cruise_script() resolves correctly when frozen
    internal_dir = out_dir / "_internal" / "luoke_location_src"
    _rmtree(internal_dir)
    shutil.copytree(
        LUOKE_SRC_DIR, internal_dir,
        ignore=shutil.ignore_patterns("__pycache__", "out", "exe_files", "examp_figs", ".gitignore"),
    )
    print(f"[OK] Copied luoke_location_src/ -> {internal_dir}")

    # cruise_capture/ — cruise controller module
    cruise_dst = out_dir / "_internal" / "cruise_capture"
    _rmtree(cruise_dst)
    if CRUISE_CAPTURE_DIR.is_dir():
        shutil.copytree(
            CRUISE_CAPTURE_DIR, cruise_dst,
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        print(f"[OK] Copied cruise_capture/ -> {cruise_dst}")

    # ── Copy docs ──
    for doc in ("README.md", "CHANGELOG.md"):
        src = PROJECT_DIR / doc
        if src.exists():
            shutil.copy2(src, out_dir / doc)

    # ── Prune unnecessary files ──
    _cleanup_build(out_dir)

    print(f"\n[OK] {NAME} built -> {out_dir}")


def main() -> None:
    build()
    print(f"\nDone. Output in {DIST_DIR}")


if __name__ == "__main__":
    main()
