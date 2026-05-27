"""
逻辑大地图有效区域：仅在「有地图」的像素上提 SIFT，避免 PNG 留白/透明区参与匹配。
支持：PNG alpha、可选单通道掩膜图、边缘收缩。
"""

from __future__ import annotations

import os

import cv2
import numpy as np


def load_logic_bgr_and_region_mask(config) -> tuple[np.ndarray, np.ndarray]:
    """
    返回 (BGR 逻辑图, uint8 掩膜 255=允许提特征, 0=忽略)。
    """
    path = config.LOGIC_MAP_PATH
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise FileNotFoundError(f"无法读取逻辑地图: {path}")

    mask: np.ndarray | None = None

    if raw.ndim == 3 and raw.shape[2] == 4:
        bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        thr = int(getattr(config, "SIFT_MASK_ALPHA_THRESHOLD", 16))
        mask = (raw[:, :, 3] > thr).astype(np.uint8) * 255
    elif raw.ndim == 3 and raw.shape[2] == 3:
        bgr = raw
    else:
        raise ValueError(f"不支持的逻辑图格式: shape={raw.shape}")

    ext_mask = getattr(config, "LOGIC_MAP_MASK_PATH", None)
    if ext_mask and str(ext_mask).strip():
        mp = str(ext_mask)
        if os.path.isfile(mp):
            m = cv2.imread(mp, cv2.IMREAD_GRAYSCALE)
            if m is None:
                raise FileNotFoundError(f"无法读取掩膜: {mp}")
            if m.shape[0] != bgr.shape[0] or m.shape[1] != bgr.shape[1]:
                raise ValueError(
                    f"掩膜尺寸 {m.shape[1]}x{m.shape[0]} 与逻辑图 {bgr.shape[1]}x{bgr.shape[0]} 不一致"
                )
            m_bin = (m > 127).astype(np.uint8) * 255
            if mask is not None:
                mask = cv2.bitwise_and(mask, m_bin)
            else:
                mask = m_bin

    if mask is None:
        h, w = bgr.shape[:2]
        mask = np.full((h, w), 255, dtype=np.uint8)

    shrink = int(getattr(config, "SIFT_MASK_EDGE_SHRINK", 0))
    if shrink > 0:
        k = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (shrink * 2 + 1, shrink * 2 + 1)
        )
        mask = cv2.erode(mask, k)

    return bgr, mask


def sift_anchors_cache_path(config) -> str:
    if getattr(config, "SIFT_ANCHORS_AUTO_NAME", True):
        stem = os.path.splitext(os.path.basename(config.LOGIC_MAP_PATH))[0]
        return os.path.join(config._OUT, f"sift_anchors_{stem}.npz")
    p = getattr(config, "SIFT_ANCHORS_PATH", None)
    if p:
        return str(p)
    return os.path.join(config._OUT, "sift_anchors.npz")


def _mask_extra_mtime(config) -> float:
    mp = getattr(config, "LOGIC_MAP_MASK_PATH", None)
    if mp and str(mp).strip() and os.path.isfile(str(mp)):
        return float(os.path.getmtime(str(mp)))
    return 0.0


def try_load_sift_anchors(
    config, map_h: int, map_w: int
) -> tuple[list | None, np.ndarray | None]:
    path = sift_anchors_cache_path(config)
    if not os.path.isfile(path):
        return None, None
    try:
        z = np.load(path, allow_pickle=False)
        if int(z["map_h"]) != map_h or int(z["map_w"]) != map_w:
            return None, None
        if float(z["logic_mtime"]) != os.path.getmtime(config.LOGIC_MAP_PATH):
            return None, None
        if "mask_mtime" in z.files and abs(
            float(z["mask_mtime"]) - _mask_extra_mtime(config)
        ) > 1e-6:
            return None, None
        clahe = float(getattr(config, "SIFT_CLAHE_LIMIT", 3.0))
        if "clahe_limit" in z.files and abs(float(z["clahe_limit"]) - clahe) > 1e-6:
            return None, None
        nf = int(getattr(config, "SIFT_MAP_NFEATURES", 0) or 0)
        if "nfeatures" in z.files and int(z["nfeatures"]) != nf:
            return None, None
        thr = int(getattr(config, "SIFT_MASK_ALPHA_THRESHOLD", 16))
        if "alpha_thr" in z.files and int(z["alpha_thr"]) != thr:
            return None, None
        sh = int(getattr(config, "SIFT_MASK_EDGE_SHRINK", 0))
        if "edge_shrink" in z.files and int(z["edge_shrink"]) != sh:
            return None, None

        des = z["des"]
        kp_arr = z["kp"]
        kps = _array_to_kp(kp_arr)
        print(f"已载入锚点缓存: {path}（{len(kps)} 个）")
        return kps, des
    except Exception as e:
        print(f"锚点缓存无效，将重新计算: {e}")
        return None, None


def save_sift_anchors(
    config,
    kp: list,
    des: np.ndarray,
    map_h: int,
    map_w: int,
) -> None:
    path = sift_anchors_cache_path(config)
    nf = int(getattr(config, "SIFT_MAP_NFEATURES", 0) or 0)
    try:
        np.savez_compressed(
            path,
            kp=_kp_to_array(kp),
            des=des,
            map_h=map_h,
            map_w=map_w,
            logic_mtime=os.path.getmtime(config.LOGIC_MAP_PATH),
            mask_mtime=_mask_extra_mtime(config),
            clahe_limit=float(getattr(config, "SIFT_CLAHE_LIMIT", 3.0)),
            nfeatures=nf,
            alpha_thr=int(getattr(config, "SIFT_MASK_ALPHA_THRESHOLD", 16)),
            edge_shrink=int(getattr(config, "SIFT_MASK_EDGE_SHRINK", 0)),
        )
        print(f"锚点已保存: {path}")
    except Exception as e:
        print(f"锚点保存失败（不影响运行）: {e}")


def _kp_to_array(kps: list) -> np.ndarray:
    if not kps:
        return np.zeros((0, 7), dtype=np.float32)
    return np.array(
        [
            [
                kp.pt[0],
                kp.pt[1],
                kp.size,
                kp.angle,
                kp.response,
                kp.octave,
                kp.class_id,
            ]
            for kp in kps
        ],
        dtype=np.float32,
    )


def _array_to_kp(arr: np.ndarray) -> list:
    kps = []
    for r in arr:
        kps.append(
            cv2.KeyPoint(
                float(r[0]),
                float(r[1]),
                float(r[2]),
                float(r[3]),
                float(r[4]),
                int(r[5]),
                int(r[6]),
            )
        )
    return kps
