"""
SIFT 跟点：仅在逻辑图有效掩膜内提特征；锚点可缓存。
大地图锚点数量由 SIFT_MAP_NFEATURES 控制：0 表示不限制（全量锚点，精度优先）。
有上一帧位置时仅在「空间邻域」内筛选锚点做 FLANN，不截断特征总数。
"""
from __future__ import annotations

import math
import os
import threading
import time
import cv2
import mss
import numpy as np
import tkinter as tk
from PIL import Image, ImageTk

import config

try:
    cv2.setUseOptimized(True)
except Exception:
    pass
from map_mask import (
    load_logic_bgr_and_region_mask,
    try_load_sift_anchors,
    save_sift_anchors,
)


def _downscale_gray_max_edge(gray: np.ndarray, max_edge: int) -> np.ndarray:
    if max_edge <= 0:
        return gray
    h, w = gray.shape[:2]
    m = max(h, w)
    if m <= max_edge:
        return gray
    s = max_edge / m
    nw, nh = int(round(w * s)), int(round(h * s))
    return cv2.resize(gray, (nw, nh), interpolation=cv2.INTER_AREA)


def _minimap_inscribed_ellipse_mask(h: int, w: int, axis_scale: float) -> np.ndarray:
    """与截屏矩形同尺寸，内接椭圆内为 255，四角为 0。方形截屏时为圆。"""
    mask = np.zeros((h, w), dtype=np.uint8)
    if h < 2 or w < 2:
        return mask
    sc = max(0.05, min(1.0, float(axis_scale)))
    cx = (w - 1) * 0.5
    cy = (h - 1) * 0.5
    ax = max(w * 0.5 * sc, 1.0)
    ay = max(h * 0.5 * sc, 1.0)
    cv2.ellipse(
        mask,
        (int(round(cx)), int(round(cy))),
        (int(round(ax)), int(round(ay))),
        0,
        0,
        360,
        255,
        -1,
    )
    return mask


def _peak_second_best(
    score_map: np.ndarray, best_loc: tuple[int, int], suppress_radius: int
) -> float:
    """抑制最佳峰附近后，再取次峰，判断模板匹配是否唯一。"""
    if score_map.size == 0:
        return 0.0
    x, y = int(best_loc[0]), int(best_loc[1])
    r = max(1, int(suppress_radius))
    y1 = max(0, y - r)
    y2 = min(score_map.shape[0], y + r + 1)
    x1 = max(0, x - r)
    x2 = min(score_map.shape[1], x + r + 1)
    score_copy = score_map.copy()
    score_copy[y1:y2, x1:x2] = -1.0
    return float(score_copy.max()) if score_copy.size > 0 else 0.0


def _normalize_angle_deg(angle_deg: float) -> float:
    """将角度归一到 [-180, 180) 便于做局部角度搜索。"""
    return ((float(angle_deg) + 180.0) % 360.0) - 180.0


def _build_template_feature_image(gray: np.ndarray) -> np.ndarray:
    """为模板匹配生成更偏轮廓/结构的图，降低纯色块与动态 UI 的干扰。"""
    blur_sigma = 1.2
    blur = cv2.GaussianBlur(gray, (0, 0), blur_sigma)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag_u8 = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    return cv2.addWeighted(gray, 0.35, mag_u8, 0.65, 0.0)


def _masked_stats_u8(
    gray: np.ndarray, mask: np.ndarray | None
) -> tuple[float, float, float]:
    """返回掩膜区域内的均值、标准差、亮像素占比。"""
    if mask is None:
        roi = gray.reshape(-1)
    else:
        roi = gray[mask > 0]
    if roi.size == 0:
        return 0.0, 0.0, 0.0
    mean_v = float(np.mean(roi))
    std_v = float(np.std(roi))
    bright_ratio = float(np.count_nonzero(roi >= 24)) / float(roi.size)
    return mean_v, std_v, bright_ratio


def _create_sift_map():
    """大地图：0 = 不限制 nfeatures。"""
    nf = int(getattr(config, "SIFT_MAP_NFEATURES", 0) or 0)
    if nf <= 0:
        return cv2.SIFT_create()
    return cv2.SIFT_create(nfeatures=nf)


def _create_sift_query():
    nq = int(getattr(config, "SIFT_QUERY_NFEATURES", 500) or 0)
    if nq <= 0:
        return cv2.SIFT_create()
    return cv2.SIFT_create(nfeatures=max(64, nq))


