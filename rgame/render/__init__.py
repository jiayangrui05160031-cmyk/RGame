"""rgame 渲染层。

渲染器必须延迟加载：Kivy 会在导入时读取 ``sys.argv``，如果在
pygame 或 headless 模式下提前导入它，会抢走本程序的命令行参数。
"""

from __future__ import annotations

from importlib import import_module

__all__ = ["RGameApp", "build_input_provider", "RGameKivyApp"]


def __getattr__(name: str):
    if name in ("RGameApp", "build_input_provider"):
        module = import_module(".pygame_app", __name__)
        return getattr(module, name)
    if name == "RGameKivyApp":
        try:
            module = import_module(".kivy_app", __name__)
            return module.RGameKivyApp
        except Exception:
            return None
    raise AttributeError(name)
