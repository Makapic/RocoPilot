import os
import sys

from config import CONFIG, load_prefs, save_prefs
from core.engine import Engine
from core.window import list_windows_by_keyword
from modes import MODE_REGISTRY
ACTION_OPTIONS = {
    "1": ("gather", "只聚能（按 X）"),
    "2": ("escape", "逃跑（按 ESC + 确认）"),
    "3": ("skill1_gather", "释放技能1后聚能（按 1，再按 X）"),
    "4": ("none", "不操作"),
}


ACTION_LABELS = {key: label for key, (action, label) in ACTION_OPTIONS.items()}
ACTION_VALUES = {action: label for key, (action, label) in ACTION_OPTIONS.items()}


def _select_window() -> int | None:
    keyword = CONFIG.window_title_keyword
    windows = list_windows_by_keyword(keyword)

    if not windows:
        print(f"\n[错误] 未找到包含 \"{keyword}\" 的窗口，请确认游戏已启动。")
        return None

    print(f"\n找到 {len(windows)} 个匹配 \"{keyword}\" 的窗口:\n")
    for i, (hwnd, title, (x, y, w, h)) in enumerate(windows, 1):
        print(f"  {i}. {title}")
        print(f"     句柄: {hwnd}  位置: ({x}, {y})  尺寸: {w}x{h}\n")

    if len(windows) == 1:
        hwnd, title, (_, _, w, h) = windows[0]
        print(f"仅找到一个窗口，自动选择: {title}\n")
    else:
        while True:
            sel = input(f"请选择窗口 (1-{len(windows)}): ").strip()
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(windows):
                    break
            except ValueError:
                pass
            print(f"输入无效，请输入 1-{len(windows)} 的数字")

        hwnd, title, _ = windows[idx]
        print(f"\n已选择: {title}\n")

    return hwnd


def _action_label(action: str) -> str:
    return ACTION_VALUES.get(action, action)


def _prompt_action(battle_type: str, default: str) -> str:
    print(f"\n请选择遇到【{battle_type}】时的行为:")
    for key, (action, label) in ACTION_OPTIONS.items():
        marker = "（默认）" if action == default else ""
        print(f"  {key}: {label}{marker}")
    choice = input(f"请输入选项 ({'/'.join(ACTION_OPTIONS.keys())}): ").strip()
    if choice in ACTION_OPTIONS:
        return ACTION_OPTIONS[choice][0]
    return default


def _list_pet_models() -> list:
    """扫描 models/ 目录，返回可用的精灵模型名称列表。"""
    model_dir = CONFIG.pet_model_dir
    models = []
    if os.path.isdir(model_dir):
        for f in sorted(os.listdir(model_dir)):
            if f.endswith(".pt"):
                models.append(f[:-3])  # 去掉 .pt 后缀
    return models


def _select_pet_model(prefs: dict) -> str:
    """让用户选择使用哪个精灵检测模型。"""
    models = _list_pet_models()
    if not models:
        print("\n[提示] models/ 目录中没有找到模型文件，使用默认: xueren")
        return "xueren"

    default = prefs.get("pet_model_name", CONFIG.pet_model_name)
    print(f"\n可用的精灵检测模型:")
    for i, name in enumerate(models, 1):
        marker = "（默认）" if name == default else ""
        print(f"  {i}. {name}{marker}")

    sel = input(f"请选择模型 (1-{len(models)}, 回车使用默认): ").strip()
    if sel.isdigit():
        idx = int(sel) - 1
        if 0 <= idx < len(models):
            return models[idx]
    return default


def _run_cruise_subprocess() -> None:
    """Entry point for cruise subprocess (launched by mode 3 when frozen)."""
    from luoke_location_src.cruise_main import main as cruise_main
    cruise_main()


def main() -> None:
    if "--cruise" in sys.argv:
        _run_cruise_subprocess()
        return

    prefs = load_prefs()

    # 恢复上次的精灵模型选择
    if "pet_model_name" in prefs:
        CONFIG.pet_model_name = prefs["pet_model_name"]

    print("\n请选择运行模式:")
    for key, cls in sorted(MODE_REGISTRY.items()):
        print(f"  {key}: {cls.label}")
    print("有问题或新功能建议请提 issue。如果这个项目对你有帮助，欢迎点个 Star 支持一下。")
    print("\n[提示] 脚本支持自适应分辨率，推荐使用 1920×1080 以获得更高识别精度。")
    print("分辨率越低 Score 可能越低；若识别异常，可在当前分辨率下重截 templates 进行适配。")

    choices = "/".join(sorted(MODE_REGISTRY.keys()))
    choice = input(f"请输入选项 ({choices}): ").strip()

    if choice == "2":
        model_name = _select_pet_model(prefs)
        prefs["pet_model_name"] = model_name
        CONFIG.pet_model_name = model_name

        pollute_action = prefs.get("pet_pollute_action", "escape")
        normal_action = prefs.get("pet_normal_action", "escape")

        print("\n当前遇敌配置:")
        print(f"  污染战斗 → {_action_label(pollute_action)}")
        print(f"  普通战斗 → {_action_label(normal_action)}")

        customize = input("是否修改遇敌配置？(y/N): ").strip().lower()
        if customize == "y":
            pollute_action = _prompt_action("污染战斗", pollute_action)
            normal_action = _prompt_action("普通战斗", normal_action)
            print(f"\n已应用遇敌配置:")
            print(f"  污染战斗 → {_action_label(pollute_action)}")
            print(f"  普通战斗 → {_action_label(normal_action)}")

        prefs["pet_pollute_action"] = pollute_action
        prefs["pet_normal_action"] = normal_action

        mode_cls = MODE_REGISTRY[choice]
        mode = mode_cls()
        mode.set_battle_actions(pollute_action=pollute_action, normal_action=normal_action)
    elif choice == "3":
        model_name = _select_pet_model(prefs)
        prefs["pet_model_name"] = model_name
        CONFIG.pet_model_name = model_name

        pollute_action = prefs.get("pet_pollute_action", "escape")
        normal_action = prefs.get("pet_normal_action", "escape")

        print("\n当前遇敌配置:")
        print(f"  污染战斗 → {_action_label(pollute_action)}")
        print(f"  普通战斗 → {_action_label(normal_action)}")

        customize = input("是否修改遇敌配置？(y/N): ").strip().lower()
        if customize == "y":
            pollute_action = _prompt_action("污染战斗", pollute_action)
            normal_action = _prompt_action("普通战斗", normal_action)
            print(f"\n已应用遇敌配置:")
            print(f"  污染战斗 → {_action_label(pollute_action)}")
            print(f"  普通战斗 → {_action_label(normal_action)}")

        prefs["pet_pollute_action"] = pollute_action
        prefs["pet_normal_action"] = normal_action

        mode_cls = MODE_REGISTRY[choice]
        mode = mode_cls()
        mode.set_battle_actions(pollute_action=pollute_action, normal_action=normal_action)
    else:
        mode_cls = MODE_REGISTRY.get(choice, MODE_REGISTRY["1"])
        mode = mode_cls()

    save_prefs(prefs)

    hwnd = _select_window()
    if hwnd is None:
        return

    Engine(mode, hwnd=hwnd).run()


if __name__ == "__main__":
    main()
