import re
import warnings

import cv2
import numpy as np

try:
    import easyocr
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        _reader = easyocr.Reader(["ch_sim", "en"], verbose=False)
except ImportError:
    _reader = None

from config import CONFIG


def _extract_ocr_roi(full_bgr: np.ndarray, width: int, height: int) -> np.ndarray:
    l = max(0, int(width * CONFIG.ocr_roi_left_ratio))
    t = max(0, int(height * CONFIG.ocr_roi_top_ratio))
    w = max(1, min(width - l, int(width * CONFIG.ocr_roi_width_ratio)))
    h = max(1, min(height - t, int(height * CONFIG.ocr_roi_height_ratio)))
    return full_bgr[t:t + h, l:l + w]


def _preprocess(bgr_patch: np.ndarray) -> np.ndarray:
    scale_factor = CONFIG.ocr_upscale_factor
    new_w = max(1, int(bgr_patch.shape[1] * scale_factor))
    new_h = max(1, int(bgr_patch.shape[0] * scale_factor))
    return cv2.resize(bgr_patch, (new_w, new_h), interpolation=cv2.INTER_CUBIC)


def recognize_spirit_name(full_bgr: np.ndarray, width: int, height: int) -> str:
    if _reader is None:
        return CONFIG.ocr_fallback_text

    try:
        patch = _extract_ocr_roi(full_bgr, width, height)
        processed = _preprocess(patch)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            results = _reader.readtext(processed)

        if not results:
            return CONFIG.ocr_fallback_text

        first_text = results[0][1]
        match = re.match(r"[\u4e00-\u9fff]+", first_text)
        return match.group(0) if match else CONFIG.ocr_fallback_text

    except Exception:
        return CONFIG.ocr_fallback_text
