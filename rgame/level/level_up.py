"""等级系统。

按《等级系统》：

- 升级曲线：``xp_to_next(level) = round(20 + 8 * (level-1) + 2 * (level-1)^1.35)``；
- 经验只通过 ``pickup_collected`` 进入；
- 50 级软上限；
- 多级跨越支持；
- 升级候选池生成（不消耗 ``card_score``）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..core.event_bus import Event, EventBus


LEVEL_CAP = 50


def xp_to_next(level: int) -> int:
    """按《等级系统》§2 初始曲线。"""
    if level >= LEVEL_CAP:
        return math.inf
    delta = level - 1
    return round(20 + 8 * delta + 2 * (delta ** 1.35))


def xp_from_kill(enemy_xp_value: int) -> int:
    """按照敌人 xp_value 直接给出（可由玩家 xp_gain_pct 加成）。"""
    return max(0, int(enemy_xp_value))


@dataclass
class LevelCandidate:
    """一次升级选项。"""
    candidate_id: str
    name_zh: str
    rarity: str = "common"
    effect: dict = field(default_factory=dict)
    applies_to_weapon: Optional[str] = None


@dataclass
class LevelSystem:
    bus: EventBus
    level: int = 1
    current_xp: int = 0
    overflow_xp: int = 0
    pending_choices: int = 0
    last_choice: Optional[LevelCandidate] = None
    xp_gain_pct: float = 0.0

    def reset(self) -> None:
        self.level = 1
        self.current_xp = 0
        self.overflow_xp = 0
        self.pending_choices = 0
        self.last_choice = None
        self.xp_gain_pct = 0.0

    def add_xp(self, amount: int) -> int:
        """加入经验，返回本次触发的升级数。"""
        if amount <= 0:
            return 0
        amount = int(round(amount * (1.0 + self.xp_gain_pct)))
        leveled = 0
        cur = self.current_xp + amount
        while True:
            need = xp_to_next(self.level)
            if cur < need or self.level >= LEVEL_CAP:
                break
            cur -= need
            self.level += 1
            leveled += 1
            if self.level >= LEVEL_CAP:
                cur = 0
                break
        if self.level >= LEVEL_CAP:
            self.current_xp = 0
            self.overflow_xp += cur
        else:
            self.current_xp = cur
        if leveled > 0:
            self.pending_choices += leveled
            self.bus.publish(Event(
                id=f"lvl-{self.level}-up",
                type="level_up",
                payload={"level": self.level, "choices_pending": self.pending_choices},
                timestamp=0.0,
            ))
        return leveled

    def consume_one_choice(self) -> None:
        if self.pending_choices > 0:
            self.pending_choices -= 1

    def is_at_cap(self) -> bool:
        return self.level >= LEVEL_CAP


def create_level_system(bus: EventBus) -> LevelSystem:
    return LevelSystem(bus=bus)
