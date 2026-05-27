# 洛克王国世界地图定位助手

原项目：[761696148/Game-Map-Tracker](https://github.com/761696148/Game-Map-Tracker) — 上游同时提供 **SIFT** 与 **LoFTR（AI）** 两种跟点思路。

**本仓库在实际使用中仅维护、推荐 SIFT 方案。** 工程里虽仍保留上游的 `main_ai.py` 等文件，但 **AI（LoFTR）路线实测效果并不好**，不作为本分支的使用重点，下文**只说明如何运行 SIFT**。

---
## 欢迎测试反馈问题
现在并没有做所有场景的充分测试，实测中**草地、海面等小地图纯色区域**还无法实现追踪，会出现失去追踪的问题。大家如果在使用过程中遇到场景无法追踪的情况，欢迎截图在issue中进行反馈。

## `out` 目录与大地图数据引用

仓库 **`out`** 内用于逻辑匹配、悬浮窗显示的**大地图相关图片等数据**，在整理与制作时参考了哔哩哔哩游戏 WIKI（洛克王国世界）公开词条：

- [大地图 · 洛克王国世界 WIKI（哔哩游戏）](https://wiki.biligame.com/rocom/%E5%A4%A7%E5%9C%B0%E5%9B%BE)

实际落盘文件（如 `rocom_base_z8.png`、`rocom_caiji_overlay.png` 及锚点缓存等）可能经缩放、叠加标注或工具链处理，**不等同于** WIKI 页面原始文件。使用与二次分发时，请遵守游戏官方、WIKI 及素材各自的版权与许可约定。

---

## 与 `Game-Map-Tracker-main` 的差异（改进说明）

**逻辑图与锚点**
- 大地图锚点支持 **`try_load_sift_anchors` / `save_sift_anchors`** 写入 `out` 下 **`.npz` 缓存**，避免每次启动全量重提；并可配置 **`SIFT_MAP_NFEATURES`** 上限（上游为单次 `SIFT_create()` 全图提点、无缓存）。

**匹配与搜索范围**

- 上游每帧 **`knnMatch` 对全图描述子**；本分支在**有上一帧位置且未进入「强制全图」条件**时，只在 **`SIFT_LOCAL_SEARCH_RADIUS`** 定义的方形邻域内选取锚点；邻域内点过多时用 **`SIFT_LOCAL_MAX_ANCHORS`** 随机子采样；过少则**退回全图**（`SIFT_LOCAL_MIN_ANCHORS`）。
- 训练侧描述子数量**低于 `SIFT_USE_BF_BELOW`** 时使用 **BFMatcher**，否则 **FLANN**；FLANN 的 **`checks`** 可配置（上游固定为 `50`）。

**小地图（查询图）SIFT**

- 上游对截屏灰度图**原尺寸**、矩形区域提特征；本分支支持 **`SIFT_QUERY_MAX_EDGE`** 降采样、**`SIFT_QUERY_NFEATURES`**、**内接椭圆掩膜**（`SIFT_MINIMAP_*`）仅在圆内提点。

**运行方式与线程**

- 入口改为 **`screen_pick.run_with_screen_pick`**：支持倒计时与**全屏框选小地图**（上游为直接 `tk.Tk()` + 固定 `config.MINIMAP`）。
- 跟踪主体可在**后台线程**执行（`SIFT_TRACK_IN_BACKGROUND`），主线程只更新 UI；**`mss` 使用 `threading.local()` 每线程一个实例**（上游在主线程同步截屏与计算）。

---

## 使用说明

### 方式一：使用 exe 运行（推荐，免装 Python）

本仓库中的 **`exe_files`** 文件夹已包含：

- **`SIFT_Map_Tracker.exe`** — 跟点程序
- **`out/`** — 运行所需依赖（逻辑底图、显示大地图、锚点缓存等）

**使用步骤：**

1. **下载或克隆本完整工程**，进入 **`exe_files`** 目录。
2. **保持目录结构不变**：`SIFT_Map_Tracker.exe` 与 **`out`** 文件夹须在同一级，不要只拷贝 exe、不要挪动 `out` 内文件相对位置。
3. 双击 **`SIFT_Map_Tracker.exe`** 启动；首次使用同样可在倒计时后**框选**游戏小地图区域。

程序从 **exe 所在目录** 读取同级 **`out`**。该 exe 仅包含 SIFT 依赖，**不能**用于运行 AI 模式。

```text
exe_files/
├── SIFT_Map_Tracker.exe
└── out/
    ├── rocom_base_z8.png
    ├── rocom_caiji_overlay.png
    └── sift_anchors_rocom_base_z8.npz   # 等，以仓库内实际文件为准
```

---

### 方式二：用 Python 运行（开发 / 调试）

1. 安装 **Python 3.8+**，进入本仓库**根目录**（与 `main_sift.py` 同级）。
2. 建议新建虚拟环境，仅安装 SIFT 所需依赖：

   ```bash
   pip install -r requirements-main_sift.txt
   ```

3. 使用项目根目录下的 **`out`**（与源码中的 `config.py` 路径一致；若你本地只在 `exe_files/out` 有资源，可复制或链接到根目录 `out`）。
4. 启动：

   ```bash
   python main_sift.py
   ```

5. 首次使用建议在倒计时结束后**全屏框选**游戏小地图区域；若使用命令行 **`--no-pick`**，则使用 `config.py` 里预先写好的 `MINIMAP` 坐标。
6. 主要参数在 **`config.py`**（刷新间隔、局部搜索半径、是否写性能日志等）。

---

## 图示说明（`examp_figs/`）

### 图 1：游戏分辨率

请在游戏设置中使用**与本工具测试时一致的游戏分辨率**（见下图示意）。**其他分辨率未做测试**，小地图在屏幕上的位置与尺寸可能变化，截屏框选区域与 `config.MINIMAP` 需自行重新校准，效果不保证。

![游戏分辨率设置示意](examp_figs/fig_1.png)

### 图 2：框选小地图区域

使用 **exe** 或 **`python main_sift.py`** 启动后，倒计时结束会进入**全屏框选**：用鼠标拖拽框住游戏中的**小地图区域**（见下图示意）。该区域即后续截屏用于 SIFT 的区域。

![框选小地图区域示意](examp_figs/fig_2.png)

### 图 3：运行中的追踪效果

正常跟点后的**悬浮窗大地图与位置标记**效果示意（见下图）。若长期「Searching」或漂移，请检查分辨率、小地图是否被 UI 遮挡，并参考 `config.py` 与分段耗时日志。

![追踪效果示意](examp_figs/fig_3.png)

---

## 关于 AI 模式（`main_ai.py`）

上游仓库包含基于 LoFTR 的 **`main_ai.py`**。在本工程实际测试中 **AI 方案效果并不理想**，因此 README **不提供** AI 环境的安装与运行步骤；若需研究，请自行参考原仓库与 `requirements.txt` 中的 PyTorch 等依赖。

---

## 致谢

核心思路与仓库结构来自 [Game-Map-Tracker](https://github.com/761696148/Game-Map-Tracker)；二次分发时请遵守上游许可（若原仓库指定许可证，以原仓库为准）。
