"""
全屏截图上拖拽框选小地图区域（与 mss 坐标一致）。
启动流程：倒计时 PICK_SCREEN_COUNTDOWN_SEC → 框选 → 启动跟点。
"""

from __future__ import annotations

import argparse
import ctypes
import sys
from collections.abc import Callable

import cv2
import numpy as np
import tkinter as tk
from tkinter import messagebox

try:
    from PIL import Image, ImageTk
except ImportError as e:
    raise SystemExit("请安装 Pillow: pip install pillow") from e

MIN_REGION = 32
PICK_OVERLAY_MAX_EDGE = 2400


def _win32_set_per_monitor_dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError, ctypes.ArgumentError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def pick_screen_region(
    parent: tk.Tk,
    on_done: Callable[[int, int, int, int], None],
    on_cancel: Callable[[], None] | None = None,
) -> None:
    try:
        import mss
    except ImportError:
        messagebox.showerror("缺少依赖", "框选需要: pip install mss")
        if on_cancel is not None:
            parent.after(0, on_cancel)
        return

    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = np.array(sct.grab(mon))
    bgr = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
    raw_h, raw_w = bgr.shape[:2]
    ml, mt = int(mon["left"]), int(mon["top"])

    scale = min(1.0, PICK_OVERLAY_MAX_EDGE / max(raw_w, raw_h, 1))
    disp_w = max(1, int(round(raw_w * scale)))
    disp_h = max(1, int(round(raw_h * scale)))
    if scale < 1.0:
        bgr = cv2.resize(bgr, (disp_w, disp_h), interpolation=cv2.INTER_AREA)
    else:
        disp_w, disp_h = raw_w, raw_h
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    photo = ImageTk.PhotoImage(pil_img)

    overlay = tk.Toplevel(parent)
    overlay.title("")
    overlay.overrideredirect(True)
    overlay.configure(cursor="crosshair", bg="#1a1a1a")
    overlay.attributes("-topmost", True)
    overlay.geometry(f"{disp_w}x{disp_h}+{ml}+{mt}")

    canvas = tk.Canvas(
        overlay,
        width=disp_w,
        height=disp_h,
        highlightthickness=0,
        bg="#1a1a1a",
    )
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_image(0, 0, anchor=tk.NW, image=photo)
    bar_h = 44
    canvas.create_rectangle(0, 0, disp_w, bar_h, fill="#2d2d2d", outline="", width=0)
    canvas.create_text(
        disp_w // 2,
        bar_h // 2,
        text="拖拽框选「游戏小地图」| 松开完成  Esc 取消",
        fill="white",
        font=("Microsoft YaHei UI", 12),
    )

    overlay._pick_photo_ref = photo  # type: ignore[attr-defined]

    box: dict[str, float | None] = {"cx0": None, "cy0": None}
    rect_id: int | None = None

    def _notify_cancel() -> None:
        if on_cancel is not None:
            parent.after(0, on_cancel)

    def _ungrab_and_destroy(*, cancelled: bool = False) -> None:
        try:
            overlay.destroy()
        except tk.TclError:
            pass
        if cancelled:
            _notify_cancel()

    def press(e: tk.Event) -> None:
        box["cx0"], box["cy0"] = float(e.x), float(e.y)
        nonlocal rect_id
        if rect_id is not None:
            canvas.delete(rect_id)
            rect_id = None

    def motion(e: tk.Event) -> None:
        if box["cx0"] is None:
            return
        cx0, cy0 = box["cx0"], box["cy0"]
        cx1, cy1 = float(e.x), float(e.y)
        left, top = min(cx0, cx1), min(cy0, cy1)
        right, bot = max(cx0, cx1), max(cy0, cy1)
        nonlocal rect_id
        if rect_id is None:
            rect_id = canvas.create_rectangle(
                left, top, right, bot, outline="#ff3333", width=3
            )
        else:
            canvas.coords(rect_id, left, top, right, bot)

    def release(e: tk.Event) -> None:
        if box["cx0"] is None:
            _ungrab_and_destroy(cancelled=True)
            return
        cx0, cy0 = box["cx0"], box["cy0"]
        cx1, cy1 = float(e.x), float(e.y)
        left_c = min(cx0, cx1)
        right_c = max(cx0, cx1)
        top_c = min(cy0, cy1)
        bottom_c = max(cy0, cy1)
        left_c = max(0.0, min(left_c, float(disp_w)))
        right_c = max(0.0, min(right_c, float(disp_w)))
        top_c = max(0.0, min(top_c, float(disp_h)))
        bottom_c = max(0.0, min(bottom_c, float(disp_h)))
        w_c = right_c - left_c
        h_c = bottom_c - top_c
        left_s = ml + int(round(left_c * raw_w / disp_w))
        top_s = mt + int(round(top_c * raw_h / disp_h))
        w_s = max(1, int(round(w_c * raw_w / disp_w)))
        h_s = max(1, int(round(h_c * raw_h / disp_h)))
        _ungrab_and_destroy(cancelled=False)
        if w_s < MIN_REGION or h_s < MIN_REGION:
            messagebox.showwarning("区域过小", f"请框选至少 {MIN_REGION}x{MIN_REGION} 像素")
            if on_cancel is not None:
                parent.after(0, on_cancel)
            return
        on_done(left_s, top_s, w_s, h_s)

    canvas.bind("<ButtonPress-1>", press)
    canvas.bind("<B1-Motion>", motion)
    canvas.bind("<ButtonRelease-1>", release)
    overlay.bind("<Escape>", lambda e: _ungrab_and_destroy(cancelled=True))

    overlay.update_idletasks()
    overlay.deiconify()
    overlay.lift()
    try:
        overlay.focus_force()
    except tk.TclError:
        pass


