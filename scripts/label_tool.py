"""Simple YOLO labeling tool using OpenCV.

Mouse: drag to draw box
Keys:
  0-9    select class ID
  W      confirm current box
  S      save all boxes for current image
  A/D    prev/next image
  C      clear current boxes
  Del    delete last box
  Q      quit
"""

import cv2
import sys
from pathlib import Path
from argparse import ArgumentParser

BOX_COLORS = [
    (0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0),
    (255, 0, 255), (0, 255, 255), (128, 255, 0), (255, 128, 0),
    (0, 128, 255), (128, 0, 255),
]


class LabelTool:
    def __init__(self, img_dir: str, class_file: str = None):
        self.img_dir = Path(img_dir)
        self.img_files = sorted(self.img_dir.glob("*.png")) + sorted(
            self.img_dir.glob("*.jpg")
        )
        if not self.img_files:
            print(f"[错误] {img_dir} 中没有找到图片")
            sys.exit(1)

        # Load or create class list
        class_path = Path(class_file) if class_file else self.img_dir / "classes.txt"
        if class_path.exists():
            self.classes = class_path.read_text(encoding="utf-8").strip().split("\n")
        else:
            self.classes = []

        self.class_path = class_path
        self.idx = 0
        self.boxes = []  # (cls_id, x1, y1, x2, y2)
        self.drawing = False
        self.start_pt = None
        self.current_cls = 0
        self.img = None
        self.display = None
        self.img_h, self.img_w = 0, 0
        self.win_name = "YOLO Label Tool"

        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(self.win_name, self._mouse_cb)

    def _mouse_cb(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.start_pt = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            tmp = self.display.copy()
            cv2.rectangle(tmp, self.start_pt, (x, y), BOX_COLORS[self.current_cls], 2)
            cv2.imshow(self.win_name, tmp)
        elif event == cv2.EVENT_LBUTTONUP:
            self.drawing = False
            x1, y1 = self.start_pt
            x2, y2 = x, y
            if abs(x2 - x1) > 3 and abs(y2 - y1) > 3:
                self.boxes.append((self.current_cls, min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
                print(f"  框 #{len(self.boxes)}: class={self.current_cls} ({x1},{y1})-({x2},{y2})")
            self._redraw()

    def _load_image(self):
        path = self.img_files[self.idx]
        self.img = cv2.imread(str(path))
        if self.img is None:
            print(f"[错误] 无法读取: {path}")
            return False
        self.img_h, self.img_w = self.img.shape[:2]

        # Load existing annotation if any
        label_path = path.with_suffix(".txt")
        self.boxes = []
        if label_path.exists():
            for line in label_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 5:
                    cls_id = int(parts[0])
                    cx, cy, w, h = map(float, parts[1:5])
                    x1 = int((cx - w / 2) * self.img_w)
                    y1 = int((cy - h / 2) * self.img_h)
                    x2 = int((cx + w / 2) * self.img_w)
                    y2 = int((cy + h / 2) * self.img_h)
                    self.boxes.append((cls_id, x1, y1, x2, y2))
        return True

    def _save_annotation(self):
        path = self.img_files[self.idx]
        label_path = path.with_suffix(".txt")
        lines = []
        for cls_id, x1, y1, x2, y2 in self.boxes:
            cx = ((x1 + x2) / 2) / self.img_w
            cy = ((y1 + y2) / 2) / self.img_h
            w = (x2 - x1) / self.img_w
            h = (y2 - y1) / self.img_h
            lines.append(f"{cls_id} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
        label_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  已保存 -> {label_path.name} ({len(self.boxes)} 个框)")

        # Save classes.txt
        if self.classes:
            self.class_path.write_text("\n".join(self.classes), encoding="utf-8")

    def _redraw(self):
        self.display = self.img.copy()
        for cls_id, x1, y1, x2, y2 in self.boxes:
            color = BOX_COLORS[cls_id % len(BOX_COLORS)]
            cv2.rectangle(self.display, (x1, y1), (x2, y2), color, 2)
            label = f"{cls_id}:{self.classes[cls_id]}" if cls_id < len(self.classes) else str(cls_id)
            cv2.putText(self.display, label, (x1, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        # Status bar
        total = len(self.img_files)
        progress = f"[{self.idx + 1}/{total}]"
        name = self.img_files[self.idx].name
        cls_name = self.classes[self.current_cls] if self.current_cls < len(self.classes) else f"class_{self.current_cls}"
        status = f"{progress} {name} | class: {self.current_cls}({cls_name}) | boxes: {len(self.boxes)} | A/D:nav W:confirm S:save C:clear Q:quit"

        bar = self.display.copy()
        h = bar.shape[0]
        cv2.rectangle(bar, (0, h - 28), (self.img_w, h), (40, 40, 40), -1)
        cv2.addWeighted(bar, 0.6, self.display, 0.4, 0, self.display)
        cv2.putText(self.display, status, (8, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
        cv2.imshow(self.win_name, self.display)

    def _add_class(self, name: str):
        if name not in self.classes:
            self.classes.append(name)
            self.class_path.write_text("\n".join(self.classes), encoding="utf-8")
            print(f"  新类别: {name} (id={self.classes.index(name)})")
        else:
            self.current_cls = self.classes.index(name)
            print(f"  切换到: {name} (id={self.current_cls})")

    def run(self):
        if not self._load_image():
            return
        self._redraw()

        while True:
            key = cv2.waitKey(0) & 0xFF

            if key == ord("q"):
                break
            elif key == ord("d"):
                self._save_annotation()
                self.idx = min(self.idx + 1, len(self.img_files) - 1)
                self._load_image()
                self._redraw()
            elif key == ord("a"):
                self._save_annotation()
                self.idx = max(self.idx - 1, 0)
                self._load_image()
                self._redraw()
            elif key == ord("s"):
                self._save_annotation()
            elif key == ord("c"):
                self.boxes.clear()
                print("  已清空所有框")
                self._redraw()
            elif key == 255:  # Delete key
                if self.boxes:
                    removed = self.boxes.pop()
                    print(f"  已删除框: class={removed[0]}")
                    self._redraw()
            elif key in range(ord("0"), ord("9") + 1):
                self.current_cls = key - ord("0")
                cls_name = self.classes[self.current_cls] if self.current_cls < len(self.classes) else f"class_{self.current_cls}"
                print(f"  当前类别: {self.current_cls} ({cls_name})")
                self._redraw()
            elif key == 13:  # Enter - add new class
                self._prompt_new_class()

        cv2.destroyAllWindows()

    def _prompt_new_class(self):
        """Prompt for a new class name in terminal."""
        print("\n请输入新类别名称（或按回车取消）:")
        name = input("> ").strip()
        if name:
            self._add_class(name)
            self._redraw()


if __name__ == "__main__":
    import os as _os
    _BASE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _DEFAULT = _os.path.join(_BASE, "datasets", "huolong")

    ap = ArgumentParser(description="YOLO label tool")
    ap.add_argument("img_dir", nargs="?", default=_DEFAULT, help="Image directory")
    ap.add_argument("--classes", "-c", default=None, help="classes.txt path")
    args = ap.parse_args()

    print("YOLO 标注工具")
    print("  鼠标拖拽画框 | 0-9 选类别 | W 确认框 | S 保存 | A/D 切换图片 | C 清除 | Del 删除 | Enter 新类别 | Q 退出")
    print()
    LabelTool(args.img_dir, args.classes).run()
