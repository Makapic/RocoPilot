# RocoPilot — 洛克王国世界自动化助手

> **输入方案**：基于 Interception 驱动级输入，在内核层面模拟键鼠，游戏反作弊无法检测。

基于 OpenCV 模板匹配 + YOLO 精灵检测的游戏自动化工具，专为《洛克王国：世界》设计。支持自动丢球、精灵定位瞄准、巡航抓宠，以及战斗中的自定义应对策略。

---

> 更新日志：[CHANGELOG.md](CHANGELOG.md)

---

## 运行环境

> 以下为实测可用的环境配置。其他相近版本（如 Windows 10、Python 3.11、CUDA 11.8）通常也能正常运行。

| 项目 | 实测配置 | 说明 |
|------|---------|------|
| 操作系统 | Windows 11 Pro 64-bit | Windows 10 亦可；依赖 pywin32，不支持 macOS/Linux |
| 权限 | **管理员权限** | Interception 驱动加载、截图 API 需要 |
| Python | 3.12.9（由 uv 管理） | 要求 3.11+，uv 自动下载，无需手动安装 |
| uv | 0.11.11 | 包管理器和 Python 版本管理器 |
| GPU | NVIDIA RTX 3060 Laptop | 驱动 581.95，CUDA 12.1；精灵检测和 OCR 需要 |
| 显存 | 6 GB | YOLO 模型约消耗 1-2 GB，巡航子进程额外占用 |
| 游戏分辨率 | 1920×1080 | 模板在该分辨率下截图，其他分辨率可自适应缩放 |

---

## 环境安装教程

以下步骤在 **Windows 11 管理员终端** 下操作，其他版本大同小异。

### 1. 安装 Interception 驱动

Interception 是内核级输入驱动，游戏无法感知模拟输入，**必须先装**。

