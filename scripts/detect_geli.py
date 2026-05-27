"""Real-time geli detection every 0.2s with overlay on game window (hepingge + juhuali)."""
import atexit
import ctypes
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np
import win32con
import win32gui

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_PATH = os.path.join(_BASE, "models", "geli.pt")
_CLASS_NAMES = ["hepingge", "juhuali"]

# ── Transparent GDI overlay ──────────────────────────────────────────────────

_overlay_class_registered: bool = False


def _register_overlay_class():
    global _overlay_class_registered
    if _overlay_class_registered:
        return

    def _wnd_proc(hwnd, msg, wparam, lparam):
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)

    _register_overlay_class._wnd_proc = _wnd_proc

    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = _wnd_proc
    wc.lpszClassName = "GeliDetOverlay"
    wc.hInstance = win32gui.GetModuleHandle(None)
    wc.hbrBackground = win32gui.GetStockObject(5)  # NULL_BRUSH
    win32gui.RegisterClass(wc)
    _overlay_class_registered = True


CLASS_COLORS = [
    0x0000FF00,  # hepingge: green
    0x000000FF,  # juhuali: red
]


class OverlayWindow:
    """Transparent, click-through overlay on top of the game client area."""

    def __init__(self):
        self._hwnd = None
        self._width = 0
        self._height = 0

    def ensure(self, game_hwnd, x, y, w, h):
        if self._hwnd is not None and (w, h) != (self._width, self._height):
            self.destroy()
        if self._hwnd is None:
            _register_overlay_class()
            ex_style = (win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT |
                        win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW |
                        win32con.WS_EX_NOACTIVATE)
            self._hwnd = win32gui.CreateWindowEx(
                ex_style, "GeliDetOverlay", "",
                win32con.WS_POPUP, x, y, w, h,
                0, 0, win32gui.GetModuleHandle(None), None,
            )
            win32gui.SetLayeredWindowAttributes(self._hwnd, 0xFF00FF, 0, win32con.LWA_COLORKEY)
            win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)
            self._width, self._height = w, h
        else:
            win32gui.SetWindowPos(
                self._hwnd, win32con.HWND_TOPMOST, x, y, w, h,
                win32con.SWP_NOACTIVATE | win32con.SWP_SHOWWINDOW,
            )

    def update(self, detections, frame_w, frame_h):
        if not self._hwnd:
            return
        hdc = ctypes.windll.user32.GetDC(self._hwnd)
        mem_dc = ctypes.windll.gdi32.CreateCompatibleDC(hdc)
        bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc, self._width, self._height)
        old_bmp = ctypes.windll.gdi32.SelectObject(mem_dc, bmp)

        brush = ctypes.windll.gdi32.CreateSolidBrush(0x00FF00FF)
        rect = ctypes.wintypes.RECT(0, 0, self._width, self._height)
        ctypes.windll.user32.FillRect(mem_dc, ctypes.byref(rect), brush)
        ctypes.windll.gdi32.DeleteObject(brush)

        scale_x = self._width / frame_w
        scale_y = self._height / frame_h

        # Crosshair at center
        cx_c = self._width // 2
        cy_c = self._height // 2
        cross_pen = ctypes.windll.gdi32.CreatePen(0, 1, 0x00FFFF00)  # Cyan cross
        ctypes.windll.gdi32.SelectObject(mem_dc, cross_pen)
        ctypes.windll.gdi32.MoveToEx(mem_dc, cx_c - 15, cy_c, None)
        ctypes.windll.gdi32.LineTo(mem_dc, cx_c + 15, cy_c)
        ctypes.windll.gdi32.MoveToEx(mem_dc, cx_c, cy_c - 15, None)
        ctypes.windll.gdi32.LineTo(mem_dc, cx_c, cy_c + 15)
        ctypes.windll.gdi32.DeleteObject(cross_pen)

        # Detection boxes
        for cls_id, cx, cy, w, h, conf in detections:
            x1 = int((cx - w // 2) * scale_x)
            y1 = int((cy - h // 2) * scale_y)
            x2 = int((cx + w // 2) * scale_x)
            y2 = int((cy + h // 2) * scale_y)
            if x2 <= x1 or y2 <= y1:
                continue
            color = CLASS_COLORS[cls_id % len(CLASS_COLORS)]
            pen = ctypes.windll.gdi32.CreatePen(0, 2, color)
            ctypes.windll.gdi32.SelectObject(mem_dc, pen)
            null_brush = ctypes.windll.gdi32.GetStockObject(5)
            ctypes.windll.gdi32.SelectObject(mem_dc, null_brush)
            ctypes.windll.gdi32.Rectangle(mem_dc, x1, y1, x2, y2)
            ctypes.windll.gdi32.DeleteObject(pen)

        ctypes.windll.gdi32.BitBlt(hdc, 0, 0, self._width, self._height,
                                   mem_dc, 0, 0, 0x00CC0020)
        ctypes.windll.gdi32.SelectObject(mem_dc, old_bmp)
        ctypes.windll.gdi32.DeleteObject(bmp)
        ctypes.windll.gdi32.DeleteDC(mem_dc)
        ctypes.windll.user32.ReleaseDC(self._hwnd, hdc)

    def hide(self):
        if self._hwnd:
            ctypes.windll.user32.ShowWindow(self._hwnd, 0)

    def destroy(self):
        if self._hwnd:
            ctypes.windll.user32.DestroyWindow(self._hwnd)
            self._hwnd = None


_overlay = OverlayWindow()
atexit.register(_overlay.destroy)


def main():
    sys.path.insert(0, _BASE)
    from core.window import find_window_by_keyword, get_client_rect_on_screen
    from core.capture import capture_window_bgr
    from ultralytics import YOLO

    if not os.path.exists(_MODEL_PATH):
        print(f"[错误] 模型未找到: {_MODEL_PATH}")
        sys.exit(1)

    hwnd = find_window_by_keyword("洛克王国：世界")
    if hwnd is None:
        print("[错误] 未找到游戏窗口")
        sys.exit(1)

    print(f"[geli检测] 加载模型: {_MODEL_PATH}")
    model = YOLO(_MODEL_PATH)
    print(f"[geli检测] 类别: {_CLASS_NAMES}")
    print(f"[geli检测] 开始实时检测 (0.2s/帧)，按 Q 退出...")

    try:
        while True:
            if win32gui.GetForegroundWindow() != hwnd:
                _overlay.hide()
                time.sleep(0.2)
                continue

            t0 = time.perf_counter()
            frame = capture_window_bgr(hwnd)
            if frame is None or frame.size == 0:
                time.sleep(0.2)
                continue

            results = model(frame, verbose=False, conf=0.1)
            detections = []
            for r in results:
                if r.boxes is None:
                    continue
                for box in r.boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    conf = float(box.conf[0])
                    cls_id = int(box.cls[0])
                    cx = int((x1 + x2) / 2)
                    cy = int((y1 + y2) / 2)
                    w = int(x2 - x1)
                    h = int(y2 - y1)
                    if w > 0 and h > 0:
                        detections.append((cls_id, cx, cy, w, h, conf))

            if detections:
                fh, fw = frame.shape[:2]
                rect = get_client_rect_on_screen(hwnd)
                _overlay.ensure(hwnd, *rect)
                _overlay.update(detections, fw, fh)
                counts = {}
                for d in detections:
                    name = _CLASS_NAMES[d[0]]
                    counts[name] = counts.get(name, 0) + 1
                elapsed = (time.perf_counter() - t0) * 1000
                ts = datetime.now().strftime("%H:%M:%S")
                parts = ", ".join(f"{k}:{v}" for k, v in counts.items())
                status_line = f"\r[{ts}] {parts} | {elapsed:.0f}ms   "
            else:
                status_line = f"\r[{datetime.now().strftime('%H:%M:%S')}] 未检测到目标    "
                _overlay.hide()

            print(status_line, end="", flush=True)

            elapsed = time.perf_counter() - t0
            sleep_t = max(0, 0.2 - elapsed)
            if sleep_t > 0:
                time.sleep(sleep_t)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except KeyboardInterrupt:
        pass
    finally:
        _overlay.destroy()
        cv2.destroyAllWindows()
        print("\n[geli检测] 已停止")


if __name__ == "__main__":
    main()
