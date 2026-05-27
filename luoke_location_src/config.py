# ==========================================
# 游戏地图跟点助手 - 全局配置文件
# ==========================================
import os
import sys


def _runtime_base_dir() -> str:
    """源码运行取当前文件目录；打包运行优先取 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_out_dir() -> str:
    base = _runtime_base_dir()
    candidate = os.path.join(base, "out")
    if os.path.isdir(candidate):
        return candidate

    # 兼容 onefile 提取到临时目录、但资源放在 exe 同级目录的情况。
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        exe_candidate = os.path.join(exe_dir, "out")
        if os.path.isdir(exe_candidate):
            return exe_candidate

    return candidate


_BASE = _runtime_base_dir()
_OUT = _resolve_out_dir()
# --- 1. 屏幕截图区域 (Minimap Region) ---
# 正常启动会先倒计时再全屏框选小地图；仅在使用命令行 --no-pick 时才用下方 MINIMAP 数值
PICK_SCREEN_COUNTDOWN_SEC = 5
# 请根据你的显示器分辨率和游戏 UI 调整这些值（或通过框选自动得到）
MINIMAP = {
    "top": 292,
    "left": 1853,
    "width": 150,
    "height": 150
}

# --- 2. 悬浮窗 UI 设置 ---
WINDOW_GEOMETRY = "400x400+50+150"  # 悬浮窗宽x高（X/Y 由 cruise_main 根据小地图位置自动计算）
VIEW_SIZE = 400                       # 悬浮窗画布边长（固定）
# 以角色为中心在大图上裁剪的半宽（像素），再缩放到 VIEW_SIZE；默认=VIEW_SIZE 约为原先 VIEW_SIZE/2 的 2 倍视野
VIEW_MAP_HALF_SIZE = 400

# --- 3. 地图文件路径（须同宽同高）---
# 搜索 / 特征匹配用底图
LOGIC_MAP_PATH = os.path.join(_OUT, "rocom_poi_overlay.png")
# 悬浮窗显示用（采集点等 overlay）
DISPLAY_MAP_PATH = os.path.join(_OUT, "rocom_caiji_overlay.png")
# 可选：与逻辑图同尺寸的灰度掩膜，白=有地图、黑=忽略（可与 alpha 同时使用取交集）
LOGIC_MAP_MASK_PATH = None
# 逻辑图为带 alpha 的 PNG 时：透明度低于此值的像素不参与 SIFT（0～255）
SIFT_MASK_ALPHA_THRESHOLD = 16
# 将有效区向内收缩像素，减少贴地图边缘的无效特征；0 关闭
SIFT_MASK_EDGE_SHRINK = 2
# 锚点缓存路径；True 时自动为 out/sift_anchors_<逻辑图文件名>.npz
SIFT_ANCHORS_AUTO_NAME = True
SIFT_ANCHORS_PATH = os.path.join(_OUT, "sift_anchors.npz")

# --- 4. 惯性导航设置 (防跟丢兜底) ---
MAX_LOST_FRAMES = 80                  # 增加惯性容忍帧数，避免频繁丢锁重搜索

# ==========================================
# SIFT 传统视觉算法专属配置 (main_sift.py)
# ==========================================
SIFT_REFRESH_RATE = 50                # 毫秒；稍放慢以匹配实际帧耗时（20fps）
SIFT_CLAHE_LIMIT = 3.0                # CLAHE 对比度增强极限 (用于榨取海水/草地纹理)
SIFT_MATCH_RATIO = 0.76               # 收紧比值测试，减少误匹配导致的定位漂移
SIFT_MIN_MATCH_COUNT = 6              # 判定成功所需的最低匹配点数
SIFT_RANSAC_THRESHOLD = 8.0           # 收紧RANSAC阈值，提高几何一致性要求
# 大地图 SIFT 最大锚点数（0=不限制）。锚点越多全图 FLANN 越慢；改后需删缓存重算 sift_anchors_*.npz
SIFT_MAP_NFEATURES = 120000
# 小地图侧 SIFT 上限（只影响截屏图，不影响大地图精度）；300～400 常能明显提速
SIFT_QUERY_NFEATURES = 400            # 回归适中的查询特征数
# 小地图长边降采样；0 = 全分辨率（更准、更慢）；192～224 可再省一截小图 SIFT 时间
SIFT_QUERY_MAX_EDGE = 224             # 回归原始值
# 截屏为方形、游戏内小地图为圆：仅在「内接椭圆」内提 SIFT，忽略四角场景/UI，减计算与误匹配
SIFT_MINIMAP_USE_INSCRIBED_ELLIPSE = True
# 椭圆半轴 = 矩形半宽/半高 × 该系数（1.0 为贴边内接；略小于 1 可向内收一点）
SIFT_MINIMAP_ELLIPSE_SCALE = 0.98
# 从小地图中心额外挖掉一小块，尽量忽略角色箭头/朝向扇形等动态 UI
SIFT_MINIMAP_CENTER_EXCLUDE_RADIUS_RATIO = 0.17
# 稳态跟点：在上一帧地图坐标为中心、边长 2×半径 的正方形内取锚点做匹配（大图原始像素）。
# 无上一帧、或连续未匹配达到 SIFT_FORCE_FULLMAP_LOST_FRAMES 时走全图锚点，不使用本半径。
# 连续运动时帧间位移有限，不必过大；过大徒增 FLANN 负担。若常退回全图可把半径略调大。
SIFT_LOCAL_SEARCH_RADIUS = 600        # 扩大局部搜索半径，覆盖更远移动
SIFT_LOCAL_RADIUS_GROW_PER_LOST_FRAME = 28
SIFT_LOCAL_SEARCH_MAX_RADIUS = 760
SIFT_LOCAL_MIN_ANCHORS = 500
# 局部模式下半径内锚点过多时随机子采样到此上限（0=不限制）。密集区 FLANN 仍可能较慢，建议 8000～15000
SIFT_LOCAL_MAX_ANCHORS = 8000         # 降低局部锚点上限，加快FLANN
# 非全图重定位时，若本帧结果相对上一帧跳跃过大则直接拒绝，避免跨河/纯色区域横跳
SIFT_LOCAL_MAX_JUMP = 100.0          # 收紧跳跃限制，防止误匹配导致定位跳到错误区域
SIFT_LOCAL_JUMP_PER_LOST_FRAME = 18.0
# 单应矩阵内点约束：好匹配点虽多，但若真正支持同一几何关系的点太少，也视为不可靠
SIFT_MIN_INLIER_COUNT = 6
SIFT_MIN_INLIER_RATIO = 0.42         # 提高内点率要求，过滤假匹配
# FLANN 搜索精度/速度：checks 越小越快、略易漏匹配；可试 18～24
SIFT_FLANN_CHECKS = 22
SIFT_USE_BF_BELOW = 3500
# --- 传送 / 大地图 UI：小地图暂时消失后的重定位 ---
# 连续若干帧未匹配后，强制用全图锚点做 FLANN（不再以「旧坐标」为中心做局部匹配，避免传送后错配漂移）
SIFT_FORCE_FULLMAP_LOST_FRAMES = 10
# 传送时小地图会短暂全黑：检测到连续黑屏后，黑屏结束的第一帧直接触发全局重定位
SIFT_TELEPORT_BLACKOUT_MIN_FRAMES = 2
SIFT_TELEPORT_BLACKOUT_MAX_MEAN = 8.0
SIFT_TELEPORT_BLACKOUT_MAX_STD = 8.0
SIFT_TELEPORT_BLACKOUT_MAX_BRIGHT_RATIO = 0.012
# 非传送但小地图长期被 UI 遮挡时：低特征帧持续一段时间后暂停计丢失；遮挡解除后立即强制全局重定位
SIFT_UI_OCCLUDE_MAX_KP = 4
SIFT_UI_OCCLUDE_MIN_FRAMES = 8
SIFT_UI_OCCLUDE_RESUME_MIN_KP = 10
# 连续未匹配超过此帧数则清空 last 坐标（不再显示惯性黄点），直到重新全局锁定
SIFT_CLEAR_LOCK_AFTER_LOST_FRAMES = 45
# 小地图 SIFT 点数低于此视为被 UI 遮挡/非游戏小地图，本帧不参与匹配
SIFT_MINIMAP_MIN_KP = 8
# 在「无可靠上一帧」或强制全图时，最低好匹配点数 = SIFT_MIN_MATCH_COUNT + 此项（抑制错配）
SIFT_RELOC_EXTRA_MIN_MATCH = 5
# SIFT 弱纹理失效时，在上一帧附近做局部模板匹配兜底，帮助草地/宽河面保持连续定位
SIFT_TEMPLATE_FALLBACK = False         # 关闭模板匹配兜底，依赖惯性和局部扩大搜索
SIFT_TEMPLATE_RADIUS = 230.0
SIFT_TEMPLATE_RADIUS_GROW_PER_LOST_FRAME = 32.0
SIFT_TEMPLATE_MAX_RADIUS = 620.0
SIFT_TEMPLATE_MIN_SCORE = 0.79
SIFT_TEMPLATE_MIN_DELTA = 0.010
SIFT_TEMPLATE_LOCAL_SCALE = 0.65       # 提高粗匹配缩放，减少搜索区
SIFT_TEMPLATE_LOCAL_ANGLE_SPAN = 30.0
SIFT_TEMPLATE_LOCAL_ANGLE_STEP = 10.0
SIFT_TEMPLATE_GLOBAL_SCALE = 0.14
SIFT_TEMPLATE_GLOBAL_MIN_SCORE = 0.73
SIFT_TEMPLATE_GLOBAL_MIN_DELTA = 0.006
SIFT_TEMPLATE_GLOBAL_ANGLE_SPAN = 180.0
SIFT_TEMPLATE_GLOBAL_ANGLE_STEP = 15.0
SIFT_TEMPLATE_GLOBAL_ANGLE_COARSE_STEP = 30.0
SIFT_TEMPLATE_REFINE_MARGIN = 128
SIFT_TEMPLATE_REFINE_ANGLE_SPAN = 4.0  # 减少精匹配角度数
SIFT_TEMPLATE_REFINE_ANGLE_STEP = 3.0  # 从 2° 放宽到 3°，精匹配角度减半
SIFT_TEMPLATE_PEAK_SUPPRESS_RADIUS = 18
SIFT_TEMPLATE_JUMP_SCALE = 1.35
SIFT_TEMPLATE_MIN_MASK_PIXELS = 80
# 在悬浮窗画面右上角显示跟踪更新帧率（按相邻两次跟踪完成间隔估算，EMA 平滑）
SIFT_SHOW_FPS = True
# True 时记录 _run_tracking_core 各段耗时(ms)。为 False 时不会写文件、也不计时输出
SIFT_TRACK_PROFILE = True
# 每完成多少次跟踪再写一行（第 1 次跟踪总会写一行，便于确认文件生效）
SIFT_TRACK_PROFILE_EVERY = 25
# 计时行追加写入此 txt（UTF-8）；None 或空字符串表示不写文件
SIFT_TRACK_PROFILE_LOG_PATH = os.path.join(_OUT, "sift_track_profile.txt")
# 是否同时打印到控制台
SIFT_TRACK_PROFILE_PRINT = True
# 显示插帧：跟踪仍按 SIFT_REFRESH_RATE；悬浮窗按此间隔重绘，用平滑后的视口中心跟点（减轻卡顿感）。0 = 关闭，与跟踪同频刷新
SIFT_DISPLAY_INTERP_MS = 33
# 显示中心向真实跟踪位置收敛的时间常数（秒），越小越跟手、略抖；越大越顺、略滞后
SIFT_DISPLAY_SMOOTH_TAU = 0.11
# 真位置与当前显示中心距离超过此像素（如传送）则直接对齐，避免拖影
SIFT_DISPLAY_TELEPORT_PX = 200.0

# ==========================================
# LoFTR AI 深度学习算法专属配置 (main_ai.py)
# ==========================================
AI_REFRESH_RATE = 200                 # AI 推理耗时较高，建议 200ms (5fps)
AI_CONFIDENCE_THRESHOLD = 0.25        # AI 置信度阈值 (越低越容易妥协)
AI_MIN_MATCH_COUNT = 6                # 判定成功所需的最低匹配点数
AI_RANSAC_THRESHOLD = 8.0             # 允许的空间误差阈值
# 雷达扫描参数
AI_SCAN_SIZE = 1600                   # 全局搜索时的区块大小
AI_SCAN_STEP = 1400                   # 全局搜索的步长
AI_TRACK_RADIUS = 500                 # 局部追踪时，向外扩展的半径 (400即截取800x800)