1. 访问 [Interception Releases](https://github.com/oblitum/Interception/releases/tag/v1.0.1)
2. 下载 `Interception.zip` 并解压到任意目录
3. **以管理员身份**打开终端（`Win+X` → 终端(管理员)），进入解压目录
4. 运行命令：
   ```powershell
   .\install-interception.exe /install
   ```
5. 看到 `Success` 提示后，**重启电脑**
6. 重启后在终端运行以下命令验证：
   ```powershell
   sc query interception
   ```
   状态显示 `RUNNING` 即安装成功

### 2. 安装 uv（Python 包管理器）

uv 会自动下载和管理 Python，**无需手动安装 Python**。

以**普通用户身份**打开终端：

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装完成后**关闭并重新打开终端**，验证：

```powershell
uv --version
```

### 3. 克隆项目并安装依赖

```powershell
# 克隆到本地
git clone https://github.com/Makapic/RocoPilot.git
cd RocoPilot
```

```powershell
# 安装基础依赖（约 500 MB）
uv sync
```

> uv 会自动创建 `.venv` 虚拟环境并安装所有依赖。基础依赖包括 OpenCV、numpy、mss（截图）、pywin32、interception-python。

### 4. （可选）安装精灵检测依赖

模式 2/3 的 YOLO 精灵定位功能需要额外安装：

```powershell
uv sync --extra pet
```

这会安装 `ultralytics`、`torch`、`torchvision`。默认从 SJTU 镜像下载 CUDA 12.1 版 PyTorch，适合国内网络。

> **显卡要求**：NVIDIA 显卡（建议 4 GB 显存以上）。CPU 亦可运行但每帧检测会慢数倍。

### 5. 精灵检测模型

| 文件 | 说明 | 仓库包含 |
|------|------|----------|
| `models/xueren.pt` | 雪人精灵检测模型 | 是（20 MB），可直接使用 |
| `models/huolong.pt` | 火龙精灵检测模型 | 是（20 MB），可直接使用 |
| `models/geli.pt` | 和平鸽 + 菊华梨检测模型 | 是（20 MB），可直接使用 |
| `yolo26s.pt` | 预训练基础权重，用于训练新模型 | 是（20 MB） |

启动时程序会列出 `models/` 下所有 `.pt` 文件供选择。其他精灵需自行训练（见下方教程）。

### 6. 启动验证

```powershell
uv run main.py
```

看到模式选择菜单即环境配置成功。按 `Ctrl+C` 退出。

--。

---

## 运行模式

启动后提供三种模式可选：

| 按键 | 模式 | 说明 |
|------|------|------|
| `1` | 自动丢球 | 非战斗状态下检测可丢球画面自动点击 |
| `2` | 自动抓宠 | YOLO 检测精灵位置 → 自动瞄准 → 丢球；战斗中支持自定义策略 |
| `3` | 自动巡航 + 抓宠 | 继承模式 2 全部能力，非战斗时启动 SIFT 地图巡航系统 |

### 模式 1：自动丢球

- 仅在游戏窗口前台时触发，避免误操作
- 检测 `elf_P` / `exchange` 模板匹配分数，达到阈值才点击
- 适合大量精灵出没时挂机丢球

### 模式 2：自动丢球（精灵定位）

- 使用 YOLO 模型实时检测画面中的精灵位置
- 透明悬浮窗叠加显示检测框和准星
- 自动瞄准：按住右键旋转视角将精灵移至画面中心，然后丢球
- 支持灵敏度自动标定，也支持手动标定（`scripts/mark_align.py`）
- 一定时间未检测到精灵自动旋转视角搜索
- **战斗内行为可配置**：污染战斗和普通战斗分别设置策略

### 模式 3：自动巡航 + 抓宠

- 继承模式 2 的全部战斗和抓宠能力
- 非战斗时启动独立巡航子进程，在框选区域内蛇形巡航
- 遇敌时通过标志文件通知巡航暂停，战斗结束后恢复
- 巡航系统基于 SIFT 特征匹配实现地图定位和路径规划

---

## 战斗内策略

模式 2 和 3 支持在战斗中按污染/普通类型分别配置行为：

| 行为 | 说明 |
|------|------|
| 只聚能 | 每 1 秒按 `X` 聚能 |
| 逃跑 | 按 `ESC` → 识别并点击"是"按钮 |
| 释放技能1后聚能 | 先按 `1` 释放技能，后续按 `X` 聚能 |
| 不操作 | 不进行任何键鼠操作 |

配置自动保存到 `user_prefs.json`，下次启动无需重新设置。

### 其他自动化

- **同行自动确认**：非战斗状态下检测到队友重新同行请求时自动按 `F`
- **污染精灵日志**：每场污染战斗记录精灵名称到 `logs/pollute_log.csv`（需 EasyOCR，否则记录为"未知"）

---

## 精灵检测模型训练

仓库提供 **xueren（雪人）、huolong（火龙）、geli（和平鸽+菊华梨）** 的预训练模型。如需检测其他精灵，按以下流程自行训练。

### 数据准备

首先需要收集精灵的截图素材，有两种方式：

**A. 模板贴图（合成训练，快速上手）**

将精灵的透明 PNG 素材放入 `templates/pets/`，脚本会自动提取轮廓并贴到游戏背景上生成训练数据。适合精灵外观清晰、背景简单的场景。

**B. 真实截图标注（精度更高）**

1. 在游戏中截取大量包含目标精灵的画面，放入 `datasets/<精灵名>/`
2. 运行标注工具：
   ```powershell
   uv run python scripts/label_tool.py datasets/<精灵名>
   ```
   | 操作 | 按键 |
   |------|------|
   | 鼠标拖拽 | 画框 |
   | `0`-`9` | 选择类别 |
   | `W` | 确认当前框 |
   | `S` | 保存标签 |
   | `A` / `D` | 上一张 / 下一张 |
   | `Del` | 删除最后一个框 |
   | `Q` | 退出 |

3. 标注结果保存为 YOLO 格式：`datasets/<精灵名>/images/`（图片）+ `datasets/<精灵名>/labels/`（标签 `.txt`）

### 训练

```powershell
# 训练火龙模型（从已有 huolong.pt 继续微调，扩充数据后使用）
uv run python scripts/train_huolong.py

# 训练雪人模型（从已有 xueren.pt 继续微调）
uv run python scripts/train_xueren.py

# 训练 geli 双物种模型（从 yolo26s.pt 预训练权重开始）
uv run python scripts/train_geli.py
```

训练完成后模型自动复制到 `models/<精灵名>.pt`，启动 main.py 时即可选择。

> 如需训练其他精灵，可复制 `train_huolong.py` 并修改其中的数据集路径和模型名。

### 实时检测测试

训练完成后可在游戏中实时预览检测效果：

```powershell
uv run python scripts/detect_xueren.py    # 测试雪人模型
uv run python scripts/detect_huolong.py   # 测试火龙模型
uv run python scripts/detect_geli.py      # 测试 geli 模型（和平鸽+菊华梨）
```

会弹出透明悬浮窗，在游戏画面上叠加检测框，用于验证模型效果。

---

## 注意事项

- **分辨率**：推荐 1920×1080。脚本支持自适应缩放，阈值已下调至 0.4 以兼容其他分辨率。
- **自定义适配**：若分辨率特殊导致识别异常，可在当前分辨率下重新截图覆盖 `templates/` 中的同名文件。
- **窗口状态**：游戏窗口**不能最小化**（可被遮挡但不能最小化）。
- **前台要求**：键盘输入需游戏窗口在前台；鼠标点击需目标位置未被遮挡。
- **巡航模式**：模式 3 启动时会弹出独立悬浮窗，需框选小地图区域完成初始化。

---

## 项目结构

```
├── main.py              # 入口，模式选择和窗口选择
├── config.py            # 全局配置（阈值、ROI、模板名等）
├── core/                # 核心引擎
│   ├── engine.py        # 主循环，战斗状态机
│   ├── capture.py       # 游戏窗口截图
│   ├── vision.py        # OpenCV 模板匹配
│   ├── input.py         # Interception 键鼠模拟
│   ├── window.py        # 窗口查找和枚举
│   ├── pet_detector.py  # YOLO 精灵检测
│   └── ...
├── modes/               # 运行模式（策略模式）
│   ├── base.py          # 抽象基类
│   ├── ball.py          # 模式 1：自动丢球
│   ├── ball_pet.py      # 模式 2：精灵定位丢球
│   └── ball_cruise.py   # 模式 3：巡航 + 抓宠
├── cruise_capture/      # 巡航路径规划与状态机
├── luoke_location_src/  # SIFT 地图定位系统
├── scripts/             # 训练/标注/标定工具
├── templates/           # 模板匹配图片（按分辨率缩放）
├── models/              # YOLO 模型文件（.pt）
└── datasets/            # 训练数据集
```

---

## 免责声明

1. **仅供学习参考**：本工具仅用于计算机视觉（OpenCV 模板匹配、SIFT 特征跟踪、YOLO 目标检测）及输入模拟技术的研究与交流。
2. **驱动风险**：本工具使用 Interception 内核级驱动模拟键鼠输入，该驱动以管理员权限运行在系统内核层。请从 [Interception 官方仓库](https://github.com/oblitum/Interception) 下载，使用非官方来源的驱动文件可能存在安全风险。
3. **账号风险**：使用自动化脚本可能违反《洛克王国：世界》用户协议，存在被警告、限制或永久封禁的风险。**由此产生的一切后果由使用者本人承担。**
4. **技术边界**：本工具不修改游戏内存、不篡改网络封包、不注入游戏进程。所有操作均基于截屏 → 图像分析 → 模拟外设输入的技术路径，与人类观察屏幕后操作键鼠的行为等价。
5. **无担保责任**：本软件按"现状"提供，不提供任何明示或暗示的担保。作者不对因使用或无法使用本工具造成的任何直接或间接损失（包括但不限于账号封禁、数据丢失、硬件损坏）承担责任。

---

## 致谢

本项目基于以下开源项目二次开发：

- [yorusacri/Auto-rocokingdom](https://github.com/yorusacri/Auto-rocokingdom) — 原始自动化框架，提供了模板匹配引擎和战斗状态机的核心思路
- [761696148/Game-Map-Tracker](https://github.com/761696148/Game-Map-Tracker) — SIFT 地图定位追踪方案，用于巡航模式的位置感知
- [oblitum/Interception](https://github.com/oblitum/Interception) — 内核级输入驱动
