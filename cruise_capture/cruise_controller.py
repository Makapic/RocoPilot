"""巡航路径生成 + 移动状态机 + interception 底层控制。"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import interception


# ── 参数 ─────────────────────────────────────────────────────────────
MOUSE_DX_PER_DEGREE = 4.0        # interception 鼠标横移 1 像素 ≈ 多少度旋转
ARRIVAL_RADIUS = 45.0            # 到达路径点判定距离（地图像素）
POSITION_TOLERANCE = 50.0        # 位置允许误差
HEADING_TOLERANCE = 25.0         # 朝向允许误差（度）
STUCK_CHECK_INTERVAL_S = 1.0     # 卡住检测间隔
STUCK_MIN_DISTANCE = 5.0         # 卡住判定最小位移（地图像素）
STUCK_TRIGGER_COUNT = 3          # 连续判定卡住次数触发脱困
TURN_EASE_MIN = 8                # 转向时最小移动量（避免过小不生效）
JUMP_INTERVAL_S = 2.8            # 跳跃冲刺间隔
W_RELEASE_INTERVAL_S = 2.0         # W 键完全释放间隔（给主进程检测战斗窗口）
W_RELEASE_DURATION_S = 0.3         # W 键释放持续时间
SCAN_COUNT = 4                      # 扫描方向数
SCAN_TURN_DEGREES = 90            # 每次转向角度（相对旋转）
SCAN_TIME_PER_DIRECTION = 2.0     # 每个方向停留秒数


def normalize_angle(angle: float) -> float:
    """将角度归一化到 [-180, 180)。"""
    a = angle % 360.0
    if a >= 180.0:
        a -= 360.0
    return a


def target_heading(current_x: float, current_y: float,
                   target_x: float, target_y: float) -> float:
    """从当前位置到目标位置的地图朝向角（度），0=上，90=右。"""
    dx = target_x - current_x
    dy = target_y - current_y
    return math.degrees(math.atan2(dx, -dy)) % 360.0


@dataclass
class CruiseArea:
    x1: int
    y1: int
    x2: int
    y2: int


def generate_zigzag_waypoints(area: CruiseArea, spacing: int = 150) -> list[tuple[int, int]]:
    """在矩形区域内生成 Z 字形路径点，确保覆盖完整边界并留出余量防止越界。"""
    x1, y1, x2, y2 = area.x1, area.y1, area.x2, area.y2
    if x1 > x2:
        x1, x2 = x2, x1
    if y1 > y2:
        y1, y2 = y2, y1

    # 向内收缩余量，防止角色动量导致越界
    margin = int(ARRIVAL_RADIUS * 2)
    dx = x2 - x1
    dy = y2 - y1
    if dx < margin * 2 or dy < margin * 2:
        margin = 0  # 区域太小则不收缩
    x1_in = x1 + margin
    x2_in = x2 - margin
    y1_in = y1 + margin
    y2_in = y2 - margin

    waypoints: list[tuple[int, int]] = []
    direction = 1
    y = y1_in
    while True:
        # 判断是否为最后一行，确保 Y 边界到达 y2_in
        is_last_row = (y + spacing > y2_in)
        row_y = y2_in if is_last_row else y

        # X 方向取点：确保首尾端点分别触碰 x1_in 和 x2_in
        xs = list(range(x1_in, x2_in + 1, spacing))
        if not xs:
            xs = [x1_in]
        if xs[0] != x1_in:
            xs.insert(0, x1_in)
        if xs[-1] != x2_in:
            xs.append(x2_in)

        if direction == -1:
            xs = list(reversed(xs))
        for x in xs:
            waypoints.append((x, row_y))

        if is_last_row:
            break
        direction *= -1
        y += spacing

    return waypoints


class CruiseState(Enum):
    IDLE = auto()
    TURNING = auto()
    MOVING = auto()
    SCANNING = auto()
    UNSTUCK = auto()


class CruiseController:
    """巡航控制器：路径生成 + 状态机 + 移动执行。"""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.state = CruiseState.IDLE
        self.waypoints: list[tuple[int, int]] = []
        self.current_waypoint_idx = 0
        self.cruise_area: Optional[CruiseArea] = None

        # 位置历史，用于估计朝向和检测卡住
        self._pos_history: list[tuple[float, float, float]] = []  # (x, y, t)
        self._stuck_count = 0
        self._last_jump_time = 0.0
        self._estimated_heading: Optional[float] = None  # 从位移估计的当前朝向

        # 移动状态
        self._w_down = False
        self._w_last_pulse = 0.0
        self._last_stuck_check_pos: Optional[tuple[float, float]] = None
        self._last_stuck_check_time = 0.0
        self._last_turn_time = 0.0

        # 扫描状态
        self._scan_dir_idx = 0
        self._scan_start_time = 0.0

    # ── 路径管理 ────────────────────────────────────────────────────

    def set_cruise_area(self, area: CruiseArea, spacing: int = 150):
        self.cruise_area = area
        self.waypoints = generate_zigzag_waypoints(area, spacing)
        self.current_waypoint_idx = 0
        print(f"[Cruise] 巡航区域: ({area.x1},{area.y1}) → ({area.x2},{area.y2}), "
              f"路径点: {len(self.waypoints)} 个")

    def current_target(self) -> Optional[tuple[int, int]]:
        if not self.waypoints or self.current_waypoint_idx >= len(self.waypoints):
            return None
        return self.waypoints[self.current_waypoint_idx]

    # ── 位置更新（由主循环调用）────────────────────────────────────

    def update_position(self, x: float, y: float):
        """每帧调用，记录位置历史。"""
        now = time.perf_counter()
        self._pos_history.append((x, y, now))
        # 只保留最近 2 秒
        cutoff = now - 2.0
        while self._pos_history and self._pos_history[0][2] < cutoff:
            self._pos_history.pop(0)

        # 从位移估计朝向
        if len(self._pos_history) >= 2:
            h = self._estimate_heading_from_history()
            if h is not None:
                self._estimated_heading = h

    def _estimate_heading_from_history(self) -> Optional[float]:
        """从最近 0.3 秒内的位移估计朝向。"""
        now = time.perf_counter()
        recent = [(x, y) for x, y, t in self._pos_history if now - t < 0.3]
        if len(recent) < 2:
            return None
        x1, y1 = recent[0]
        x2, y2 = recent[-1]
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 3.0:
            return None
        return math.degrees(math.atan2(dx, -dy)) % 360.0

    # ── 状态机（每帧调用）──────────────────────────────────────────

    def tick(self) -> None:
        """主循环每帧调用（约 50ms 间隔）。"""
        target = self.current_target()
        if target is None:
            self._release_all()
            self.state = CruiseState.IDLE
            return

        if not self._pos_history:
            return

        cur_x, cur_y, _ = self._pos_history[-1]
        tx, ty = target

        if self.state == CruiseState.IDLE:
            self._start_moving_to(cur_x, cur_y, tx, ty)

        elif self.state == CruiseState.TURNING:
            # 等待位移产生朝向估计，然后修正
            now = time.perf_counter()
            if self._estimated_heading is not None and now - self._last_turn_time > 0.6:
                desired = target_heading(cur_x, cur_y, tx, ty)
                err = abs(normalize_angle(desired - self._estimated_heading))
                if err < HEADING_TOLERANCE:
                    self.state = CruiseState.MOVING
                    self._last_stuck_check_pos = (cur_x, cur_y)
                    self._last_stuck_check_time = now
                else:
                    print(f"[Cruise] TURNING 修正: error={err:.1f}°")
                    self._release_forward()
                    time.sleep(0.05)
                    self._turn_toward(cur_x, cur_y, tx, ty)
                    time.sleep(0.05)
                    self._start_forward()
                    self._last_turn_time = now
            elif self._estimated_heading is None and now - self._last_turn_time > 2.0:
                # 2 秒后仍无朝向估计（可能卡墙）→ 随机转向试探
                print("[Cruise] TURNING 超时无朝向，随机转向试探")
                self._release_forward()
                time.sleep(0.05)
                self._turn_by_degrees(random.choice([90, -90, 135, -135]))
                time.sleep(0.05)
                self._start_forward()
                self._last_turn_time = now

        elif self.state == CruiseState.MOVING:
            dist = math.hypot(cur_x - tx, cur_y - ty)
            if dist < ARRIVAL_RADIUS:
                self._on_arrived()
                return

            # 每 2 秒完全释放 W 300ms，确保主进程能截到无 W 干扰的战斗 UI
            now = time.perf_counter()
            if self._w_down and now - self._w_last_pulse > W_RELEASE_INTERVAL_S:
                interception.key_up('w')
                time.sleep(W_RELEASE_DURATION_S)
                interception.key_down('w')
                self._w_last_pulse = now

            self._check_stuck_and_handle(cur_x, cur_y)
            self._maintain_heading(cur_x, cur_y, tx, ty)

        elif self.state == CruiseState.SCANNING:
            self._do_scan_tick()

        elif self.state == CruiseState.UNSTUCK:
            # 脱困动作进行中
            pass

    # ── 转向 ────────────────────────────────────────────────────────

    def _turn_by_degrees(self, degrees: float):
        """按住右键拖动鼠标旋转指定角度。正=右转，负=左转。"""
        dx = int(degrees * MOUSE_DX_PER_DEGREE)
        if abs(dx) < TURN_EASE_MIN:
            dx = TURN_EASE_MIN if dx >= 0 else -TURN_EASE_MIN

        # 缓动曲线：小角度不加缓动，大角度加
        abs_dx = abs(dx)
        if abs_dx > 40:
            # 减速接近目标
            dx = int(math.copysign(abs_dx * 0.8, dx))

        interception.mouse_down('right')
        time.sleep(0.02)
        interception.move_relative(dx, 0)
        time.sleep(0.05 + abs_dx * 0.001)
        interception.mouse_up('right')
        time.sleep(0.05)

        # 转向后朝向估计已失效，清空历史等待新位移数据
        # 扫描状态下不清除：4×90°=360° 回到原朝向，历史数据仍然有效
        # 若清除会导致扫描完成后无法获得朝向，卡在 TURNING 的 2 秒超时循环
        if self.state != CruiseState.SCANNING:
            self._estimated_heading = None
            self._pos_history.clear()

    def _turn_toward(self, cur_x: float, cur_y: float, tx: float, ty: float):
        """转向目标方向。需要已知当前朝向。"""
        if self._estimated_heading is None:
            return  # 朝向未知，无法计算转向量
        desired = target_heading(cur_x, cur_y, tx, ty)
        err = normalize_angle(desired - self._estimated_heading)

        if abs(err) < HEADING_TOLERANCE * 0.5:
            return

        print(f"[Cruise] 转向: error={err:.1f}°")
        self._turn_by_degrees(err)

    def _maintain_heading(self, cur_x: float, cur_y: float, tx: float, ty: float):
        """移动中持续微调朝向。"""
        if self._estimated_heading is None:
            return
        now = time.perf_counter()
        if now - self._last_turn_time < 0.5:
            return  # 刚转过，等位移积累
        desired = target_heading(cur_x, cur_y, tx, ty)
        err = normalize_angle(desired - self._estimated_heading)
        if abs(err) > HEADING_TOLERANCE * 1.5:
            self._release_forward()
            time.sleep(0.05)
            self._turn_toward(cur_x, cur_y, tx, ty)
            time.sleep(0.05)
            self._start_forward()
            self._last_turn_time = now

    # ── 前进 / 停止 ─────────────────────────────────────────────────

    def _start_forward(self):
        if not self._w_down:
            interception.key_down('w')
            self._w_down = True

    def _release_forward(self):
        if self._w_down:
            interception.key_up('w')
            self._w_down = False

    def _release_all(self):
        self._release_forward()

    def _start_moving_to(self, cur_x: float, cur_y: float, tx: float, ty: float):
        """开始向目标移动：先前进获取朝向，再在 TURNING 中修正。"""
        print(f"[Cruise] 前往路径点: ({tx},{ty})")
        self._start_forward()
        self.state = CruiseState.TURNING
        self._last_stuck_check_pos = (cur_x, cur_y)
        self._last_stuck_check_time = time.perf_counter()
        self._last_turn_time = time.perf_counter()

    # ── 到达 ────────────────────────────────────────────────────────

    def _on_arrived(self):
        """到达当前路径点。"""
        self._release_forward()
        target = self.current_target()
        print(f"[Cruise] 到达路径点 {self.current_waypoint_idx + 1}/{len(self.waypoints)}: {target}")
        self.state = CruiseState.SCANNING
        self._scan_dir_idx = 0
        self._scan_start_time = time.perf_counter()

    # ── 扫描抓宠 ────────────────────────────────────────────────────

    def _do_scan_tick(self):
        """扫描状态下的每帧动作。相对旋转 SCAN_TURN_DEGREES 度后停留。"""
        now = time.perf_counter()
        elapsed = now - self._scan_start_time

        if self._scan_dir_idx >= SCAN_COUNT:
            # 扫描完成，前进到下一个路径点
            self.current_waypoint_idx += 1
            if self.current_waypoint_idx >= len(self.waypoints):
                self.waypoints.reverse()
                self.current_waypoint_idx = 0
                print(f"[Cruise] 巡航完成！反向继续循环 ({len(self.waypoints)} 个路径点)")
                self.state = CruiseState.IDLE
                return
            self.state = CruiseState.IDLE
            return

        # 进入该方向时先旋转（第一个方向不转，保持朝向）
        if elapsed < 0.3:
            if self._scan_dir_idx > 0:
                self._turn_by_degrees(SCAN_TURN_DEGREES)
        elif elapsed >= SCAN_TIME_PER_DIRECTION + 0.3:
            # 该方向扫描完成，转下一个
            self._scan_dir_idx += 1
            self._scan_start_time = now

    # ── 卡住检测 ────────────────────────────────────────────────────

    def _check_stuck_and_handle(self, cur_x: float, cur_y: float):
        """检测并处理卡住。"""
        now = time.perf_counter()
        if self._last_stuck_check_pos is None:
            self._last_stuck_check_pos = (cur_x, cur_y)
            self._last_stuck_check_time = now
            return

        if now - self._last_stuck_check_time < STUCK_CHECK_INTERVAL_S:
            return

        dist = math.hypot(cur_x - self._last_stuck_check_pos[0],
                          cur_y - self._last_stuck_check_pos[1])
        if dist < STUCK_MIN_DISTANCE:
            self._stuck_count += 1
            if self._stuck_count >= STUCK_TRIGGER_COUNT:
                print(f"[Cruise] 卡住检测！启动脱困")
                self._do_unstuck()
                self._stuck_count = 0
        else:
            self._stuck_count = max(0, self._stuck_count - 1)

        self._last_stuck_check_pos = (cur_x, cur_y)
        self._last_stuck_check_time = now

    def _do_unstuck(self):
        """脱困：随机转向后继续前进（不按 S/W 避免误触骑宠/跳跃）。"""
        self._release_forward()
        prev_state = self.state
        self.state = CruiseState.UNSTUCK

        # 随机转向 90~180 度
        turn_deg = random.choice([90, -90, 135, -135, 180])
        print(f"[Cruise] 脱困转向: {turn_deg}°")
        self._turn_by_degrees(turn_deg)
        time.sleep(0.1)

        # 恢复前进
        self._start_forward()

        self._stuck_count = 0
        self._last_turn_time = time.perf_counter()
        self.state = prev_state