class SiftMapTrackerApp:
    def __init__(self, root, minimap_region=None):
        self.root = root
        self.root.title("SIFT 双地图跟点 (逻辑与显示分离)")

        self.root.attributes("-topmost", True)
        self.root.geometry(config.WINDOW_GEOMETRY)

        self.last_x = None
        self.last_y = None
        self.lost_frames = 0
        self.MAX_LOST_FRAMES = config.MAX_LOST_FRAMES

        print(f"正在加载逻辑大地图 ({config.LOGIC_MAP_PATH})…")
        self.logic_map_bgr, self._region_mask = load_logic_bgr_and_region_mask(
            config
        )
        self.map_height, self.map_width = self.logic_map_bgr.shape[:2]
        valid_px = int(np.count_nonzero(self._region_mask))
        print(
            f"有效地图区域像素: {valid_px} / {self.map_width * self.map_height} "
            f"（仅在有效区内提 SIFT）"
        )

        logic_map_gray = cv2.cvtColor(self.logic_map_bgr, cv2.COLOR_BGR2GRAY)

        print(f"正在加载显示大地图 ({config.DISPLAY_MAP_PATH})…")
        self.display_map_bgr = cv2.imread(config.DISPLAY_MAP_PATH)
        if self.display_map_bgr is None:
            raise FileNotFoundError(
                f"找不到显示地图文件: {config.DISPLAY_MAP_PATH}，请检查路径！"
            )

        dh, dw = self.display_map_bgr.shape[:2]
        if dh != self.map_height or dw != self.map_width:
            raise ValueError(
                f"严重错误：逻辑地图({self.map_width}x{self.map_height}) 与 显示地图({dw}x{dh}) 尺寸不一致！"
            )

        self.clahe = cv2.createCLAHE(
            clipLimit=config.SIFT_CLAHE_LIMIT, tileGridSize=(8, 8)
        )
        print("正在对逻辑地图进行 CLAHE…")
        logic_map_gray = self.clahe.apply(logic_map_gray)
        self.logic_map_gray = logic_map_gray
        self.logic_map_tpl = _build_template_feature_image(logic_map_gray)

        kp_big, des_big = try_load_sift_anchors(config, self.map_height, self.map_width)
        if des_big is None or kp_big is None:
            print("正在提取逻辑地图 SIFT（仅有效区域，首次较慢）…")
            sift_map = _create_sift_map()
            kp_big, des_big = sift_map.detectAndCompute(
                logic_map_gray, self._region_mask
            )
            if des_big is None or len(kp_big) == 0:
                raise RuntimeError(
                    "有效区域内未得到 SIFT 描述子：请检查掩膜/alpha 是否过严，或略放宽区域。"
                )
            print(f"✅ 锚点数量: {len(kp_big)}（已按有效区域；大地图未做数量截断）")
            save_sift_anchors(config, kp_big, des_big, self.map_height, self.map_width)
        else:
            print(f"✅ 使用缓存锚点: {len(kp_big)} 个")

        self.kp_big = kp_big
        self.des_big = des_big
        self._kp_xy = np.array(
            [[kp.pt[0], kp.pt[1]] for kp in self.kp_big], dtype=np.float32
        )

        self.sift = _create_sift_query()

        FLANN_INDEX_KDTREE = 1
        index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
        search_params = dict(checks=int(getattr(config, "SIFT_FLANN_CHECKS", 28)))
        self.flann = cv2.FlannBasedMatcher(index_params, search_params)
        self.bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        self._rng = np.random.default_rng()

        # mss 在 Win 上依赖线程局部 DC；须在调用 grab 的同一线程内创建并复用 MSS 实例
        self._mss_tls = threading.local()
        self.minimap_region = (
            minimap_region if minimap_region is not None else config.MINIMAP
        )

        self.canvas = tk.Canvas(
            root, width=config.VIEW_SIZE, height=config.VIEW_SIZE, bg="#2b2b2b"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.image_on_canvas = None
        self._track_async_busy = False
        self._fps_last_t: float | None = None
        self._fps_ema = 0.0
        self._track_inertial = False
        self._smooth_x: float | None = None
        self._smooth_y: float | None = None
        self._smooth_tick_last_t: float | None = None
        self.last_align_angle_deg: float | None = None
        self._blackout_run_frames = 0
        self._teleport_reloc_pending = False
        self._ui_occluded = False
        self._ui_occlusion_run_frames = 0
        # 复用 PhotoImage + paste，避免每帧 new 导致 Tk 侧图像堆积、长时间运行内存耗尽闪退
        self._ui_photo_ref: ImageTk.PhotoImage | None = None

        self.update_tracker()
        _di = int(getattr(config, "SIFT_DISPLAY_INTERP_MS", 0) or 0)
        if _di > 0:
            self.root.after(_di, self._smooth_display_tick)

        if bool(getattr(config, "SIFT_TRACK_PROFILE", False)):
            lp = str(getattr(config, "SIFT_TRACK_PROFILE_LOG_PATH", "") or "").strip()
            if lp:
                abs_lp = os.path.abspath(lp)
                try:
                    d = os.path.dirname(abs_lp)
                    if d:
                        os.makedirs(d, exist_ok=True)
                    with open(abs_lp, "a", encoding="utf-8") as fp:
                        fp.write(
                            f"\n[SIFT profile] --- session {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
                        )
                        fp.flush()
                    print(f"SIFT 分段计时已开启，日志文件: {abs_lp}", flush=True)
                except OSError as e:
                    print(f"SIFT 分段计时：无法写入日志文件 {abs_lp!r}: {e}", flush=True)

    def _get_mss_sct(self):
        """每个线程各自持有一个 mss.mss()，禁止跨线程复用。"""
        sct = getattr(self._mss_tls, "sct", None)
        if sct is None:
            self._mss_tls.sct = mss.mss()
            sct = self._mss_tls.sct
        return sct

    def _force_fullmap_match_state(self, lx, ly, lf: int) -> bool:
        ff = int(getattr(config, "SIFT_FORCE_FULLMAP_LOST_FRAMES", 10))
        if lx is None or ly is None:
            return True
        return lf >= ff

    def _select_train_kp_des_state(self, lx, ly, lf: int):
        if self._force_fullmap_match_state(lx, ly, lf):
            return self.kp_big, self.des_big
        r = float(getattr(config, "SIFT_LOCAL_SEARCH_RADIUS", 720))
        r += max(0.0, float(lf)) * float(
            getattr(config, "SIFT_LOCAL_RADIUS_GROW_PER_LOST_FRAME", 0.0)
        )
        r_max = float(getattr(config, "SIFT_LOCAL_SEARCH_MAX_RADIUS", 0.0))
        if r_max > 0:
            r = min(r, r_max)
        min_a = int(getattr(config, "SIFT_LOCAL_MIN_ANCHORS", 500))
        if r <= 0:
            return self.kp_big, self.des_big
        cx, cy = float(lx), float(ly)
        xy = self._kp_xy
        m = (
            (xy[:, 0] >= cx - r)
            & (xy[:, 0] <= cx + r)
            & (xy[:, 1] >= cy - r)
            & (xy[:, 1] <= cy + r)
        )
        idx = np.flatnonzero(m)
        if idx.size < min_a:
            return self.kp_big, self.des_big
        cap = int(getattr(config, "SIFT_LOCAL_MAX_ANCHORS", 0) or 0)
        if cap > 0 and idx.size > cap:
            idx = self._rng.choice(idx, size=cap, replace=False)
            idx.sort()
        return [self.kp_big[i] for i in idx], self.des_big[idx]

    def _build_minimap_mask(self, h: int, w: int) -> np.ndarray | None:
        if not getattr(config, "SIFT_MINIMAP_USE_INSCRIBED_ELLIPSE", True):
            return None
        esc = float(getattr(config, "SIFT_MINIMAP_ELLIPSE_SCALE", 1.0))
        mask = _minimap_inscribed_ellipse_mask(h, w, esc)
        hole_ratio = float(
            getattr(config, "SIFT_MINIMAP_CENTER_EXCLUDE_RADIUS_RATIO", 0.0)
        )
        if hole_ratio > 1e-6:
            cx = int(round((w - 1) * 0.5))
            cy = int(round((h - 1) * 0.5))
            rr = int(round(min(h, w) * 0.5 * hole_ratio))
            if rr > 0:
                cv2.circle(mask, (cx, cy), rr, 0, -1)
        return mask

    def _is_probably_blackout(
        self, minimap_gray_raw: np.ndarray, mask: np.ndarray | None
    ) -> bool:
        mean_v, std_v, bright_ratio = _masked_stats_u8(minimap_gray_raw, mask)
        max_mean = float(getattr(config, "SIFT_TELEPORT_BLACKOUT_MAX_MEAN", 8.0))
        max_std = float(getattr(config, "SIFT_TELEPORT_BLACKOUT_MAX_STD", 8.0))
        max_bright_ratio = float(
            getattr(config, "SIFT_TELEPORT_BLACKOUT_MAX_BRIGHT_RATIO", 0.012)
        )
        return (
            mean_v <= max_mean
            and std_v <= max_std
            and bright_ratio <= max_bright_ratio
        )

    def _resize_with_scale(
        self, image: np.ndarray | None, scale: float, *, is_mask: bool
    ) -> np.ndarray | None:
        if image is None:
            return None
        scale = float(scale)
        if abs(scale - 1.0) < 1e-6:
            return image
        h, w = image.shape[:2]
        nw = max(8, int(round(w * scale)))
        nh = max(8, int(round(h * scale)))
        interp = cv2.INTER_NEAREST if is_mask else cv2.INTER_AREA
        return cv2.resize(image, (nw, nh), interpolation=interp)

    def _rotate_query(
        self, image: np.ndarray, mask: np.ndarray | None, angle_deg: float
    ) -> tuple[np.ndarray, np.ndarray | None]:
        h, w = image.shape[:2]
        center = ((w - 1) * 0.5, (h - 1) * 0.5)
        rot_m = cv2.getRotationMatrix2D(center, float(angle_deg), 1.0)
        rot_img = cv2.warpAffine(
            image,
            rot_m,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        rot_mask = None
        if mask is not None:
            rot_mask = cv2.warpAffine(
                mask,
                rot_m,
                (w, h),
                flags=cv2.INTER_NEAREST,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
        return rot_img, rot_mask

    def _template_angle_candidates(self, global_mode: bool) -> list[float]:
        base = self.last_align_angle_deg
        angles: list[float] = []
        if base is not None:
            span = float(
                getattr(
                    config,
                    "SIFT_TEMPLATE_GLOBAL_ANGLE_SPAN"
                    if global_mode
                    else "SIFT_TEMPLATE_LOCAL_ANGLE_SPAN",
                    0.0,
                )
            )
            step = float(
                getattr(
                    config,
                    "SIFT_TEMPLATE_GLOBAL_ANGLE_STEP"
                    if global_mode
                    else "SIFT_TEMPLATE_LOCAL_ANGLE_STEP",
                    15.0,
                )
            )
            if step > 0 and span >= 0:
                i = int(round(span / step))
                angles.extend(base + k * step for k in range(-i, i + 1))
            if global_mode:
                coarse = float(getattr(config, "SIFT_TEMPLATE_GLOBAL_ANGLE_COARSE_STEP", 30.0))
                if coarse > 0:
                    angles.extend(float(k) for k in range(-180, 180, int(round(coarse))))
        else:
            coarse = float(getattr(config, "SIFT_TEMPLATE_GLOBAL_ANGLE_COARSE_STEP", 30.0))
            if coarse <= 0:
                coarse = 30.0
            angles.extend(float(k) for k in range(-180, 180, int(round(coarse))))

        ordered: list[float] = []
        seen: set[int] = set()
        for ang in angles:
            key = int(round(_normalize_angle_deg(ang) * 10.0))
            if key in seen:
                continue
            seen.add(key)
            ordered.append(_normalize_angle_deg(ang))
        return ordered

    def _match_template_over_angles(
        self,
        search: np.ndarray,
        templ: np.ndarray,
        mask: np.ndarray | None,
        angles: list[float],
    ) -> dict[str, float | tuple[int, int]] | None:
        if search.shape[0] < templ.shape[0] or search.shape[1] < templ.shape[1]:
            return None

        best_score = -1.0
        second_score = -1.0
        best_loc: tuple[int, int] | None = None
        best_angle = 0.0
        suppress_radius = int(
            getattr(config, "SIFT_TEMPLATE_PEAK_SUPPRESS_RADIUS", 18)
        )
        min_mask_px = int(getattr(config, "SIFT_TEMPLATE_MIN_MASK_PIXELS", 80))

        for ang in angles:
            rot_templ, rot_mask = self._rotate_query(templ, mask, ang)
            if rot_mask is not None and int(np.count_nonzero(rot_mask)) < min_mask_px:
                continue
            try:
                if rot_mask is not None:
                    resp = cv2.matchTemplate(
                        search,
                        rot_templ,
                        cv2.TM_CCORR_NORMED,
                        mask=rot_mask,
                    )
                else:
                    resp = cv2.matchTemplate(
                        search,
                        rot_templ,
                        cv2.TM_CCOEFF_NORMED,
                    )
            except cv2.error:
                continue

            _min_v, max_v, _min_loc, max_loc = cv2.minMaxLoc(resp)
            score = float(max_v)
            alt = _peak_second_best(resp, max_loc, suppress_radius)
            if score > best_score:
                second_score = max(second_score, best_score, alt)
                best_score = score
                best_loc = max_loc
                best_angle = float(ang)
            else:
                second_score = max(second_score, score, alt)

        if best_loc is None:
            return None
        return {
            "score": best_score,
            "second": max(0.0, second_score),
            "angle": best_angle,
            "loc": best_loc,
        }

    def _estimate_align_angle_deg(
        self, M: np.ndarray, query_w: int, query_h: int
    ) -> float | None:
        pts = np.float32(
            [
                [[query_w * 0.5, query_h * 0.5]],
                [[query_w * 0.5, 0.0]],
            ]
        )
        try:
            dst = cv2.perspectiveTransform(pts, M).reshape(-1, 2)
        except cv2.error:
            return None
        vec = dst[1] - dst[0]
        norm = float(np.hypot(vec[0], vec[1]))
        if norm < 1e-4:
            return None
        angle = math.degrees(math.atan2(float(vec[0]), float(-vec[1])))
        return _normalize_angle_deg(angle)

    def _is_valid_center(self, x: float, y: float) -> bool:
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            return False
        xi = int(round(x))
        yi = int(round(y))
        xi = max(0, min(self.map_width - 1, xi))
        yi = max(0, min(self.map_height - 1, yi))
        return bool(self._region_mask[yi, xi] > 0)

    def _local_motion_limit(self, lf: int, for_template: bool = False) -> float:
        base = float(getattr(config, "SIFT_LOCAL_MAX_JUMP", 180.0))
        grow = float(getattr(config, "SIFT_LOCAL_JUMP_PER_LOST_FRAME", 40.0))
        if for_template:
            base *= float(getattr(config, "SIFT_TEMPLATE_JUMP_SCALE", 1.35))
        return max(0.0, base + max(0, int(lf)) * grow)

    def _accept_sift_candidate(
        self,
        cand_x: float,
        cand_y: float,
        prev_x: float | None,
        prev_y: float | None,
        prev_lost: int,
        good_count: int,
        inlier_count: int,
        force_fullmap: bool,
    ) -> bool:
        if not self._is_valid_center(cand_x, cand_y):
            return False

        min_inliers = int(getattr(config, "SIFT_MIN_INLIER_COUNT", 5))
        if inlier_count < min_inliers:
            return False

        min_ratio = float(getattr(config, "SIFT_MIN_INLIER_RATIO", 0.38))
        if good_count > 0 and (inlier_count / float(good_count)) < min_ratio:
            return False

        if not force_fullmap and prev_x is not None and prev_y is not None:
            jump = math.hypot(float(cand_x) - float(prev_x), float(cand_y) - float(prev_y))
            if jump > self._local_motion_limit(prev_lost, for_template=False):
                return False
        return True

    def _run_template_fallback(
        self,
        minimap_gray: np.ndarray,
        minimap_mask: np.ndarray | None,
        lx: float | None,
        ly: float | None,
        lf: int,
        force_fullmap: bool,
    ) -> tuple[int, int] | None:
        h, w = minimap_gray.shape[:2]
        if h < 8 or w < 8:
            return None

        global_mode = force_fullmap or lx is None or ly is None
        half_w = w * 0.5
        half_h = h * 0.5

        if global_mode:
            left = 0
            top = 0
            search = self.logic_map_tpl
            coarse_scale = float(getattr(config, "SIFT_TEMPLATE_GLOBAL_SCALE", 0.14))
            min_score = float(
                getattr(config, "SIFT_TEMPLATE_GLOBAL_MIN_SCORE", 0.80)
            )
            min_delta = float(
                getattr(config, "SIFT_TEMPLATE_GLOBAL_MIN_DELTA", 0.010)
            )
        else:
            radius = float(getattr(config, "SIFT_TEMPLATE_RADIUS", 240.0))
            radius += max(0.0, float(lf)) * float(
                getattr(config, "SIFT_TEMPLATE_RADIUS_GROW_PER_LOST_FRAME", 35.0)
            )
            r_max = float(getattr(config, "SIFT_TEMPLATE_MAX_RADIUS", 0.0))
            if r_max > 0:
                radius = min(radius, r_max)

            left = int(math.floor(float(lx) - half_w - radius))
            top = int(math.floor(float(ly) - half_h - radius))
            right = int(math.ceil(float(lx) + half_w + radius))
            bottom = int(math.ceil(float(ly) + half_h + radius))
            left = max(0, left)
            top = max(0, top)
            right = min(self.map_width, right)
            bottom = min(self.map_height, bottom)
            search = self.logic_map_tpl[top:bottom, left:right]
            coarse_scale = float(getattr(config, "SIFT_TEMPLATE_LOCAL_SCALE", 0.55))
            min_score = float(getattr(config, "SIFT_TEMPLATE_MIN_SCORE", 0.84))
            min_delta = float(getattr(config, "SIFT_TEMPLATE_MIN_DELTA", 0.015))

        if search.shape[0] < h or search.shape[1] < w:
            return None

        search_small = self._resize_with_scale(search, coarse_scale, is_mask=False)
        templ_small = self._resize_with_scale(minimap_gray, coarse_scale, is_mask=False)
        mask_small = self._resize_with_scale(minimap_mask, coarse_scale, is_mask=True)
        if search_small is None or templ_small is None:
            return None

        angles = self._template_angle_candidates(global_mode)
        coarse = self._match_template_over_angles(
            search_small, templ_small, mask_small, angles
        )
        if coarse is None:
            return None
        if float(coarse["score"]) < min_score or (
            float(coarse["score"]) - float(coarse["second"])
        ) < min_delta:
            return None

        coarse_loc = coarse["loc"]
        if not isinstance(coarse_loc, tuple):
            return None
        coarse_cx = float(left) + (
            float(coarse_loc[0]) + templ_small.shape[1] * 0.5
        ) / coarse_scale
        coarse_cy = float(top) + (
            float(coarse_loc[1]) + templ_small.shape[0] * 0.5
        ) / coarse_scale

        refine_margin = int(getattr(config, "SIFT_TEMPLATE_REFINE_MARGIN", 96))
        ref_left = max(0, int(round(coarse_cx - half_w - refine_margin)))
        ref_top = max(0, int(round(coarse_cy - half_h - refine_margin)))
        ref_right = min(self.map_width, int(round(coarse_cx + half_w + refine_margin)))
        ref_bottom = min(
            self.map_height, int(round(coarse_cy + half_h + refine_margin))
        )
        ref_search = self.logic_map_tpl[ref_top:ref_bottom, ref_left:ref_right]
        if ref_search.shape[0] < h or ref_search.shape[1] < w:
            ref_search = search
            ref_left = left
            ref_top = top

        refine_span = float(getattr(config, "SIFT_TEMPLATE_REFINE_ANGLE_SPAN", 6.0))
        refine_step = float(getattr(config, "SIFT_TEMPLATE_REFINE_ANGLE_STEP", 2.0))
        refine_angles = [float(coarse["angle"])]
        if refine_step > 0 and refine_span > 0:
            n = int(round(refine_span / refine_step))
            refine_angles = [
                _normalize_angle_deg(float(coarse["angle"]) + k * refine_step)
                for k in range(-n, n + 1)
            ]
        refine = self._match_template_over_angles(
            ref_search, minimap_gray, minimap_mask, refine_angles
        )
        pick = coarse if refine is None else refine
        pick_left = left if refine is None else ref_left
        pick_top = top if refine is None else ref_top
        pick_w = templ_small.shape[1] if refine is None else w
        pick_h = templ_small.shape[0] if refine is None else h
        pick_scale = coarse_scale if refine is None else 1.0

        if float(pick["score"]) < min_score or (
            float(pick["score"]) - float(pick["second"])
        ) < min_delta:
            return None

        pick_loc = pick["loc"]
        if not isinstance(pick_loc, tuple):
            return None
        cand_x = float(pick_left) + (float(pick_loc[0]) + pick_w * 0.5) / pick_scale
        cand_y = float(pick_top) + (float(pick_loc[1]) + pick_h * 0.5) / pick_scale
        if not self._is_valid_center(cand_x, cand_y):
            return None

        if not global_mode and lx is not None and ly is not None:
            jump = math.hypot(cand_x - float(lx), cand_y - float(ly))
            if jump > self._local_motion_limit(lf, for_template=True):
                return None

        self.last_align_angle_deg = _normalize_angle_deg(float(pick["angle"]))
        return int(round(cand_x)), int(round(cand_y))

    def _compose_display_view(
        self,
        center_x: float | None,
        center_y: float | None,
        is_inertial: bool,
    ) -> np.ndarray:
        """按大地图显示层裁剪窗口并画位置点；center 可为亚像素（插帧平滑）。"""
        vs = int(config.VIEW_SIZE)
        half = int(getattr(config, "VIEW_MAP_HALF_SIZE", vs // 2))
        half = max(half, vs // 2)

        if center_x is None or center_y is None:
            display_crop = np.zeros((vs, vs, 3), dtype=np.uint8)
            cv2.putText(
                display_crop,
                "SIFT Searching...",
                (70, 200),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )
            return display_crop

        cx = float(center_x)
        cy = float(center_y)
        cx_i = int(round(cx))
        cy_i = int(round(cy))
        y1 = max(0, cy_i - half)
        y2 = min(self.map_height, cy_i + half)
        x1 = max(0, cx_i - half)
        x2 = min(self.map_width, cx_i + half)
        roi = self.display_map_bgr[y1:y2, x1:x2]
        ch, cw = roi.shape[:2]
        loc_x = cx - float(x1)
        loc_y = cy - float(y1)
        if cw >= 1 and ch >= 1:
            display_crop = cv2.resize(
                roi, (vs, vs), interpolation=cv2.INTER_AREA
            )
            lx_s = int(round(loc_x * vs / cw))
            ly_s = int(round(loc_y * vs / ch))
            lx_s = max(0, min(vs - 1, lx_s))
            ly_s = max(0, min(vs - 1, ly_s))
            r_in = max(4, int(round(10 * vs / max(cw, ch))))
            r_out = max(5, int(round(12 * vs / max(cw, ch))))
            if not is_inertial:
                cv2.circle(
                    display_crop,
                    (lx_s, ly_s),
                    radius=r_in,
                    color=(0, 0, 255),
                    thickness=-1,
                )
                cv2.circle(
                    display_crop,
                    (lx_s, ly_s),
                    radius=r_out,
                    color=(255, 255, 255),
                    thickness=2,
                )
            else:
                cv2.circle(
                    display_crop,
                    (lx_s, ly_s),
                    radius=r_in,
                    color=(0, 255, 255),
                    thickness=-1,
                )
                cv2.circle(
                    display_crop,
                    (lx_s, ly_s),
                    radius=r_out,
                    color=(0, 150, 150),
                    thickness=2,
                )
        else:
            display_crop = np.zeros((vs, vs, 3), dtype=np.uint8)
        return display_crop

    def _run_tracking_core(
        self,
    ) -> tuple[int | None, int | None, int, bool]:
        """
        截屏 + SIFT + 匹配。可在后台线程调用（勿碰 Tk）。
        返回 (last_x, last_y, lost_frames, is_inertial)；显示由 _compose_display_view / 插帧 负责。
        """
        prof = bool(getattr(config, "SIFT_TRACK_PROFILE", False))
        _pc = time.perf_counter
        t_all = _pc()
        seg_ms: dict[str, float] = {}

        lx, ly, lf = self.last_x, self.last_y, self.lost_frames

        clear_after = int(getattr(config, "SIFT_CLEAR_LOCK_AFTER_LOST_FRAMES", 0))
        if clear_after > 0 and lf >= clear_after:
            lx, ly, lf = None, None, 0

        t = _pc()
        screenshot = self._get_mss_sct().grab(self.minimap_region)
        minimap_bgr = np.array(screenshot)[:, :, :3]
        if prof:
            seg_ms["grab"] = (_pc() - t) * 1000.0

        t = _pc()
        minimap_gray_raw = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2GRAY)
        mask_gray = self._build_minimap_mask(*minimap_gray_raw.shape[:2])
        is_blackout = self._is_probably_blackout(minimap_gray_raw, mask_gray)
        if is_blackout:
            self._blackout_run_frames += 1
            min_frames = int(getattr(config, "SIFT_TELEPORT_BLACKOUT_MIN_FRAMES", 2))
            if self._blackout_run_frames >= max(1, min_frames):
                self._teleport_reloc_pending = True
                self.last_align_angle_deg = None
            if prof:
                seg_ms["black"] = (_pc() - t) * 1000.0
                seg_ms["total"] = (_pc() - t_all) * 1000.0
            if lx is not None and ly is not None:
                return lx, ly, lf, True
            return None, None, lf, False

        force_fullmap_override = False
        if self._blackout_run_frames > 0:
            force_fullmap_override = self._teleport_reloc_pending
            self._blackout_run_frames = 0
            self._teleport_reloc_pending = False

        minimap_gray = self.clahe.apply(minimap_gray_raw)
        minimap_tpl = _build_template_feature_image(minimap_gray)

        qe = int(getattr(config, "SIFT_QUERY_MAX_EDGE", 256))
        mini_gray = _downscale_gray_max_edge(minimap_gray, qe)
        mh, mw = mini_gray.shape[:2]
        mask_mini = self._build_minimap_mask(mh, mw)
        if prof:
            seg_ms["prep"] = (_pc() - t) * 1000.0

        t = _pc()
        kp_mini, des_mini = self.sift.detectAndCompute(mini_gray, mask_mini)
        if prof:
            seg_ms["sift_q"] = (_pc() - t) * 1000.0

        raw_kp_count = int(len(kp_mini)) if kp_mini is not None else 0
        min_kp = int(getattr(config, "SIFT_MINIMAP_MIN_KP", 8))
        if des_mini is not None and len(kp_mini) < min_kp:
            des_mini = None

        ui_resume_kp = int(getattr(config, "SIFT_UI_OCCLUDE_RESUME_MIN_KP", 10))
        if self._ui_occluded and raw_kp_count < max(min_kp, ui_resume_kp):
            if prof:
                seg_ms["total"] = (_pc() - t_all) * 1000.0
            if lx is not None and ly is not None:
                return lx, ly, lf, True
            return None, None, lf, False

        t = _pc()
        kp_train, des_train = self._select_train_kp_des_state(lx, ly, lf)
        if prof:
            seg_ms["train"] = (_pc() - t) * 1000.0

        nq = int(len(des_mini)) if des_mini is not None else 0
        nt = int(len(des_train)) if des_train is not None else 0

        found = False
        center_x, center_y = None, None
        is_inertial = False
        force_fullmap = force_fullmap_override or self._force_fullmap_match_state(
            lx, ly, lf
        )
        if self._ui_occluded and raw_kp_count >= max(min_kp, ui_resume_kp):
            self._ui_occluded = False
            self._ui_occlusion_run_frames = 0
            self.last_align_angle_deg = None
            force_fullmap = True

        if des_mini is not None and len(kp_mini) >= 2 and des_train is not None:
            use_bf = nt < int(getattr(config, "SIFT_USE_BF_BELOW", 3500))
            t = _pc()
            if use_bf:
                matches = self.bf.knnMatch(des_mini, des_train, k=2)
            else:
                matches = self.flann.knnMatch(des_mini, des_train, k=2)
            if prof:
                seg_ms["knn"] = (_pc() - t) * 1000.0

            t = _pc()
            good_matches = []
            for m_n in matches:
                if len(m_n) == 2:
                    m, n = m_n
                    if m.distance < config.SIFT_MATCH_RATIO * n.distance:
                        good_matches.append(m)
            if prof:
                seg_ms["ratio"] = (_pc() - t) * 1000.0

            min_need = int(config.SIFT_MIN_MATCH_COUNT)
            if force_fullmap:
                min_need += int(getattr(config, "SIFT_RELOC_EXTRA_MIN_MATCH", 0))

            if len(good_matches) >= min_need:
                t = _pc()
                src_pts = np.float32(
                    [kp_mini[m.queryIdx].pt for m in good_matches]
                ).reshape(-1, 1, 2)
                dst_pts = np.float32(
                    [kp_train[m.trainIdx].pt for m in good_matches]
                ).reshape(-1, 1, 2)

                M, mask = cv2.findHomography(
                    src_pts, dst_pts, cv2.RANSAC, config.SIFT_RANSAC_THRESHOLD
                )

                if M is not None:
                    inlier_count = int(mask.sum()) if mask is not None else 0
                    h_m, w_m = mini_gray.shape[:2]
                    center_pt = np.float32([[[w_m / 2.0, h_m / 2.0]]])
                    dst_center = cv2.perspectiveTransform(center_pt, M)
                    temp_x = float(dst_center[0][0][0])
                    temp_y = float(dst_center[0][0][1])

                    if self._accept_sift_candidate(
                        temp_x,
                        temp_y,
                        lx,
                        ly,
                        lf,
                        len(good_matches),
                        inlier_count,
                        force_fullmap,
                    ):
                        found = True
                        center_x = int(round(temp_x))
                        center_y = int(round(temp_y))
                        lx, ly = center_x, center_y
                        lf = 0
                        est_ang = self._estimate_align_angle_deg(M, w_m, h_m)
                        if est_ang is not None:
                            self.last_align_angle_deg = est_ang
                if prof:
                    seg_ms["pose"] = (_pc() - t) * 1000.0

        if (
            not found
            and bool(getattr(config, "SIFT_TEMPLATE_FALLBACK", True))
        ):
            t = _pc()
            fallback = self._run_template_fallback(
                minimap_tpl, mask_gray, lx, ly, lf, force_fullmap
            )
            if fallback is not None:
                center_x, center_y = fallback
                lx, ly = center_x, center_y
                lf = 0
                found = True
            if prof:
                seg_ms["tmpl"] = (_pc() - t) * 1000.0

        if found:
            self._ui_occlusion_run_frames = 0
            self._ui_occluded = False
        else:
            occ_max_kp = int(getattr(config, "SIFT_UI_OCCLUDE_MAX_KP", 4))
            occ_min_frames = int(getattr(config, "SIFT_UI_OCCLUDE_MIN_FRAMES", 8))
            if raw_kp_count <= occ_max_kp:
                self._ui_occlusion_run_frames += 1
                if self._ui_occlusion_run_frames >= max(1, occ_min_frames):
                    self._ui_occluded = True
                    self.last_align_angle_deg = None
                    if prof:
                        seg_ms["total"] = (_pc() - t_all) * 1000.0
                    if lx is not None and ly is not None:
                        return lx, ly, lf, True
                    return None, None, lf, False
            else:
                self._ui_occlusion_run_frames = 0

        if not found and lx is not None and ly is not None:
            lf += 1
            if lf <= self.MAX_LOST_FRAMES:
                found = True
                center_x, center_y = lx, ly
                is_inertial = True

        if prof:
            seg_ms["total"] = (_pc() - t_all) * 1000.0
            self._profile_i = getattr(self, "_profile_i", 0) + 1
            ev = int(getattr(config, "SIFT_TRACK_PROFILE_EVERY", 25))
            if ev <= 0:
                ev = 1
            do_log = self._profile_i == 1 or (self._profile_i % ev == 0)
            if do_log:
                def g(k: str) -> float:
                    return float(seg_ms.get(k, 0.0))

                bf = "bf" if nt < int(getattr(config, "SIFT_USE_BF_BELOW", 3500)) else "flann"
                line = (
                    "[SIFT profile] "
                    f"total={g('total'):.1f}ms "
                    f"grab={g('grab'):.1f} prep={g('prep'):.1f} "
                    f"sift_q={g('sift_q'):.1f} train={g('train'):.1f} "
                    f"knn({bf})={g('knn'):.1f} ratio={g('ratio'):.1f} pose={g('pose'):.1f} "
                    f"tmpl={g('tmpl'):.1f} | "
                    f"nq={nq} nt={nt}"
                )
                log_path = getattr(config, "SIFT_TRACK_PROFILE_LOG_PATH", None)
                if log_path:
                    lp = str(log_path).strip()
                    if lp:
                        try:
                            abs_lp = os.path.abspath(lp)
                            d = os.path.dirname(abs_lp)
                            if d:
                                os.makedirs(d, exist_ok=True)
                            with open(abs_lp, "a", encoding="utf-8") as fp:
                                fp.write(line + "\n")
                                fp.flush()
                        except OSError as e:
                            print(f"[SIFT profile] 无法写入日志 {abs_lp!r}: {e}", flush=True)
                if getattr(config, "SIFT_TRACK_PROFILE_PRINT", False):
                    print(line, flush=True)

        return lx, ly, lf, is_inertial

    def _bump_track_fps_ema(self) -> None:
        """仅在每次跟踪完成时调用，表示「定位更新率」而非界面重绘率。"""
        now = time.perf_counter()
        if self._fps_last_t is not None:
            dt = now - self._fps_last_t
            if dt > 1e-9:
                inst = 1.0 / dt
                if self._fps_ema <= 1e-6:
                    self._fps_ema = inst
                else:
                    self._fps_ema = 0.88 * self._fps_ema + 0.12 * inst
        self._fps_last_t = now

    def _overlay_fps_on(self, display_bgr: np.ndarray) -> np.ndarray:
        if not getattr(config, "SIFT_SHOW_FPS", True):
            return display_bgr

        _, w = display_bgr.shape[:2]
        label = f"FPS {self._fps_ema:.1f}" if self._fps_ema > 0.15 else "FPS ---"
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = max(0.45, min(0.72, w / 520.0))
        thickness = max(1, int(round(scale * 2)))
        (tw, th), _bl = cv2.getTextSize(label, font, scale, thickness)
        pad = 6
        org_x = w - tw - pad
        org_y = pad + th
        cv2.putText(
            display_bgr,
            label,
            (org_x, org_y),
            font,
            scale,
            (160, 255, 200),
            thickness,
            cv2.LINE_AA,
        )
        return display_bgr

    def _apply_tracker_ui(self, display_bgr: np.ndarray) -> None:
        display_bgr = self._overlay_fps_on(display_bgr)
        display_rgb = cv2.cvtColor(display_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(display_rgb)
        ref = self._ui_photo_ref
        if ref is None:
            self._ui_photo_ref = ImageTk.PhotoImage(pil_img)
        else:
            ref.paste(pil_img)
        self.tk_image = self._ui_photo_ref
        if self.image_on_canvas is None:
            self.image_on_canvas = self.canvas.create_image(
                0, 0, anchor=tk.NW, image=self.tk_image
            )
        else:
            self.canvas.itemconfig(self.image_on_canvas, image=self.tk_image)

    def _snap_smooth_on_teleport(self, lx: int, ly: int) -> None:
        tp = float(getattr(config, "SIFT_DISPLAY_TELEPORT_PX", 200.0))
        if self._smooth_x is None or self._smooth_y is None:
            self._smooth_x, self._smooth_y = float(lx), float(ly)
            return
        if math.hypot(float(lx) - self._smooth_x, float(ly) - self._smooth_y) > tp:
            self._smooth_x, self._smooth_y = float(lx), float(ly)

    def _on_tracker_result(
        self, lx: int | None, ly: int | None, lf: int, is_inertial: bool
    ) -> None:
        self.last_x, self.last_y, self.lost_frames = lx, ly, lf
        self._track_inertial = is_inertial
        if lx is None or ly is None:
            self._smooth_x = None
            self._smooth_y = None
        else:
            self._snap_smooth_on_teleport(lx, ly)

        self._bump_track_fps_ema()
        interp_ms = int(getattr(config, "SIFT_DISPLAY_INTERP_MS", 0) or 0)
        if interp_ms <= 0:
            img = self._compose_display_view(
                float(lx) if lx is not None else None,
                float(ly) if ly is not None else None,
                is_inertial,
            )
            self._apply_tracker_ui(img)

    def _smooth_display_tick(self) -> None:
        interp_ms = int(getattr(config, "SIFT_DISPLAY_INTERP_MS", 0) or 0)
        if interp_ms <= 0:
            return

        lx, ly = self.last_x, self.last_y
        tau = float(getattr(config, "SIFT_DISPLAY_SMOOTH_TAU", 0.11))
        now = time.perf_counter()
        if self._smooth_tick_last_t is None:
            dt = interp_ms * 0.001
        else:
            dt = max(1e-4, now - self._smooth_tick_last_t)
        self._smooth_tick_last_t = now

        if lx is not None and ly is not None:
            ax, ay = float(lx), float(ly)
            if self._smooth_x is None or self._smooth_y is None:
                self._smooth_x, self._smooth_y = ax, ay
            else:
                k = 1.0 - math.exp(-dt / tau) if tau > 1e-6 else 1.0
                self._smooth_x += k * (ax - self._smooth_x)
                self._smooth_y += k * (ay - self._smooth_y)

            img = self._compose_display_view(
                self._smooth_x, self._smooth_y, self._track_inertial
            )
            self._apply_tracker_ui(img)
        else:
            self._smooth_x = None
            self._smooth_y = None
            img = self._compose_display_view(None, None, False)
            self._apply_tracker_ui(img)

        self.root.after(interp_ms, self._smooth_display_tick)

    def _tracker_finish_async(self, pack: tuple) -> None:
        self._track_async_busy = False
        lx, ly, lf, is_inertial = pack
        self._on_tracker_result(lx, ly, lf, is_inertial)
        self.root.after(config.SIFT_REFRESH_RATE, self.update_tracker)

    def _tracker_async_error(self, err: BaseException) -> None:
        self._track_async_busy = False
        print(f"跟踪线程异常: {err}")
        self.root.after(config.SIFT_REFRESH_RATE, self.update_tracker)

    def update_tracker(self) -> None:
        use_bg = getattr(config, "SIFT_TRACK_IN_BACKGROUND", True)
        if use_bg:
            if self._track_async_busy:
                self.root.after(config.SIFT_REFRESH_RATE, self.update_tracker)
                return
            self._track_async_busy = True

            def worker() -> None:
                try:
                    pack = self._run_tracking_core()
                    self.root.after(0, lambda p=pack: self._tracker_finish_async(p))
                except Exception as e:
                    self.root.after(0, lambda ex=e: self._tracker_async_error(ex))

            threading.Thread(target=worker, daemon=True).start()
        else:
            pack = self._run_tracking_core()
            lx, ly, lf, is_inertial = pack
            self._on_tracker_result(lx, ly, lf, is_inertial)
            self.root.after(config.SIFT_REFRESH_RATE, self.update_tracker)


if __name__ == "__main__":
    from screen_pick import run_with_screen_pick

    run_with_screen_pick(
        SiftMapTrackerApp,
        title_hint="SIFT 双地图跟点 (逻辑与显示分离)",
    )