def parse_launch_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="大地图跟点")
    ap.add_argument(
        "--no-pick",
        action="store_true",
        help="不倒计时、不框选，直接使用 config.MINIMAP",
    )
    return ap.parse_args()


def run_with_screen_pick(app_class: type, *, title_hint: str) -> None:
    """先倒计时再框选小地图，然后启动 app_class(root, minimap_region=...)."""
    import config

    args = parse_launch_args()

    def _show_loading(parent: tk.Tk, text: str) -> tk.Toplevel:
        win = tk.Toplevel(parent)
        win.title("正在启动")
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.geometry("420x120+80+80")
        lbl = tk.Label(
            win,
            text=text,
            justify=tk.CENTER,
            font=("Microsoft YaHei UI", 10),
            padx=16,
            pady=16,
        )
        lbl.pack(fill=tk.BOTH, expand=True)
        tip = tk.Label(
            win,
            text="首次运行若需重建大地图锚点，可能需要等待较长时间。",
            justify=tk.CENTER,
            font=("Microsoft YaHei UI", 9),
            padx=8,
            pady=0,
        )
        tip.pack(fill=tk.X)
        win.update_idletasks()
        win.deiconify()
        win.lift()
        return win

    def _start_app(root: tk.Tk, minimap_region) -> None:
        loading = _show_loading(root, "正在加载地图、锚点和悬浮窗，请稍候...")
        root.update_idletasks()
        try:
            root.title(title_hint)
            root._tracker_app = app_class(root, minimap_region=minimap_region)  # type: ignore[attr-defined]
        except BaseException as exc:
            try:
                loading.destroy()
            except tk.TclError:
                pass
            messagebox.showerror(
                "启动失败",
                f"程序启动失败：\n{exc}",
            )
            try:
                root.destroy()
            except tk.TclError:
                pass
            raise SystemExit(1) from exc
        try:
            loading.destroy()
        except tk.TclError:
            pass
        root.deiconify()
        root.lift()

    if args.no_pick:
        _win32_set_per_monitor_dpi_aware()
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        _start_app(root, minimap_region=None)
        root.mainloop()
        return

    _win32_set_per_monitor_dpi_aware()
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    def on_done(left: int, top: int, w: int, h: int) -> None:
        mreg = {"top": top, "left": left, "width": w, "height": h}
        _start_app(root, minimap_region=mreg)

    def on_cancel() -> None:
        try:
            root.destroy()
        except tk.TclError:
            pass
        sys.exit(0)

    def start_pick() -> None:
        pick_screen_region(root, on_done, on_cancel)

    sec = int(getattr(config, "PICK_SCREEN_COUNTDOWN_SEC", 5))
    if sec <= 0:
        start_pick()
    else:
        _countdown_before_pick(root, sec, start_pick, on_cancel)

    root.mainloop()


def _countdown_before_pick(
    parent: tk.Tk,
    seconds: int,
    on_then: Callable[[], None],
    on_cancel: Callable[[], None] | None,
) -> None:
    try:
        import mss
    except ImportError:
        on_then()
        return

    with mss.mss() as sct:
        mon = sct.monitors[1]
    ml, mt = int(mon["left"]), int(mon["top"])
    mw, mh = int(mon["width"]), int(mon["height"])
    win_w, win_h = 480, 150
    x = ml + max(0, mw - win_w - 20)
    y = mt + max(0, mh - win_h - 24)

    win = tk.Toplevel(parent)
    win.title("准备框选")
    win.attributes("-topmost", True)
    win.resizable(False, False)
    win.geometry(f"{win_w}x{win_h}+{x}+{y}")

    tmpl = (
        "请在此时间内切换到游戏窗口（Alt+Tab）\n"
        "结束后将截取屏幕并拖拽框选小地图。\n\n"
        "剩余 {n} 秒…"
    )
    lbl = tk.Label(
        win,
        text=tmpl.format(n=seconds),
        justify=tk.CENTER,
        font=("Microsoft YaHei UI", 10),
        padx=12,
        pady=10,
    )
    lbl.pack(fill=tk.BOTH, expand=True)

    remaining = seconds

    def _cancel(_evt: tk.Event | None = None) -> None:
        try:
            win.destroy()
        except tk.TclError:
            pass
        if on_cancel is not None:
            on_cancel()

    def _tick() -> None:
        nonlocal remaining
        remaining -= 1
        if remaining <= 0:
            try:
                win.destroy()
            except tk.TclError:
                pass
            on_then()
            return
        lbl.config(text=tmpl.format(n=remaining))
        parent.after(1000, _tick)

    win.bind("<Escape>", _cancel)
    win.protocol("WM_DELETE_WINDOW", lambda: _cancel(None))

    parent.after(1000, _tick)
    win.update_idletasks()
    win.deiconify()
    win.lift()
    try:
        win.focus_force()
    except tk.TclError:
        pass
