import os
from typing import List, Tuple

import numpy as np

from config import CONFIG


class PetDetector:
    def __init__(self) -> None:
        self._model = None

    def preload(self) -> None:
        """提前加载模型，避免首帧检测时卡顿。"""
        self._ensure_model()

    def _ensure_model(self):
        if self._model is not None:
            return
        from ultralytics import YOLO
        model_path = os.path.join(CONFIG.pet_model_dir, f"{CONFIG.pet_model_name}.pt")
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"模型未找到: {model_path}，请先运行 scripts/train_xueren.py 训练模型"
            )
        self._model = YOLO(model_path)
        print(f"[PetDetector] 模型已加载: {CONFIG.pet_model_name} ({model_path}) (conf≥{CONFIG.pet_conf_threshold})")

    def detect(self, frame_bgr: np.ndarray) -> List[Tuple[int, int, int, int, float]]:
        """返回 [(cx, cy, w, h, conf), ...] 坐标均为像素坐标。"""
        self._ensure_model()
        results = self._model(frame_bgr, verbose=False, conf=CONFIG.pet_conf_threshold)
        detections = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)
                w = int(x2 - x1)
                h = int(y2 - y1)
                if w > 0 and h > 0:
                    detections.append((cx, cy, w, h, conf))
        return sorted(detections, key=lambda d: d[4], reverse=True)
