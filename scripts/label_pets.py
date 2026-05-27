"""精灵标注工具 — 用鼠标拖拽框出精灵，输出 YOLO 格式标签。

用法:
    uv run scripts/label_pets.py [--pet huolong] [图片目录]

默认从 datasets/{pet}/ 读取 PNG/JPG，标注结果保存到 datasets/{pet}/images/ 和 datasets/{pet}/labels/。

操作:
    鼠标拖拽    画框
    S           保存当前标注，跳到下一张
    D           删除当前图片（废片）
    R           清除当前图片所有框
    ← →        前一张 / 后一张
    Q           退出
"""

import argparse
import os
import shutil
import sys
from typing import List, Tuple

import cv2
import numpy as np

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_WIN_NAME = "Label Pets"
_BOX_COLOR = (0, 255, 0)
_BOX_THICKNESS = 2
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def _imread_unicode(path: str) -> np.ndarray | None:
    with open(path, "rb") as f:
        data = np.frombuffer(f.read(), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _list_images(src_dir: str) -> List[str]:
    exts = {".png", ".jpg", ".jpeg", ".bmp"}
    files = []
    for f in sorted(os.listdir(src_dir)):
        if os.path.splitext(f)[1].lower() in exts:
            files.append(f)
    return files


def _load_labels(label_path: str) -> List[Tuple[int, float, float, float, float]]:
    """读取 YOLO 格式标签，返回 [(cx, cy, w, h), ...] 归一化坐标。"""
    boxes = []
    if os.path.exists(label_path):
        with open(label_path, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 5:
                    cls_id = int(parts[0])
                    cx, cy, w, h = map(float, parts[1:5])
                    boxes.append((cls_id, cx, cy, w, h))
    return boxes


def _save_labels(label_path: str, boxes: List[Tuple[int, int, int, int]], img_w: int, img_h: int) -> None:
    """保存归一化 YOLO 格式标签。boxes 为像素坐标 (x1, y1, x2, y2)。"""
    os.makedirs(os.path.dirname(label_path), exist_ok=True)
    with open(label_path, "w") as f:
        for x1, y1, x2, y2 in boxes:
            x1_c = max(0, min(x1, x2))
            y1_c = max(0, min(y1, y2))
            x2_c = min(img_w, max(x1, x2))
            y2_c = min(img_h, max(y1, y2))
            bw, bh = x2_c - x1_c, y2_c - y1_c
            if bw <= 0 or bh <= 0:
                continue
            cx = (x1_c + bw / 2) / img_w
            cy = (y1_c + bh / 2) / img_h
            nw = bw / img_w
            nh = bh / img_h
            f.write(f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}\n")


class LabelTool:
    def __init__(self, src_dir: str, images_dir: str, labels_dir: str) -> None:
        self.src_dir = src_dir
        self.images_dir = images_dir
        self.labels_dir = labels_dir
        self.files = _list_images(src_dir)
        if not self.files:
            print(f"[错误] {src_dir} 中没有图片文件")
            sys.exit(1)
        self.idx = 0
        self.img: np.ndarray | None = None
        self.display: np.ndarray | None = None
        self.boxes: List[Tuple[int, int, int, int]] = []  # 像素坐标 (x1, y1, x2, y2)
        self.drawing = False
        self.start_pt: Tuple[int, int] = (0, 0)
        self.current_pt: Tuple[int, int] = (0, 0)
        self.img_h = 0
        self.img_w = 0

    # ── 图片加载 ────────────────────────────────────────────────────────

    def _load_current(self) -> None:
        path = os.path.join(self.src_dir, self.files[self.idx])
        self.img = _imread_unicode(path)
        if self.img is None:
            print(f"[警告] 无法读取: {path}")
            return
        self.img_h, self.img_w = self.img.shape[:2]

        # 尝试加载已有标签
        stem = os.path.splitext(self.files[self.idx])[0]
        label_path = os.path.join(self.labels_dir, f"{stem}.txt")
        saved = _load_labels(label_path)
        self.boxes = []
        for cls_id, cx, cy, w, h in saved:
            x1 = int((cx - w / 2) * self.img_w)
            y1 = int((cy - h / 2) * self.img_h)
            x2 = int((cx + w / 2) * self.img_w)
            y2 = int((cy + h / 2) * self.img_h)
            self.boxes.append((x1, y1, x2, y2))

    # ── 显示 ────────────────────────────────────────────────────────────

    def _render(self) -> None:
        self.display = self.img.copy()

        # 画已确认的框
        for x1, y1, x2, y2 in self.boxes:
            cv2.rectangle(self.display, (x1, y1), (x2, y2), _BOX_COLOR, _BOX_THICKNESS)

        # 画正在拖拽的框
        if self.drawing:
            cv2.rectangle(self.display, self.start_pt, self.current_pt, (255, 255, 0), 1)

        # HUD
        total = len(self.files)
        name = self.files[self.idx]
        info = f"[{self.idx + 1}/{total}] {name}  boxes: {len(self.boxes)}"
        cv2.putText(self.display, info, (10, self.img_h - 10), _FONT, 0.5, (0, 255, 255), 1)

        # 快捷键提示
        hints = "S:保存 D:删除 R:清除 Q:退出"
        cv2.putText(self.display, hints, (10, 20), _FONT, 0.45, (200, 200, 200), 1)

        cv2.imshow(_WIN_NAME, self.display)

    # ── 鼠标回调 ────────────────────────────────────────────────────────

    def _on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.start_pt = (x, y)
            self.current_pt = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self.current_pt = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self.drawing = False
            x1, y1 = self.start_pt
            x2, y2 = x, y
            if abs(x2 - x1) > 5 and abs(y2 - y1) > 5:
                self.boxes.append((x1, y1, x2, y2))

    # ── 操作 ────────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self.boxes:
            print(f"[跳过] {self.files[self.idx]} — 没有标注框")
            return
        stem = os.path.splitext(self.files[self.idx])[0]
        src_path = os.path.join(self.src_dir, self.files[self.idx])
        dst_img = os.path.join(self.images_dir, self.files[self.idx])
        label_path = os.path.join(self.labels_dir, f"{stem}.txt")

        os.makedirs(self.images_dir, exist_ok=True)
        _save_labels(label_path, self.boxes, self.img_w, self.img_h)
        shutil.move(src_path, dst_img)
        del self.files[self.idx]
        print(f"[保存] {self.files[self.idx] if self.idx < len(self.files) else '完成'} "
              f"— {len(self.boxes)} 个框")

        if not self.files:
            print("所有图片已标注完毕！")
            return

        if self.idx >= len(self.files):
            self.idx = len(self.files) - 1
        self._load_current()

    def _delete(self) -> None:
        path = os.path.join(self.src_dir, self.files[self.idx])
        os.remove(path)
        print(f"[删除] {self.files[self.idx]}")
        del self.files[self.idx]
        if not self.files:
            print("所有图片已处理完毕！")
            return
        if self.idx >= len(self.files):
            self.idx = len(self.files) - 1
        self._load_current()

    def _clear_boxes(self) -> None:
        self.boxes.clear()

    def _prev(self) -> None:
        if self.idx > 0:
            self.idx -= 1
            self._load_current()

    def _next(self) -> None:
        if self.idx < len(self.files) - 1:
            self.idx += 1
            self._load_current()

    # ── 主循环 ──────────────────────────────────────────────────────────

    def run(self) -> None:
        cv2.namedWindow(_WIN_NAME, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(_WIN_NAME, self._on_mouse)

        self._load_current()
        if self.img is None:
            print("[错误] 无法加载第一张图片")
            return

        print(f"共 {len(self.files)} 张图片待标注")
        print("操作: 鼠标拖拽=画框  S=保存  D=删除  R=清除  ←→=切换  Q=退出")

        while self.files:
            self._render()
            key = cv2.waitKey(0) & 0xFF

            if key == ord('q'):
                break
            elif key == ord('s'):
                self._save()
            elif key == ord('d'):
                self._delete()
            elif key == ord('r'):
                self._clear_boxes()
            elif key == 81 or key == 2424832:  # left arrow
                self._prev()
            elif key == 83 or key == 2555904:  # right arrow
                self._next()
            elif key == ord('a'):
                self._prev()
            elif key == ord('f'):
                self._next()

        cv2.destroyAllWindows()
        remaining = len(self.files)
        print(f"退出。已标注图片在 {self.images_dir}，待标注 {remaining} 张仍在 {self.src_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="精灵标注工具")
    parser.add_argument("--pet", "-p", default="huolong",
                        help="精灵名称 (默认: huolong)")
    parser.add_argument("src", nargs="?",
                        help="图片目录 (默认: datasets/{pet}/)")
    args = parser.parse_args()

    pet_dataset = os.path.join(_BASE, "datasets", args.pet)
    src = os.path.abspath(args.src) if args.src else pet_dataset
    images_dir = os.path.join(pet_dataset, "images")
    labels_dir = os.path.join(pet_dataset, "labels")
    os.makedirs(pet_dataset, exist_ok=True)

    if not os.path.isdir(src):
        print(f"[错误] 目录不存在: {src}")
        sys.exit(1)

    print(f"精灵标注工具 — {args.pet}")
    print(f"  图片目录: {src}")
    print(f"  输出目录: {images_dir}")
    LabelTool(src, images_dir, labels_dir).run()


if __name__ == "__main__":
    main()
