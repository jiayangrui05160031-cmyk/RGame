"""rgame 启动入口。

用法::

    python main.py                  # pygame 桌面端
    python main.py --seed 42        # 固定 seed
    python main.py --headless       # 不进入 GUI（CI / 调试 Engine）
"""

from __future__ import annotations

import argparse
import sys
import traceback

from rgame.engine import Engine


def main() -> int:
    parser = argparse.ArgumentParser(description="rgame — 俯视角单屏肉鸽")
    parser.add_argument("--seed", type=int, default=None, help="固定 seed")
    parser.add_argument("--platform", default="win", help="win/mac/linux/android/ios")
    parser.add_argument("--save", default="rgame_profile.json", help="存档路径")
    parser.add_argument("--log", default=None, help="日志文件路径")
    parser.add_argument("--disk-log", action="store_true", help="开启磁盘日志")
    parser.add_argument("--headless", action="store_true", help="不进入 GUI，仅打印可执行情况")
    parser.add_argument("--backend", default="pygame", choices=["pygame", "kivy"], help="渲染后端")
    args = parser.parse_args()

    if args.headless:
        engine = Engine(platform=args.platform, seed=args.seed)
        engine.start_run(preset_id="preset_balanced")
        print("Engine booted:", engine.state())
        print("seed =", engine.seed)
        return 0

    if args.backend == "kivy":
        try:
            from rgame.render.kivy_app import RGameKivyApp
        except Exception:
            RGameKivyApp = None
        if RGameKivyApp is None:
            print("Kivy 未安装；请 `pip install \"kivy[base]\"`", file=sys.stderr)
            return 2
        app = RGameKivyApp(
            seed=args.seed,
            platform=args.platform,
            save_path=args.save,
            log_path=args.log,
            enable_disk_log=args.disk_log,
        )
        app.run()
        return 0

    try:
        from rgame.render.pygame_app import RGameApp
    except Exception:
        RGameApp = None
    if RGameApp is None:
        print("pygame 未安装；请 `pip install pygame`", file=sys.stderr)
        return 2

    try:
        app = RGameApp(
            seed=args.seed,
            platform=args.platform,
            enable_disk_log=args.disk_log,
            save_path=args.save,
            log_path=args.log or "rgame_run.log",
        )
        app.run()
    except Exception as e:
        print("=" * 60, file=sys.stderr)
        print("火星攻击 启动失败！", file=sys.stderr)
        print("请截图以下信息或报告开发者。", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        traceback.print_exc()
        print("=" * 60, file=sys.stderr)
        input("按 Enter 退出...")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
