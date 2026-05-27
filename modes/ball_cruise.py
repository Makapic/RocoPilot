"""巡航+自动抓宠模式 — 继承模式3全部战斗能力，非战斗时启动SIFT巡航系统。"""
import os
import subprocess
import sys
from typing import Optional

from core.util import _ts
from modes.ball_pet import AutoBallPetMode
from modes.base import BattleEvent

# 与巡航子进程的协调标志文件
_CRUISE_PAUSE_FLAG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "luoke_location_src", "out", "cruise_pause.flag"
)


class AutoCruiseMode(AutoBallPetMode):
    """巡航+自动抓宠：启动SIFT巡航进程（独立tkinter悬浮窗），在框选区域内蛇形巡航并抓宠。

    首次进入非战斗状态时启动巡航子进程（Popen非阻塞），
    主进程继续运行引擎循环处理战斗逃跑。
    遇到战斗时通知巡航子进程暂停移动。
    """

    label = "自动巡航+抓宠"

    def __init__(self) -> None:
        super().__init__()
        self._cruise_launched = False
        self._cruise_process: Optional[subprocess.Popen] = None
        self._cruise_paused = False

    @property
    def name(self) -> str:
        return "auto_cruise"

    # ── 阻止 Engine 在主进程预加载 PetDetector ─────────────────────
    # 巡航由独立子进程执行，子进程自行加载 PetDetector。
    # 主进程不加载，避免 GPU 显存双倍占用。

    def _get_detector(self):
        return None

    # ── 非战斗回调 ────────────────────────────────────────────────

    def on_non_battle_no_action(self, event: BattleEvent) -> None:
        if self._cruise_launched:
            # 巡航已启动，检查子进程是否还活着
            if self._cruise_process is not None:
                poll = self._cruise_process.poll()
                if poll is not None:
                    print(f"[{_ts()}] 巡航子进程已退出 (code={poll})")
                    self._cruise_launched = False
                    self._cruise_paused = False
            return
        self._cruise_launched = True
        self._launch_cruise()

    # ── 战斗回调：标记文件通知巡航子进程暂停/恢复 ──────────────────

    def on_battle_start(self, event: BattleEvent) -> None:
        self._set_cruise_pause(True)
        super().on_battle_start(event)

    def on_battle_end(self, event: BattleEvent) -> None:
        super().on_battle_end(event)
        self._set_cruise_pause(False)

    def _set_cruise_pause(self, pause: bool) -> None:
        """通过标志文件通知巡航子进程暂停/恢复。"""
        self._cruise_paused = pause
        try:
            if pause:
                os.makedirs(os.path.dirname(_CRUISE_PAUSE_FLAG), exist_ok=True)
                with open(_CRUISE_PAUSE_FLAG, 'w') as f:
                    f.write('1')
            else:
                if os.path.exists(_CRUISE_PAUSE_FLAG):
                    os.remove(_CRUISE_PAUSE_FLAG)
        except Exception as e:
            print(f"[{_ts()}] 巡航暂停标志操作失败: {e}")

    # ── 巡航启动 ────────────────────────────────────────────────────

    def _find_cruise_script(self) -> Optional[str]:
        """查找 cruise_main.py 的路径（相对于项目根目录）。"""
        auto_roco_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        candidates = [
            os.path.join(auto_roco_dir, "luoke_location_src", "cruise_main.py"),
        ]

        for p in candidates:
            norm = os.path.normpath(p)
            if os.path.exists(norm):
                return norm
        return None

    def _find_python(self) -> str:
        """优先返回项目 .venv 的 Python，确保依赖完整。"""
        auto_roco_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        venv_python = os.path.join(auto_roco_dir, ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python):
            return venv_python
        return sys.executable

    def _launch_cruise(self) -> None:
        """启动巡航+抓宠独立进程（Popen非阻塞，主进程继续处理战斗）。"""
        # 清理可能残留的暂停标志（上次异常退出遗留）
        self._set_cruise_pause(False)

        # 将用户选择的精灵模型传递给子进程
        from config import CONFIG
        pet_model = CONFIG.pet_model_name

        if getattr(sys, "frozen", False):
            # Frozen: launch self as subprocess with --cruise flag
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            cmd = [sys.executable, "--cruise", "--pet-model", pet_model]
            cwd = exe_dir
            print(f"[{_ts()}] 启动巡航系统 (frozen): {sys.executable} --cruise --pet-model {pet_model}")
        else:
            cruise_script = self._find_cruise_script()
            if cruise_script is None:
                print(f"[{_ts()}] 错误：未找到 cruise_main.py")
                return
            python_exe = self._find_python()
            cmd = [python_exe, cruise_script, "--pet-model", pet_model]
            cwd = os.path.dirname(cruise_script)
            print(f"[{_ts()}] 启动巡航系统: {python_exe} {cruise_script} --pet-model {pet_model}")

        try:
            self._cruise_process = subprocess.Popen(cmd, cwd=cwd)
        except FileNotFoundError:
            print(f"[{_ts()}] 错误：找不到可执行文件 {cmd[0]}")
        except Exception as e:
            print(f"[{_ts()}] 启动巡航失败: {e}")
