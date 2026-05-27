"""Merge newly labeled xueren screenshots from datasets/ into datasets/xueren/."""
import os
import shutil
import re
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent
SRC_DIR = _BASE / "datasets"
DST_IMG = _BASE / "datasets" / "xueren" / "images"
DST_LBL = _BASE / "datasets" / "xueren" / "labels"

DST_IMG.mkdir(parents=True, exist_ok=True)
DST_LBL.mkdir(parents=True, exist_ok=True)

# Find highest existing number
existing = list(DST_IMG.glob("xueren_new_*.png"))
max_num = 0
for f in existing:
    m = re.search(r"xueren_new_(\d+)\.png$", f.name)
    if m:
        max_num = max(max_num, int(m.group(1)))

print(f"现有 xueren 数据集最高编号: {max_num:03d}")

# Find labeled pairs in datasets/ root (must have both .png and .txt)
png_files = sorted(SRC_DIR.glob("xueren_new_*.png"))
pairs = []
for png in png_files:
    txt = png.with_suffix(".txt")
    if txt.exists():
        pairs.append((png, txt))

print(f"在 datasets/ 中找到 {len(pairs)} 对已标注文件")

if not pairs:
    print("没有已标注的文件对，请先完成标注再运行此脚本。")
    exit(1)

# Rename and move
moved = 0
for png, txt in pairs:
    max_num += 1
    new_name = f"xueren_new_{max_num:03d}"
    shutil.move(str(png), str(DST_IMG / f"{new_name}.png"))
    shutil.move(str(txt), str(DST_LBL / f"{new_name}.txt"))
    moved += 1
    print(f"  {png.name} -> {new_name}.png")

print(f"\n完成！已将 {moved} 对文件合并到 datasets/xueren/")
print(f"总图片数: {len(list(DST_IMG.glob('*.png')))}")
print(f"总标签数: {len(list(DST_LBL.glob('*.txt')))}")
