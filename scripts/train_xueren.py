"""Train YOLO model on xueren dataset, fine-tuning from existing xueren model."""
import os

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from ultralytics import YOLO

DATA_YAML = os.path.join(_BASE, "datasets", "xueren", "data.yaml")
MODEL_PATH = os.path.join(_BASE, "models", "xueren.pt")

print(f"数据: {DATA_YAML}")
print(f"基础模型: {MODEL_PATH} (从已有 xueren.pt 继续训练)")
print("开始训练 xueren 模型...")

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

# Copy trained model to models/
os.makedirs(os.path.join(_BASE, "models"), exist_ok=True)
import shutil
src = os.path.join(_BASE, "runs", "detect", "train", "weights", "best.pt")
dst = os.path.join(_BASE, "models", "xueren.pt")
if os.path.exists(src):
    shutil.copy2(src, dst)
    print(f"\n训练完成！模型已保存: {dst}")
else:
    print("\n训练完成！请手动将 best.pt 复制到 models/xueren.pt")
