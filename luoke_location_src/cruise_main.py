"""巡航 + 自动抓宠 主入口。

在 SIFT 追踪悬浮窗基础上增加：
- 鼠标拖拽框选巡航区域
- 自动 Z 字形路径巡航
- 到达路径点后 360° 扫描抓宠

用法：python cruise_main.py
"""
from __future__ import annotations

import ctypes
import math
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

import keyboard
import win32api
import win32con
import win32gui

# ── 将父目录（项目根）加到 sys.path ─────────────────────────────
# 注意：用 append 而非 insert(0)，确保当前目录（luoke_location_src）的
# config.py 优先于项目根的同名模块。
_HERE = os.path.dirname(os.path.abspath(__file__))
_AUTO_ROCO = os.path.normpath(os.path.join(_HERE, ".."))
if os.path.isdir(_AUTO_ROCO) and _AUTO_ROCO not in sys.path:
    sys.path.append(_AUTO_ROCO)

_CRUISE_CAPTURE = os.path.join(_AUTO_ROCO, "cruise_capture")
if os.path.isdir(_CRUISE_CAPTURE) and _CRUISE_CAPTURE not in sys.path:
    sys.path.append(_CRUISE_CAPTURE)

# 主进程通过此标志文件通知巡航子进程暂停（战斗时）
_PAUSE_FLAG = os.path.join(_HERE, "out", "cruise_pause.flag")


def _load_pet_detector():
    """加载宠物检测器。

    需要临时将项目根目录放到 sys.path 最前面，
    因为 core.pet_detector 依赖项目根的 config.CONFIG，
    而当前目录的 config.py (SIFT) 会将其覆盖。
    """
    _auto = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
    ))
    saved_config = sys.modules.get("config")
    if _auto in sys.path:
        sys.path.remove(_auto)
    sys.path.insert(0, _auto)
    if "config" in sys.modules:
        del sys.modules["config"]
    try:
        from config import CONFIG
        _model = globals().get("_CRUISE_PET_MODEL", "xueren")
        CONFIG.pet_model_name = _model
        from core.pet_detector import PetDetector
        import core.window   # noqa: F401 — _screen_rect 需要
        import core.capture  # noqa: F401 — _scan_for_pets 需要
        import core.input    # noqa: F401 — _ensure_interception / click_at 需要
        detector = PetDetector()
        detector.preload()
        return detector
    except Exception as e:
        print(f"[Cruise] 加载宠物检测器失败: {e}")
        return None
    finally:
        if sys.path[0] == _auto:
            sys.path.pop(0)
        if _auto not in sys.path:
            sys.path.append(_auto)
        if saved_config is not None:
            sys.modules["config"] = saved_config

import cv2
import numpy as np
from PIL import Image, ImageTk

import config

# ── 性能优化 ─────────────────────────────────────────────────────
config.SIFT_REFRESH_RATE = 50        # 20fps，匹配实际帧耗时

from main_sift import SiftMapTrackerApp
from screen_pick import run_with_screen_pick


