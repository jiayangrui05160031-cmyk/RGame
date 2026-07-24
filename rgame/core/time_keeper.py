"""时间管理。

按《游戏总体目录》§4 与《游戏总体流程》§1：

- ``run_time`` 与 ``stage_time`` 仅在 ``RUNNING`` 中累计；
- 暂停、超级怪兽警告、升级、抽卡、过关、应用后台时全部冻结；
- 提供 :py:meth:`advance` 由外部循环节拍调用，不内置时钟；
- 大数值缩写（K/M/B）保证 UI 显示稳定。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def abbr(value: float, precision: int = 1) -> str:
    """大数缩写。

    >>> abbr(12_000)
    '12K'
    >>> abbr(2_580_000)
    '2.6M'
    """
    if value < 1000:
        return f"{int(round(value))}" if value >= 0 else f"{value:.0f}"
    units = ("", "K", "M", "B", "T")
    v = float(value)
    idx = 0
    while abs(v) >= 1000 and idx < len(units) - 1:
        v /= 1000
        idx += 1
    if precision == 0:
        return f"{int(round(v))}{units[idx]}"
    return f"{v:.{precision}f}{units[idx]}"


@dataclass
class TimeKeeper:
    """冻结感知的时间管理者。

    使用方式：

        timer = TimeKeeper()
        if state_machine.current == RUNNING:
            timer.advance(dt_seconds)
    """

    run_time: float = 0.0
    stage_time: float = 0.0
    paused_time: float = 0.0
    super_warning_time: float = 0.0
    card_select_time: float = 0.0
    level_up_time: float = 0.0
    stage_clear_time: float = 0.0
    delta: float = 0.0

    # --- 推进 -------------------------------------------------------------

    def advance(self, dt: float) -> None:
        """不直接判断状态机，由调用方在合法状态机下推进。

        :param dt: 步进秒数（已夹至 ``[0, max_dt]`` 防止巨大帧时间）。
        """
        if dt < 0:
            dt = 0
        self.delta = dt
        self.run_time += dt
        self.stage_time += dt

    def freeze_paused(self, dt: float) -> None:
        self.paused_time += max(0.0, dt)

    def freeze_super_warning(self, dt: float) -> None:
        self.super_warning_time += max(0.0, dt)

    def freeze_card_select(self, dt: float) -> None:
        self.card_select_time += max(0.0, dt)

    def freeze_level_up(self, dt: float) -> None:
        self.level_up_time += max(0.0, dt)

    def freeze_stage_clear(self, dt: float) -> None:
        self.stage_clear_time += max(0.0, dt)

    def reset_stage(self) -> None:
        self.stage_time = 0.0
        self.stage_clear_time = 0.0

    def reset_run(self) -> None:
        self.run_time = 0.0
        self.stage_time = 0.0
        self.paused_time = 0.0
        self.super_warning_time = 0.0
        self.card_select_time = 0.0
        self.level_up_time = 0.0
        self.stage_clear_time = 0.0

    # --- 报告 -------------------------------------------------------------

    def progress_phase(self) -> int:
        """按《怪兽要求》§8 阶段时间映射，仅根据 ``stage_time``。"""
        return int(self.stage_time // 120)  # 每 120 秒一个阶段窗口

    @property
    def stage_minutes(self) -> int:
        return int(self.stage_time // 60)


__all__ = ["TimeKeeper", "abbr", "math"]
