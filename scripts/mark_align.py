"""对齐标定工具 — 标记背景固定物体，测量像素位移以校准鼠标灵敏度。

用法:
    # 现场标定：自动截图、复合移动视角、截图、打开标记窗口
    uv run scripts/mark_align.py --capture [--step-h 200] [--step-v 100]

操作:
    左键     在当前图片上标记/移动标定点
    S        保存灵敏度到 user_prefs.json
    Q        退出
"""

import argparse
import json
import os
import sys
import time

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

import cv2
import interception
import numpy as np

from core.window import find_window_by_keyword, get_client_rect_on_screen

_WIN_NAME = "Alignment Calibration"
_CROSS_SIZE = 20
_CROSS_COLOR1 = (0, 255, 0)
_CROSS_COLOR2 = (0, 255, 255)
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_PREFS_PATH = os.path.join(_BASE, "user_prefs.json")


def _load_prefs() -> dict:
    try:
        with open(_PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_prefs(prefs: dict) -> None:
    with open(_PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


class AlignMarker:
    """并排显示两张截图，点击标记同一个物体，计算水平和垂直灵敏度。"""

    def __init__(self, img1: np.ndarray, img2: np.ndarray,
                 step_h: int, step_v: int) -> None:
        self.img1 = img1
        self.img2 = img2
        self.h1, self.w1 = img1.shape[:2]
        self.h2, self.w2 = img2.shape[:2]
        self.step_h = step_h
        self.step_v = step_v

        self.pt1 = None  # (x, y) on img1
        self.pt2 = None  # (x, y) on img2
        self.ratio_h = 0.0
        self.ratio_v = 0.0

        self.canvas_h = max(self.h1, self.h2)
        self.img2_left = self.w1 + 4  # img2 在画布上的起始 x（跳过 4px 分隔线）

        cv2.namedWindow(_WIN_NAME, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(_WIN_NAME, self._on_mouse)

    def _on_mouse(self, event, x, y, flags, param) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            if x < self.w1 and y < self.h1:
                self.pt1 = (x, y)
                print(f"  标定点1: ({x}, {y})")
            elif x >= self.img2_left and x < self.img2_left + self.w2 and y < self.h2:
                self.pt2 = (x - self.img2_left, y)
                print(f"  标定点2: ({x - self.img2_left}, {y})")
        elif event == cv2.EVENT_RBUTTONDOWN:
            if x < self.w1:
                self.pt1 = None
                print("  已清除标定点1")
            elif x >= self.img2_left:
                self.pt2 = None
                print("  已清除标定点2")

    def _draw_cross(self, canvas, cx, cy, color):
        cv2.line(canvas, (cx - _CROSS_SIZE, cy), (cx + _CROSS_SIZE, cy), color, 2)
        cv2.line(canvas, (cx, cy - _CROSS_SIZE), (cx, cy + _CROSS_SIZE), color, 2)
        cv2.circle(canvas, (cx, cy), 4, color, 1)

    def _render(self) -> None:
        canvas = cv2.copyMakeBorder(
            self.img1, 0, self.canvas_h - self.h1, 0, 0,
            cv2.BORDER_CONSTANT, value=(20, 20, 20),
        )
        right = cv2.copyMakeBorder(
            self.img2, 0, self.canvas_h - self.h2, 0, 0,
            cv2.BORDER_CONSTANT, value=(20, 20, 20),
        )
        sep = cv2.copyMakeBorder(right, 0, 0, 0, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        canvas = cv2.hconcat([canvas, sep])

        if self.pt1 is not None:
            self._draw_cross(canvas, self.pt1[0], self.pt1[1], _CROSS_COLOR1)
            cv2.putText(canvas, f"P1 ({self.pt1[0]}, {self.pt1[1]})",
                        (self.pt1[0] + _CROSS_SIZE + 4, self.pt1[1] - 24),
                        _FONT, 0.45, _CROSS_COLOR1, 1)

        if self.pt2 is not None:
            px2, py2 = self.pt2[0] + self.img2_left, self.pt2[1]
            self._draw_cross(canvas, px2, py2, _CROSS_COLOR2)
            cv2.putText(canvas, f"P2 ({self.pt2[0]}, {self.pt2[1]})",
                        (px2 + _CROSS_SIZE + 4, py2 - 24),
                        _FONT, 0.45, _CROSS_COLOR2, 1)

        info = None
        if self.pt1 is not None and self.pt2 is not None:
            dx = self.pt2[0] - self.pt1[0]
            dy = self.pt2[1] - self.pt1[1]
            self.ratio_h = abs(dx) / self.step_h if self.step_h > 0 else 0
            self.ratio_v = abs(dy) / self.step_v if self.step_v > 0 else 0

            info = (
                f"dx={dx:+d}px (step_h={self.step_h})  ratio_h={self.ratio_h:.4f} px/u  |  "
                f"dy={dy:+d}px (step_v={self.step_v})  ratio_v={self.ratio_v:.4f} px/u"
            )
            cv2.putText(canvas, info, (10, 30), _FONT, 0.5, (255, 255, 255), 2)
            cv2.putText(canvas, info, (10, 30), _FONT, 0.5, (0, 200, 255), 1)

        hint = "L:标记  R:清除单点"
        if self.pt1 is not None and self.pt2 is not None:
            hint += "  |  已自动保存"
        hint += "  |  Q:退出"
        cv2.putText(canvas, hint, (10, self.canvas_h - 10),
                    _FONT, 0.45, (160, 160, 160), 1)

        cv2.putText(canvas, "1 — 移动前", (10, 8), _FONT, 0.5, _CROSS_COLOR1, 2)
        cv2.putText(canvas, "2 — 移动后（右移+上移）", (self.img2_left + 10, 8),
                    _FONT, 0.5, _CROSS_COLOR2, 2)
        if info:
            cv2.putText(canvas, "移动: →" + str(self.step_h) + "u  ↑" + str(self.step_v) + "u",
                        (self.img2_left + 10, 24), _FONT, 0.4, (180, 180, 180), 1)

        cv2.imshow(_WIN_NAME, canvas)

    def _save_ratio(self) -> None:
        prefs = _load_prefs()
        prefs["pet_aim_pixels_per_unit_h"] = round(self.ratio_h, 4)
        prefs["pet_aim_pixels_per_unit_v"] = round(self.ratio_v, 4)
        _save_prefs(prefs)
        print(f"  已保存到 {_PREFS_PATH}:")
        print(f"    ratio_h = {self.ratio_h:.4f} px/unit")
        print(f"    ratio_v = {self.ratio_v:.4f} px/unit")

    def run(self) -> tuple[float, float]:
        print(f"对齐标定工具")
        print(f"  图片1: {self.w1}x{self.h1}")
        print(f"  图片2: {self.w2}x{self.h2}")
        print(f"  水平步长: {self.step_h}u, 垂直步长: {self.step_v}u")
        print(f"操作: 左键标点 | 右键清除 | 两点标记后自动保存 | Q 退出")
        print()

        _saved = False
        while True:
            self._render()
            # 两点标记好后自动保存，不需要按 S
            if self.pt1 is not None and self.pt2 is not None and not _saved:
                self._save_ratio()
                _saved = True
            elif (self.pt1 is None or self.pt2 is None) and _saved:
                _saved = False  # 清除后允许重新保存

            key = cv2.waitKey(20) & 0xFF
            if key == ord('q'):
                break

        cv2.destroyAllWindows()
        return self.ratio_h, self.ratio_v


# ── 现场标定：截图 → 复合移动 → 截图 → 标记 ─────────────────────────────

def calibrate_live(step_h: int, step_v: int) -> tuple[float, float]:
    """现场标定：获取游戏窗口，截图，右移+上移视角，再截图，打开标记窗口。"""
    hwnd = find_window_by_keyword("洛克王国：世界")
    if hwnd is None:
        print("[错误] 未找到游戏窗口，请确保游戏已启动且窗口标题包含 '洛克王国：世界'")
        return 0.0, 0.0

    rect = get_client_rect_on_screen(hwnd)
    print(f"找到游戏窗口: {hwnd:#x} 区域=({rect[0]},{rect[1]}) {rect[2]}x{rect[3]}")

    from core.capture import capture_window_bgr

    # ---- 截图1 ----
    print("截图中（移动前）...")
    img1 = capture_window_bgr(hwnd)
    if img1 is None or img1.size == 0:
        print("[错误] 截图失败，请确保游戏窗口未最小化")
        return 0.0, 0.0
    h1, w1 = img1.shape[:2]
    print(f"  截图1: {w1}x{h1}")

    # ---- 复合移动（按住右键拖动视角） ----
    print(f"移动视角: →{step_h}  ↑{step_v} ...")
    interception.auto_capture_devices()
    interception.mouse_down('right')
    time.sleep(0.05)
    interception.move_relative(step_h, -step_v)
    time.sleep(0.5)
    interception.mouse_up('right')
    time.sleep(0.1)

    # ---- 截图2 ----
    print("截图中（移动后）...")
    img2 = capture_window_bgr(hwnd)
    if img2 is None or img2.size == 0:
        print("[错误] 截图2失败")
        return 0.0, 0.0
    h2, w2 = img2.shape[:2]
    print(f"  截图2: {w2}x{h2}")

    # ---- 标记 ----
    print(f"\n请在两张图上分别点击同一个背景固定物体，两点标记后自动保存。\n")
    marker = AlignMarker(img1, img2, step_h, step_v)
    ratio_h, ratio_v = marker.run()

    if ratio_h > 0 or ratio_v > 0:
        print(f"\n标定完成: ratio_h={ratio_h:.4f}  ratio_v={ratio_v:.4f}")
    return ratio_h, ratio_v


def main() -> None:
    parser = argparse.ArgumentParser(description="对齐标定工具 — 背景物体点标注")
    parser.add_argument("--capture", action="store_true",
                        help="现场标定模式：从游戏窗口截图并自动移动视角")
    parser.add_argument("--step-h", type=int, default=200,
                        help="水平移动步长 mouse units (默认: 200)")
    parser.add_argument("--step-v", type=int, default=100,
                        help="垂直移动步长 mouse units (默认: 100)")
    args = parser.parse_args()

    if args.capture:
        calibrate_live(args.step_h, args.step_v)
    else:
        print("[提示] 使用 --capture 进行现场标定，或手动提供两张截图路径")


if __name__ == "__main__":
    main()
