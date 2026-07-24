"""移动与边界。

按《玩家操作》§3 +《环境背景系统》§2：

- 输入向量归一化避免对角速度叠加；
- 移动速度 = 基础 × 加成；
- 越界只截断超界分量。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PlayableBounds:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)


def normalize_move(x: float, y: float) -> tuple[float, float]:
    """(x, y) ∈ R²，归一化到单位长度。

    支持反向键相互抵消（输入层完成）。
    """
    if x == 0 and y == 0:
        return 0.0, 0.0
    n = math.hypot(x, y)
    return x / n, y / n


def apply_movement(
    pos: tuple[float, float],
    dir_: tuple[float, float],
    speed: float,
    dt: float,
    bounds: PlayableBounds,
    radius: float = 22.0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """根据方向/速度/dt 计算下一位置；超出可玩区时只截断。

    :return: (新位置, 实际速度向量)（实际速度=单方向被截时）。
    """
    if dir_ == (0.0, 0.0) or speed == 0:
        return pos, (0.0, 0.0)
    dx = dir_[0] * speed * dt
    dy = dir_[1] * speed * dt
    nx = pos[0] + dx
    ny = pos[1] + dy
    final_vx, final_vy = dir_[0] * speed, dir_[1] * speed
    # 截断越界分量
    if nx - radius < bounds.min_x:
        nx = bounds.min_x + radius
        final_vx = max(0.0, final_vx)
    elif nx + radius > bounds.max_x:
        nx = bounds.max_x - radius
        final_vx = min(0.0, final_vx)
    if ny - radius < bounds.min_y:
        ny = bounds.min_y + radius
        final_vy = max(0.0, final_vy)
    elif ny + radius > bounds.max_y:
        ny = bounds.max_y - radius
        final_vy = min(0.0, final_vy)
    return (nx, ny), (final_vx, final_vy)


def clamp_to_playable_bounds(pos: tuple[float, float], bounds: PlayableBounds, radius: float = 22.0) -> tuple[float, float]:
    nx = max(bounds.min_x + radius, min(bounds.max_x - radius, pos[0]))
    ny = max(bounds.min_y + radius, min(bounds.max_y - radius, pos[1]))
    return (nx, ny)
