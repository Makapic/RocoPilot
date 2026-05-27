import json
import os
import sys
from dataclasses import dataclass, field


def _base_dir() -> str:
    """Return the directory that contains templates/."""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "_internal")
    return os.path.dirname(os.path.abspath(__file__))


def _exe_dir() -> str:
    """Return the directory next to the exe (writable, for logs)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_PREFS_PATH = os.path.join(_exe_dir(), "user_prefs.json")


def load_prefs() -> dict:
    try:
        with open(_PREFS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_prefs(prefs: dict) -> None:
    with open(_PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)


@dataclass
class AppConfig:
    # A visible window title keyword for your game client.
    window_title_keyword: str = "洛克王国：世界"

    # Reference resolution for template matching.
    ref_width: int = 2560
    ref_height: int = 1600
    require_exact_resolution: bool = False

    # Polling interval must be <= 5.0 seconds per user requirement.
    poll_interval_sec: float = 0.4

    # Trigger exactly one key press on state transition.
    press_key: str = "x"
    # User requirement: If in battle, keep pressing X with 1.0s interval.
    trigger_cooldown_sec: float = 1.0

    # Detection settings.
    match_threshold: float = 0.40
    use_edge_match: bool = True

    # Detection ROI: right-bottom quarter of the window.
    roi_left_ratio: float = 0.5
    roi_top_ratio: float = 0.5
    roi_width_ratio: float = 0.5
    roi_height_ratio: float = 0.5

    # Templates.
    template_dir: str = field(default_factory=lambda: os.path.join(_base_dir(), "templates"))
    template_pattern: str = "*.png"
    capture_template_name: str = "capture.png"
    pollute_capture_template_name: str = "pollute_capture.png"
    battle_end_template_names: tuple = ("elf_P.png", "missions.png", "map.png")

    # Teammate reconnect detection (non-battle state).
    reconnect_template_name: str = "qiudaidai.png"
    reconnect_accept_key: str = "f"
    reconnect_center_roi: tuple = (0.2, 0.2, 0.6, 0.6)  # (left, top, width, height)
    reconnect_threshold: float = 0.7

    # OCR spirit name detection ROI: top-right corner of the game window.
    ocr_roi_left_ratio: float = 0.85
    ocr_roi_top_ratio: float = 0.0
    ocr_roi_width_ratio: float = 0.15
    ocr_roi_height_ratio: float = 0.15

    # OCR preprocessing parameters.
    ocr_upscale_factor: float = 2.0
    ocr_fallback_text: str = "未知"

    # Pollution battle CSV log.
    pollute_log_path: str = field(default_factory=lambda: os.path.join(_exe_dir(), "logs", "pollute_log.csv"))

    # Pet detection mode.
    pet_model_dir: str = field(default_factory=lambda: os.path.join(_exe_dir(), "models"))
    pet_model_name: str = "xueren"
    pet_conf_threshold: float = 0.4
    # Fixed-step iterative aiming: small uniform steps, fast cadence.
    pet_iterative_aim: bool = True
    pet_aim_step_px: int = 40                  # Fixed mouse pixels per step.
    pet_aim_max_iters: int = 15                # Max iterations per aim attempt.

    pet_aim_center_thresh: int = 6             # Centering threshold (pixels), both axes.
    pet_aim_camera_delay: float = 0.12         # Delay after each move for camera to settle.
    # Sensitivity calibration: measure px-per-driver-unit ratio for one-shot aiming.
    # 0 = auto-calibrate on first detection. Set >0 to use a pre-measured ratio.
    pet_aim_pixels_per_unit: float = 0.0
    pet_aim_calibrate: bool = True             # Auto-calibrate when pet_aim_pixels_per_unit == 0.
    pet_aim_calib_step: int = 200              # Mouse driver units for calibration move.
    # Runtime controls.


CONFIG = AppConfig()