class CruiseTrackerApp(SiftMapTrackerApp):
    """扩展 SIFT 追踪器：加入巡航区域框选 + 自动巡航 + 抓宠。"""

    def __init__(self, root: tk.Tk, minimap_region=None):
        # ── 先调用父类初始化（加载地图、SIFT 特征、启动追踪）────
        super().__init__(root, minimap_region)

        # ── 窗口定位：紧贴小地图正下方 ────────────────────────────
        self.root.title("SIFT 巡航 + 自动抓宠")
        geo = config.WINDOW_GEOMETRY  # 格式 "WxH+X+Y"，取宽高
        parts = geo.replace("x", "+").split("+")
        ww = int(parts[0])
        wh = int(parts[1]) + 40  # 加高容纳控制栏
        # 根据小地图区域计算位置
        mr = self.minimap_region if self.minimap_region else config.MINIMAP
        mm_left = mr["left"]
        mm_top = mr["top"]
        mm_height = mr.get("height", 150)
        mm_width = mr.get("width", 150)
        wx = max(0, mm_left - ww - 10)  # 小地图左侧，留 10px 间隙
        wy = mm_top + mm_height         # 紧贴小地图下沿
        self.root.geometry(f"{ww}x{wh}+{wx}+{wy}")

        # ── 抓宠相关（从模式3 ball_pet.py 原样复制）──────────────
        self._sensitivity_ratio_h: float = 1.0
        self._sensitivity_ratio_v: float = 1.0
        self._last_throw_time: float = 0.0
        self._last_detect_time: float = 0.0
        self._last_rotate_time: float = 0.0
        self._aiming: bool = False
        self._last_periodic_scan_time: float = 0.0  # 周期性宠物扫描计时
        self._cruise_mode = False
        self._cruise_controller = None     # 延迟导入
        self._pet_detector = None
        self._game_hwnd = None
        self._cruise_area_rect = None      # 框选矩形 (x1,y1,x2,y2) 地图坐标
        self._cruise_tick_ms = 100         # 巡航主循环间隔
        self._f9_triggered = False         # F9 热键标志（由 keyboard 钩子设置）

        # ── 框选状态 ──────────────────────────────────────────────
        self._selecting = False
        self._sel_start_x = 0
        self._sel_start_y = 0
        self._sel_rect_id = None
        self._area_rect_ids: list[int] = []

        # ── 巡航 UI ────────────────────────────────────────────────
        self._setup_cruise_ui()

        # ── 延迟初始化游戏窗口和抓宠检测器 ─────────────────────────
        self.root.after(2000, self._init_game_components)

    # ── UI 设置 ───────────────────────────────────────────────────

    def _setup_cruise_ui(self):
        """在悬浮窗底部添加巡航控制面板。"""
        control_frame = tk.Frame(self.root, bg="#2b2b2b")
        control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=2)

        self._btn_select = tk.Button(
            control_frame,
            text="框选巡航区域",
            command=self._start_area_select,
            bg="#3a3a3a", fg="#ddd",
            font=("Microsoft YaHei UI", 9),
            relief=tk.FLAT, padx=8, pady=2,
        )
        self._btn_select.pack(side=tk.LEFT, padx=2)

        self._btn_clear = tk.Button(
            control_frame,
            text="清除区域",
            command=self._clear_cruise_area,
            bg="#3a3a3a", fg="#ddd",
            font=("Microsoft YaHei UI", 9),
            relief=tk.FLAT, padx=8, pady=2,
        )
        self._btn_clear.pack(side=tk.LEFT, padx=2)

        self._btn_start = tk.Button(
            control_frame,
            text="开始巡航",
            command=self._toggle_cruise,
            bg="#2d6b2d", fg="#ddd",
            font=("Microsoft YaHei UI", 9, "bold"),
            relief=tk.FLAT, padx=12, pady=2,
        )
        self._btn_start.pack(side=tk.LEFT, padx=4)

        self._btn_repick = tk.Button(
            control_frame,
            text="重选小地图",
            command=self._repick_minimap,
            bg="#3a3a3a", fg="#ddd",
            font=("Microsoft YaHei UI", 9),
            relief=tk.FLAT, padx=8, pady=2,
        )
        self._btn_repick.pack(side=tk.LEFT, padx=2)

        self._status_label = tk.Label(
            control_frame,
            text="就绪",
            bg="#2b2b2b", fg="#aaa",
            font=("Microsoft YaHei UI", 8),
        )
        self._status_label.pack(side=tk.RIGHT, padx=4)

        # 鼠标事件绑定到 canvas
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press, add="+")
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag, add="+")
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release, add="+")

    # ── 游戏组件延迟初始化 ────────────────────────────────────────

    def _init_game_components(self):
        """延迟初始化游戏窗口句柄和宠物检测器。"""
        if self._game_hwnd is None:
            if not self._try_find_window():
                print("[Cruise] 未找到游戏窗口，10秒后重试...")
                self.root.after(10000, self._init_game_components)
                return

        if self._pet_detector is None:
            self._pet_detector = _load_pet_detector()
            if self._pet_detector is not None:
                self._load_sensitivity_ratio()
                print("[Cruise] 宠物检测器已就绪，灵敏度已加载")

    # ── 巡航区域框选 ──────────────────────────────────────────────

    def _start_area_select(self):
        """进入框选模式。"""
        if self._cruise_mode:
            messagebox.showwarning("提示", "请先停止巡航再框选区域")
            return
        self._selecting = True
        self._clear_area_visuals()
        self.canvas.configure(cursor="crosshair")
        self._btn_select.configure(bg="#555")
        self._status_label.configure(text="在地图上拖拽框选巡航范围...")

    def _clear_area_visuals(self):
        """清除画布上的区域矩形和路径线。"""
        for rid in self._area_rect_ids:
            self.canvas.delete(rid)
        self._area_rect_ids.clear()
        if self._sel_rect_id:
            self.canvas.delete(self._sel_rect_id)
            self._sel_rect_id = None

    def _clear_cruise_area(self):
        """清除巡航区域。"""
        if self._cruise_mode:
            messagebox.showwarning("提示", "请先停止巡航再清除区域")
            return
        self._cruise_area_rect = None
        self._clear_area_visuals()
        self._status_label.configure(text="区域已清除")

    def _canvas_to_map(self, cx: float, cy: float) -> tuple[int, int]:
        """将画布坐标转换为大地图坐标。"""
        vs = int(config.VIEW_SIZE)
        half = int(getattr(config, "VIEW_MAP_HALF_SIZE", vs // 2))
        half = max(half, vs // 2)

        # 从当前显示视口计算裁剪区域
        if self.last_x is not None and self.last_y is not None:
            center_x, center_y = float(self.last_x), float(self.last_y)
        else:
            center_x = float(self.map_width) / 2.0
            center_y = float(self.map_height) / 2.0

        cx_i = int(round(center_x))
        cy_i = int(round(center_y))
        y1 = max(0, cy_i - half)
        y2 = min(self.map_height, cy_i + half)
        x1 = max(0, cx_i - half)
        x2 = min(self.map_width, cx_i + half)

        ch = max(1, y2 - y1)
        cw = max(1, x2 - x1)

        map_x = int(x1 + cx * cw / vs)
        map_y = int(y1 + cy * ch / vs)
        return map_x, map_y

    def _on_canvas_press(self, event: tk.Event):
        if not self._selecting:
            return
        self._sel_start_x = event.x
        self._sel_start_y = event.y
        if self._sel_rect_id:
            self.canvas.delete(self._sel_rect_id)
        self._sel_rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="#ff0", width=2,
        )

    def _on_canvas_drag(self, event: tk.Event):
        if not self._selecting or self._sel_rect_id is None:
            return
        self.canvas.coords(
            self._sel_rect_id,
            self._sel_start_x, self._sel_start_y,
            event.x, event.y,
        )

    def _on_canvas_release(self, event: tk.Event):
        if not self._selecting:
            return
        self._selecting = False
        self.canvas.configure(cursor="")
        self._btn_select.configure(bg="#3a3a3a")

        if self._sel_rect_id:
            self.canvas.delete(self._sel_rect_id)
            self._sel_rect_id = None

        x1_c, y1_c = self._sel_start_x, self._sel_start_y
        x2_c, y2_c = event.x, event.y
        if x1_c > x2_c:
            x1_c, x2_c = x2_c, x1_c
        if y1_c > y2_c:
            y1_c, y2_c = y2_c, y1_c

        if abs(x2_c - x1_c) < 10 or abs(y2_c - y1_c) < 10:
            self._status_label.configure(text="框选区域太小，请重新拖拽")
            return

        mx1, my1 = self._canvas_to_map(x1_c, y1_c)
        mx2, my2 = self._canvas_to_map(x2_c, y2_c)
        self._cruise_area_rect = (mx1, my1, mx2, my2)

        # 在地图上绘制区域框
        self._draw_cruise_area_overlay()
        self._status_label.configure(
            text=f"巡航区域: ({mx1},{my1}) → ({mx2},{my2})"
        )

    def _draw_cruise_area_overlay(self):
        """在当前显示画面上叠加绘制巡航区域和路径预览。"""
        # 这里不直接修改 canvas（因为 display 会每帧更新），
        # 而是修改 _compose_display_view 来叠加绘制。
        # 保存区域坐标，在 _overlay_cruise_on_display 中使用。
        pass

    # ── 显示 overlay ──────────────────────────────────────────────

    def _apply_tracker_ui(self, display_bgr: np.ndarray) -> None:
        """重写父类方法，叠加巡航区域和路径。"""
        try:
            display_bgr = self._overlay_cruise_on_display(display_bgr)
        except Exception as e:
            print(f"[Cruise] 叠加巡航图层异常: {e}")
        super()._apply_tracker_ui(display_bgr)

    def _overlay_cruise_on_display(self, display_bgr: np.ndarray) -> np.ndarray:
        """在 display_bgr 上叠加巡航区域矩形和路径线。"""
        if self._cruise_area_rect is None:
            return display_bgr

        vs = int(config.VIEW_SIZE)
        half = int(getattr(config, "VIEW_MAP_HALF_SIZE", vs // 2))
        half = max(half, vs // 2)

        # 当前视口信息
        if self.last_x is not None and self.last_y is not None:
            center_x, center_y = float(self.last_x), float(self.last_y)
        else:
            return display_bgr

        cx_i = int(round(center_x))
        cy_i = int(round(center_y))
        y1 = max(0, cy_i - half)
        y2 = min(self.map_height, cy_i + half)
        x1 = max(0, cx_i - half)
        x2 = min(self.map_width, cx_i + half)
        ch = max(1, y2 - y1)
        cw = max(1, x2 - x1)

        def map_to_display(mx: int, my: int) -> tuple[int, int]:
            dx = int((mx - x1) * vs / cw)
            dy = int((my - y1) * vs / ch)
            return dx, dy

        # 绘制巡航区域矩形
        ax1, ay1 = self._cruise_area_rect[:2]
        ax2, ay2 = self._cruise_area_rect[2:]
        d1 = map_to_display(ax1, ay1)
        d2 = map_to_display(ax2, ay2)
        cv2.rectangle(display_bgr, d1, d2, (0, 255, 255), 2)

        # 绘制路径预览
        if self._cruise_controller is not None and self._cruise_controller.waypoints:
            pts = self._cruise_controller.waypoints
            for i in range(len(pts) - 1):
                p1 = map_to_display(pts[i][0], pts[i][1])
                p2 = map_to_display(pts[i + 1][0], pts[i + 1][1])
                cv2.line(display_bgr, p1, p2, (0, 200, 200), 1, cv2.LINE_AA)

            # 当前目标点高亮
            target = self._cruise_controller.current_target()
            if target is not None:
                tp = map_to_display(target[0], target[1])
                cv2.circle(display_bgr, tp, 8, (0, 255, 255), -1)

        return display_bgr

    # ── 巡航控制 ──────────────────────────────────────────────────

    def _toggle_cruise(self):
        """开始/停止巡航。"""
        if self._cruise_mode:
            self._stop_cruise()
            return

        if self._cruise_area_rect is None:
            messagebox.showwarning("提示", "请先框选巡航区域")
            return

        if self._game_hwnd is None:
            # 主动重试查找
            self._status_label.configure(text="正在查找游戏窗口...")
            self._init_game_components()
            self.root.after(500, self._check_hwnd_and_start)
            return

        self._start_cruise()

    def _try_find_window(self) -> bool:
        """快速查找游戏窗口（不加载模型）。
        使用 win32gui 直接枚举窗口，避免 core.window 导入时的 config 冲突。
        """
        matches: list[tuple[int, str]] = []
        keywords = ["洛克王国", "洛克", "王国", "ROCO", "Roco"]

        def _enum_handler(hwnd: int, _ctx) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            if win32gui.IsIconic(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            if title:
                for kw in keywords:
                    if kw in title:
                        matches.append((hwnd, title))
                        return

        try:
            win32gui.EnumWindows(_enum_handler, None)
        except Exception as e:
            print(f"[Cruise] 枚举窗口失败: {e}")
            return False

        if not matches:
            print(f"[Cruise] 未找到匹配窗口，搜索关键词: {keywords}")
            return False

        # 标题最短的最可能是主窗口
        best_hwnd, best_title = min(matches, key=lambda m: len(m[1]))
        self._game_hwnd = best_hwnd
        print(f"[Cruise] 找到游戏窗口: hwnd={best_hwnd} title=\"{best_title}\"")
        return True

    def _check_hwnd_and_start(self):
        if self._game_hwnd is not None:
            self._start_cruise()
        else:
            # 再试一次
            if self._try_find_window():
                self._start_cruise()
            else:
                messagebox.showwarning("提示", "未找到游戏窗口，请确保洛克王国已启动")
                self._status_label.configure(text="就绪")

    def _repick_minimap(self):
        """删除已保存的小地图区域，下次启动重新框选。"""
        if self._cruise_mode:
            messagebox.showwarning("提示", "请先停止巡航")
            return
        if not messagebox.askyesno(
            "重选小地图",
            "将删除已保存的小地图区域，\n下次启动程序时将重新框选。\n\n确定要继续吗？"
        ):
            return
        try:
            if os.path.exists(_MINIMAP_SAVE_PATH):
                os.remove(_MINIMAP_SAVE_PATH)
                self._status_label.configure(text="小地图区域已清除，请重启程序")
            else:
                self._status_label.configure(text="没有已保存的区域，无需清除")
        except Exception as e:
            messagebox.showerror("错误", f"删除失败: {e}")

    def _focus_game_window(self):
        """点击游戏窗口中心，确保游戏在前台再开始巡航。"""
        if self._game_hwnd is None:
            return
        try:
            rect = win32gui.GetWindowRect(self._game_hwnd)
            cx = (rect[0] + rect[2]) // 2
            cy = (rect[1] + rect[3]) // 2

            # 将游戏窗口带到前台
            win32gui.SetForegroundWindow(self._game_hwnd)
            time.sleep(0.15)
            # 在窗口中心模拟左键点击
            win32api.SetCursorPos((cx, cy))
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.1)
            print("[Cruise] 已点击游戏窗口中心")
        except Exception as e:
            print(f"[Cruise] 聚焦游戏窗口失败: {e}")

    def _start_cruise(self):
        """启动巡航。"""
        # 先聚焦游戏窗口
        self._focus_game_window()

        # 注册 F9 全局热键（keyboard 库，Windows 底层钩子）
        self._start_f9_monitor()

        # 悬浮窗设为鼠标穿透，避免 interception 旋转时鼠标点到悬浮窗
        self._set_window_click_through(True)

        from cruise_controller import CruiseController, CruiseArea

        ax1, ay1, ax2, ay2 = self._cruise_area_rect
        area = CruiseArea(x1=ax1, y1=ay1, x2=ax2, y2=ay2)
        spacing = 150  # 路径点间距

        self._cruise_controller = CruiseController(self._game_hwnd)
        self._cruise_controller.set_cruise_area(area, spacing)
        self._cruise_mode = True

        self._btn_start.configure(text="停止巡航 (F9)", bg="#8b2d2d")
        self._btn_select.configure(state=tk.DISABLED)
        self._status_label.configure(text="巡航中...")

        print("[Cruise] 巡航已启动")
        self.root.after(self._cruise_tick_ms, self._cruise_loop)

    def _start_f9_monitor(self):
        """通过 keyboard 库注册全局 F9 热键（底层 Windows 钩子，不受 sleep 影响）。"""
        self._f9_triggered = False
        try:
            keyboard.add_hotkey('f9', self._on_f9_hotkey)
            print("[Cruise] F9 热键已注册")
        except Exception as e:
            print(f"[Cruise] F9 热键注册失败: {e}")

    def _on_f9_hotkey(self):
        """F9 热键回调（由 keyboard 钩子线程调用）。"""
        self._f9_triggered = True

    def _stop_f9_monitor(self):
        """注销 F9 热键。"""
        try:
            keyboard.remove_hotkey('f9')
        except Exception:
            pass

    def _set_window_click_through(self, enable: bool):
        """通过 ctypes 直接调 Win32 API 设置鼠标穿透。"""
        hwnd = self.root.winfo_id()
        if not hwnd:
            return

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
        LWA_ALPHA = 0x2

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if enable:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
            print("[Cruise] 悬浮窗鼠标穿透已启用")
        else:
            style &= ~(WS_EX_LAYERED | WS_EX_TRANSPARENT)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)

    def _stop_cruise(self):
        """停止巡航。"""
        self._cruise_mode = False

        # 停止 F9 后台监测线程
        self._stop_f9_monitor()

        if self._cruise_controller:
            self._cruise_controller._release_all()
            try:
                from cruise_controller import CruiseState
                self._cruise_controller.state = CruiseState.IDLE
            except ImportError:
                pass

        # 恢复悬浮窗可点击
        self._set_window_click_through(False)

        self._btn_start.configure(text="开始巡航", bg="#2d6b2d")
        self._btn_select.configure(state=tk.NORMAL)
        self._status_label.configure(text="巡航已停止 (F9)")
        print("[Cruise] 巡航已停止")

    def _cruise_loop(self):
        """巡航主循环（通过 root.after 调度）。"""
        if not self._cruise_mode or self._cruise_controller is None:
            return

        # 检查 F9 热键标志（由 keyboard 钩子设置）
        if self._f9_triggered:
            self._f9_triggered = False
            print("[Cruise] F9 热键触发 —— 停止巡航")
            self._stop_cruise()
            return

        # 检查主进程发来的暂停标志（战斗逃跑期间暂停移动）
        if os.path.exists(_PAUSE_FLAG):
            if self._cruise_controller is not None:
                self._cruise_controller._release_all()
            self._status_label.configure(text="PAUSED (主进程战斗中)")
            self.root.after(self._cruise_tick_ms, self._cruise_loop)
            return

        try:
            ctrl = self._cruise_controller

            # 更新位置
            if self.last_x is not None and self.last_y is not None:
                ctrl.update_position(self.last_x, self.last_y)

            # 状态机 tick
            ctrl.tick()

            # 扫描状态下执行宠物检测
            if ctrl.state.name == "SCANNING":
                self._scan_for_pets()

            # 周期性宠物扫描（每2秒，独立于巡航状态）
            now = time.perf_counter()
            if now - self._last_periodic_scan_time > 2.0:
                self._last_periodic_scan_time = now
                if ctrl.state.name != "SCANNING":
                    was_moving = ctrl._w_down
                    if was_moving:
                        ctrl._release_forward()
                    try:
                        self._scan_for_pets()
                    finally:
                        if was_moving:
                            ctrl._start_forward()

            # 更新状态显示
            target = ctrl.current_target()
            if target is not None:
                wp_info = f"{ctrl.current_waypoint_idx + 1}/{len(ctrl.waypoints)}"
            else:
                wp_info = "完成" if ctrl.state.name == "IDLE" else "-"

            self._status_label.configure(
                text=f"{ctrl.state.name} | 路径点: {wp_info}"
            )
        except Exception as e:
            print(f"[Cruise] 循环异常: {e}")
            try:
                ctrl._release_all()
            except Exception:
                pass

        if self._cruise_mode:
            self.root.after(self._cruise_tick_ms, self._cruise_loop)

    # ── 扫描抓宠（从模式3 ball_pet.py 原样复制）────────────────────

    def _load_sensitivity_ratio(self) -> None:
        """优先从 user_prefs.json 加载已标定的横向/纵向灵敏度。（同模式3）"""
        import json
        _auto = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
        ))
        prefs_path = os.path.join(_auto, "user_prefs.json")
        try:
            if os.path.exists(prefs_path):
                with open(prefs_path, "r", encoding="utf-8") as f:
                    prefs = json.load(f)
                rh = prefs.get("pet_aim_pixels_per_unit_h", 0.0)
                rv = prefs.get("pet_aim_pixels_per_unit_v", 0.0)
                if rh > 0 and rv > 0:
                    self._sensitivity_ratio_h = rh
                    self._sensitivity_ratio_v = rv
                    print(f"[Cruise] 已加载标定灵敏度: h={rh:.4f} v={rv:.4f}")
                    return
                old = prefs.get("pet_aim_pixels_per_unit", 0.0)
                if old > 0:
                    self._sensitivity_ratio_h = old
                    self._sensitivity_ratio_v = old
                    print(f"[Cruise] 已加载旧版标定灵敏度: ratio={old:.4f}")
                    return
        except Exception:
            pass

    def _screen_rect(self, hwnd, fw, fh):
        """Return (left, top, width, height) of game client area on screen."""
        from core.window import get_client_rect_on_screen
        return get_client_rect_on_screen(hwnd)

    def _screen_size(self, hwnd: int) -> tuple:
        rect = self._screen_rect(hwnd, 0, 0)
        return rect[2], rect[3]

    def _aim_calibrated(self, hwnd: int, pet_cx: int, pet_cy: int,
                         pet_w: int, pet_h: int, conf: float,
                         detector) -> None:
        """MLP闭环瞄准（同模式3）：mouse = w1*px + w2*px*|px| + w3*px³。"""
        import json
        import interception
        from core.input import _ensure_interception
        from core.capture import capture_window_bgr

        _auto = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..",
        ))
        prefs_path = os.path.join(_auto, "user_prefs.json")
        nn_w = [1.0 / self._sensitivity_ratio_h, 0.0, 0.0]
        nn_w_v = [1.0 / self._sensitivity_ratio_v, 0.0, 0.0]
        try:
            if os.path.exists(prefs_path):
                with open(prefs_path, "r", encoding="utf-8") as f:
                    prefs = json.load(f)
                if "nn_weights_h" in prefs:
                    nn_w = prefs["nn_weights_h"]
                if "nn_weights_v" in prefs:
                    nn_w_v = prefs["nn_weights_v"]
        except Exception:
            pass

        screen_w, screen_h = self._screen_size(hwnd)
        cx, cy = screen_w // 2, screen_h // 2
        thresh = 20  # pet_aim_center_thresh
        settle = 0.06

        total_dx, total_dy = 0, 0

        _ensure_interception()
        interception.mouse_down('right')
        time.sleep(0.05)

        try:
            for attempt in range(3):
                h_px = float(pet_cx - cx)
                v_px = float(pet_cy - cy)

                if abs(h_px) < thresh and abs(v_px) < thresh:
                    break

                dx = int(nn_w[0] * h_px + nn_w[1] * h_px * abs(h_px) + nn_w[2] * h_px ** 3)
                dy = int(nn_w_v[0] * v_px + nn_w_v[1] * v_px * abs(v_px) + nn_w_v[2] * v_px ** 3)
                dx = max(-400, min(400, dx))
                dy = max(-400, min(400, dy))

                if abs(dx) < 2 and abs(dy) < 2:
                    break

                interception.move_relative(dx, dy)
                total_dx += dx
                total_dy += dy
                time.sleep(settle)

                frame = capture_window_bgr(hwnd)
                if frame is None or frame.size == 0:
                    break
                dets = detector.detect(frame)
                if not dets:
                    break
                pet_cx, pet_cy = dets[0][0], dets[0][1]

            pass  # 瞄准完成
        finally:
            interception.mouse_up('right')
            time.sleep(0.10)

    def _scan_for_pets(self):
        """扫描状态下执行精灵检测和抓取（同模式3 _detect_and_throw 管线）。"""
        if self._pet_detector is None:
            if not getattr(self, '_scan_warned_detector', False):
                print("[Cruise] 宠物检测器尚未就绪，等待初始化...")
                self._scan_warned_detector = True
            return False
        if self._game_hwnd is None:
            if not getattr(self, '_scan_warned_hwnd', False):
                print("[Cruise] 游戏窗口句柄未设置，无法截图")
                self._scan_warned_hwnd = True
            return False
        self._scan_warned_detector = False
        self._scan_warned_hwnd = False

        try:
            from core.capture import capture_window_bgr
            from core.input import _ensure_interception, click_at
        except ImportError as e:
            print(f"[Cruise] 抓宠模块导入失败: {e}")
            return False

        detector = self._pet_detector

        frame = capture_window_bgr(self._game_hwnd)
        if frame is None or frame.size == 0:
            print(f"[Cruise] 截图失败: hwnd={self._game_hwnd}, frame={'None' if frame is None else 'empty'}")
            return False

        try:
            detections = detector.detect(frame)
        except Exception as e:
            print(f"[Cruise] 精灵检测异常: {e}")
            return False

        if not detections:
            return False

        pet_cx, pet_cy, pet_w, pet_h, conf = detections[0]
        print(f"[Cruise] 检测到精灵: conf={conf:.2f} pos=({pet_cx},{pet_cy})")

        # 瞄准（同模式3：标定过用MLP闭环，否则用简单一步到位）
        ratio_h = self._sensitivity_ratio_h
        ratio_v = self._sensitivity_ratio_v
        if ratio_h != 1.0 or ratio_v != 1.0:
            self._aim_calibrated(self._game_hwnd, pet_cx, pet_cy, pet_w, pet_h, conf, detector)
        else:
            # 未标定：简单一步到位
            import interception
            from core.input import _ensure_interception
            _ensure_interception()
            fh, fw = frame.shape[:2]
            dx = int((pet_cx - fw // 2) / ratio_h)
            dy = int((pet_cy - fh // 2) / ratio_v)
            interception.mouse_down('right')
            time.sleep(0.05)
            interception.move_relative(dx, dy)
            time.sleep(0.10)
            interception.mouse_up('right')
            time.sleep(0.10)

        # 丢球（同模式3）
        if click_at(self._game_hwnd):
            self._last_throw_time = time.time()
            print(f"[Cruise] 丢球! conf={conf:.2f}")
        else:
            print(f"[Cruise] 丢球点击失败")

        return True


# ── 入口 ────────────────────────────────────────────────────────────

_MINIMAP_SAVE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "out", "minimap_region.json"
)


def _load_saved_region() -> dict | None:
    if not os.path.exists(_MINIMAP_SAVE_PATH):
        return None
    try:
        with open(_MINIMAP_SAVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in ("top", "left", "width", "height"):
            if k not in data or not isinstance(data[k], int) or data[k] <= 0:
                return None
        return data
    except Exception:
        return None


def _save_region(mreg: dict):
    try:
        os.makedirs(os.path.dirname(_MINIMAP_SAVE_PATH), exist_ok=True)
        with open(_MINIMAP_SAVE_PATH, "w", encoding="utf-8") as f:
            json.dump(mreg, f)
        print(f"[Cruise] 小地图区域已保存: {mreg}")
    except Exception as e:
        print(f"[Cruise] 保存小地图区域失败: {e}")


if __name__ == "__main__":
    import json

    # 解析 --pet-model 参数（由主进程传递），存入全局变量供 _load_pet_detector 使用
    for i, arg in enumerate(sys.argv):
        if arg == "--pet-model" and i + 1 < len(sys.argv):
            _CRUISE_PET_MODEL = sys.argv[i + 1]
            break
    else:
        _CRUISE_PET_MODEL = "xueren"
    print(f"[Cruise] 精灵模型: {_CRUISE_PET_MODEL}")

    # 检查是否有上次保存的小地图位置
    saved = _load_saved_region()

    if saved is not None:
        print(f"[Cruise] 检测到已保存的小地图区域: {saved}")
        # 直接使用保存的区域，跳过框选
        from screen_pick import _win32_set_per_monitor_dpi_aware
        _win32_set_per_monitor_dpi_aware()
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        root.title("SIFT 巡航 + 自动抓宠")

        app = CruiseTrackerApp(root, minimap_region=saved)
        # 保存以便下次使用
        root.after(1000, lambda: _save_region(app.minimap_region))
        root.deiconify()
        root.lift()
        root.mainloop()
    else:
        # 首次运行：正常框选，然后保存
        orig_on_done_ref = [None]

        # 用自定义逻辑包装 run_with_screen_pick
        import argparse
        import config as _config
        from screen_pick import (
            _win32_set_per_monitor_dpi_aware,
            pick_screen_region,
            _countdown_before_pick,
        )

        _win32_set_per_monitor_dpi_aware()
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        def _do_start(root, mreg):
            # 先保存到文件
            _save_region(mreg)
            # 显示加载中
            loading = tk.Toplevel(root)
            loading.title("")
            loading.attributes("-topmost", True)
            loading.geometry("420x120+80+80")
            lbl = tk.Label(loading, text="正在加载地图、锚点和悬浮窗，请稍候...",
                           justify=tk.CENTER, font=("Microsoft YaHei UI", 10), padx=16, pady=16)
            lbl.pack(fill=tk.BOTH, expand=True)
            loading.update_idletasks()
            loading.deiconify()
            loading.lift()

            root.update_idletasks()
            try:
                root.title("SIFT 巡航 + 自动抓宠")
                root._tracker_app = CruiseTrackerApp(root, minimap_region=mreg)
            except BaseException as exc:
                try:
                    loading.destroy()
                except tk.TclError:
                    pass
                messagebox.showerror("启动失败", f"程序启动失败：\n{exc}")
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

        def on_done(left, top, w, h):
            mreg = {"top": top, "left": left, "width": w, "height": h}
            _do_start(root, mreg)

        def on_cancel():
            try:
                root.destroy()
            except tk.TclError:
                pass
            sys.exit(0)

        sec = int(getattr(config, "PICK_SCREEN_COUNTDOWN_SEC", 5))
        if sec <= 0:
            pick_screen_region(root, on_done, on_cancel)
        else:
            _countdown_before_pick(root, sec, lambda: pick_screen_region(root, on_done, on_cancel), on_cancel)

        root.mainloop()
