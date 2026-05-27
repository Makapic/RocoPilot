"""Train YOLO model on geli dataset (hepingge + juhuali)."""
import os
import shutil

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from ultralytics import YOLO

DATA_YAML = os.path.join(_BASE, "datasets", "geli", "data.yaml")
MODEL_PATH = os.path.join(_BASE, "yolo26s.pt")

if not os.path.exists(MODEL_PATH):
    MODEL_PATH = "yolo26s.pt"

print(f"数据: {DATA_YAML}")
print(f"预训练模型: {MODEL_PATH}")
print("开始训练 geli 模型...")

model = YOLO(MODEL_PATH)
model.train(
    data=DATA_YAML,
    epochs=50,
    batch=8,
    imgsz=640,
    device=0,
    workers=0,
    plots=True,
    verbose=True,
    val=False,
    mosaic=1.0,
    flipud=0.5,
    fliplr=0.5,
    hsv_h=0.015,
    hsv_s=0.7,
    hsv_v=0.4,
    scale=0.5,
    translate=0.1,
    erasing=0.4,
)

# Find latest training run and copy best.pt
os.makedirs(os.path.join(_BASE, "models"), exist_ok=True)
runs_dir = os.path.join(_BASE, "runs", "detect")
train_dirs = sorted(
    [d for d in os.listdir(runs_dir) if d.startswith("train")],
    key=lambda d: os.path.getmtime(os.path.join(runs_dir, d)),
    reverse=True,
)
dst = os.path.join(_BASE, "models", "geli.pt")
if train_dirs:
    src = os.path.join(runs_dir, train_dirs[0], "weights", "best.pt")
    if os.path.exists(src):
        shutil.copy2(src, dst)
        print(f"\n训练完成！模型已保存: {dst} (来自 {train_dirs[0]})")
    else:
        print(f"\n训练完成！但未找到 {src}，请手动复制 best.pt")
else:
    print("\n训练完成！未找到训练输出目录，请手动将 best.pt 复制到 models/geli.pt")
