"""掉落系统。

按《掉落系统》：

- 3 秒寿命；只有 ``RUNNING`` 累计；
- 经验、治疗、临时增益、护盾碎片为有利；
- 炸弹为危险，2.5 秒引爆，爆炸半径 120、基础 18；
- 防连出：开局 20s 不出炸弹；同一玩家附近连续 3 掉落最多 1 炸弹；
- 玩家生命 < 25% 时炸弹权重减半、治疗权重提高；
- 场上硬上限 120；
- 等级经验通过 ``pickup_collected`` 进入等级系统。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from ..core.event_bus import Event, EventBus
from ..core.run_context import RunContext
from ..enemies.enemies import Enemy


PICKUP_LIFETIME = 3.0
BOMB_LIFETIME = 2.5
DROP_HARD_CAP = 120
BASE_BOMB_RADIUS = 120.0
BASE_BOMB_DAMAGE = 18.0
INITIAL_NO_BOMB_TIME = 20.0


class PickupKind:
    XP = "xp"
    HEAL = "heal"
    TEMP_BUFF = "temp_buff"
    SHIELD_RESTORE = "shield_restore"
    ARMOR = "armor"
    COIN = "coin"
    SKILL_CHARGE = "skill_charge"


@dataclass
class Pickup:
    """有利掉落。"""

    entity_id: str
    kind: str
    amount: float = 0.0
    buff: Optional[str] = None
    buff_duration: float = 0.0
    spawn_time: float = 0.0
    lifetime: float = PICKUP_LIFETIME
    position: tuple[float, float] = (0, 0)
    magnetized: bool = False
    resolved: bool = False
    icon: str = "xp"

    def alive_at(self, now: float) -> bool:
        if self.resolved:
            return False
        return (now - self.spawn_time) < self.lifetime


@dataclass
class HazardBomb:
    """危险炸弹。"""

    entity_id: str
    position: tuple[float, float]
    radius: float
    base_damage: float
    spawn_time: float
    arm_delay: float = 0.3
    armed_at: float = 0.0
    lifetime: float = BOMB_LIFETIME
    resolved: bool = False
    damage_multiplier: float = 1.0
    icon: str = "bomb"
    faction: str = "enemy"
    harmless_to_player: bool = False

    def alive_at(self, now: float) -> bool:
        if self.resolved:
            return False
        return (now - self.spawn_time) < self.lifetime


@dataclass
class DropSystem:
    bus: EventBus
    pickups: list[Pickup] = field(default_factory=list)
    bombs: list[HazardBomb] = field(default_factory=list)
    last_drops_window: deque[bool] = field(default_factory=lambda: deque(maxlen=3))
    last_player_was_within: deque[bool] = field(default_factory=lambda: deque(maxlen=3))
    run_start_time: float = 0.0
    run_time_offset: float = 0.0

    # ---- 状态 ----------------------------------------------------------

    def reset(self) -> None:
        self.pickups.clear()
        self.bombs.clear()
        self.last_drops_window.clear()

    # ---- 内部：选取条目 ------------------------------------------------

    def _draw_drop(
        self,
        *,
        drop_table: dict,
        rng,
        now: float,
        low_hp: bool,
        run_time: float,
    ) -> tuple[str, dict] | None:
        """从掉落表中抽取一项；遵循低生命补偿。"""
        entries = drop_table["entries"]
        # 只调整本次抽样权重；浅拷贝条目会把低血量补偿永久写回配置。
        weights = []
        for entry in entries:
            weight = max(0.0, float(entry.get("weight", 1)))
            if low_hp and entry["kind"] == "hazard_bomb":
                weight *= 0.5
            elif low_hp and entry["kind"] == "heal":
                weight *= 1.5
            weights.append(weight)
        total = sum(weights)
        if total <= 0:
            idx = rng.range(len(entries))
        else:
            roll = rng.random() * total
            acc = 0.0
            idx = len(entries) - 1
            for i, weight in enumerate(weights):
                acc += weight
                if roll <= acc:
                    idx = i
                    break
        return entries[idx]["kind"], entries[idx]

    # ---- 外部调用 ------------------------------------------------------

    def spawn_drops(
        self,
        *,
        run_context: RunContext,
        drop_table: dict,
        position: tuple[float, float],
        player_pos: tuple[float, float],
        player_current_hp: float,
        player_max_hp: float,
        low_hp_threshold: float = 0.25,
    ) -> list[str]:
        """按敌人死亡触发调度一次掉落生成。

        返回本次新增的实体 ID 列表（pickup + bomb）。
        """
        now = run_context.timer.run_time
        run_time = now - self.run_start_time
        low_hp = (player_current_hp / max(1.0, player_max_hp)) < low_hp_threshold

        # 场上硬上限：先尝试命中 + 合并
        if len(self.pickups) + len(self.bombs) >= DROP_HARD_CAP:
            self.bus.publish(Event(
                id=f"dropcap-{now}",
                type="drop_capped",
                payload={"position": list(position)},
                timestamp=now,
            ))
            return []

        # 防连出：开局 20 秒不出炸弹
        first_20 = run_time < INITIAL_NO_BOMB_TIME

        outcome: list[str] = []

        # 抽样
        rng = run_context.rng.get("drop_rng")
        kind, entry = self._draw_drop(
            drop_table=drop_table,
            rng=rng,
            now=now,
            low_hp=low_hp,
            run_time=run_time,
        )

        # 防连出：限制炸弹连续
        recent_window = list(self.last_drops_window)[-2:]
        if kind == "hazard_bomb":
            if first_20:
                # 兜底成经验
                kind = "xp_small"
                entry = {"kind": "xp_small", "amount": 2, "weight": 1, "icon": "xp"}
            elif len(recent_window) >= 2 and all(recent_window):
                kind = "xp_small"
                entry = {"kind": "xp_small", "amount": 3, "weight": 1, "icon": "xp"}

        # 位置合法性：避免与玩家重叠
        d = math.hypot(position[0] - player_pos[0], position[1] - player_pos[1])
        if d < 90 and kind == "hazard_bomb":
            kind = "xp_small"
            entry = {"kind": "xp_small", "amount": 2, "weight": 1, "icon": "xp"}

        # 记录最近是否为炸弹（用于防连出）
        self.last_drops_window.append(kind == "hazard_bomb")

        if kind == "hazard_bomb":
            b = HazardBomb(
                entity_id=f"bomb_{len(self.bombs)}_{int(now * 1000)}",
                position=position,
                radius=float(entry.get("radius", BASE_BOMB_RADIUS)),
                base_damage=float(entry.get("damage", BASE_BOMB_DAMAGE)),
                spawn_time=now,
                damage_multiplier=1.0,
                icon=entry.get("icon", "bomb"),
            )
            b.armed_at = now + b.arm_delay
            self.bombs.append(b)
            self.bus.publish(Event(
                id=f"dspawn-{b.entity_id}",
                type="hazard_drop_armed",
                payload={"position": list(position), "radius": b.radius, "lifetime": b.lifetime},
                timestamp=now,
            ))
            outcome.append(b.entity_id)
        elif kind in ("xp_small", "xp_large", "heal", "shield_restore", "armor", "temp_buff", "coin", PickupKind.SKILL_CHARGE):
            p = Pickup(
                entity_id=f"drop_{len(self.pickups)}_{int(now * 1000)}",
                kind=kind,
                amount=float(entry.get("amount", entry.get("pct_of_maxhp", 0) or 1)),
                buff=entry.get("buff"),
                buff_duration=float(entry.get("duration", 0.0)),
                spawn_time=now,
                position=position,
                icon=entry.get("icon", "drop"),
            )
            self.pickups.append(p)
            self.bus.publish(Event(
                id=f"dspawn-{p.entity_id}",
                type="drop_spawned",
                payload={"kind": p.kind, "amount": p.amount, "position": list(position)},
                timestamp=now,
            ))
            outcome.append(p.entity_id)
        return outcome

    # ---- 推进 ----------------------------------------------------------

    def step(self, *, dt: float, now: float, run_context: RunContext, player_pos, pickup_radius: float, player_alive: bool, on_pickup, on_bomb_explode):
        """3 秒寿命 + 玩家拾取 + 炸弹引爆。

        :param on_pickup: ``callable(pickup: Pickup) -> None``。
        :param on_bomb_explode: ``callable(bomb: HazardBomb, position, radius, damage) -> None``。
        """
        # pickup
        keep: list[Pickup] = []
        for p in self.pickups:
            # 3 秒到期
            if p.resolved:
                continue
            if now - p.spawn_time >= p.lifetime:
                self.bus.publish(Event(
                    id=f"dexp-{p.entity_id}",
                    type="drop_expired",
                    payload={"kind": p.kind, "amount": p.amount},
                    timestamp=now,
                ))
                continue
            if not player_alive or p.resolved:
                keep.append(p)
                continue
            # 磁吸
            d = math.hypot(p.position[0] - player_pos[0], p.position[1] - player_pos[1])
            if d <= pickup_radius:
                # 满血治疗物不消耗
                stat = on_pickup(p)
                p.resolved = True
            else:
                keep.append(p)
        self.pickups = keep

        # bomb
        keep_b: list[HazardBomb] = []
        for b in self.bombs:
            if b.resolved:
                continue
            if now - b.spawn_time >= b.lifetime:
                b.resolved = True
                self.bus.publish(Event(
                    id=f"dexp-{b.entity_id}",
                    type="drop_expired",
                    payload={"kind": "hazard_bomb"},
                    timestamp=now,
                ))
                continue
            if now >= b.armed_at + (b.lifetime - b.arm_delay):
                b.resolved = True
                # 爆炸
                on_bomb_explode(b, b.position, b.radius, b.base_damage * b.damage_multiplier)
                self.bus.publish(Event(
                    id=f"dexp-{b.entity_id}",
                    type="hazard_drop_triggered",
                    payload={"position": list(b.position), "radius": b.radius, "damage": b.base_damage * b.damage_multiplier},
                    timestamp=now,
                ))
                continue
            keep_b.append(b)
        self.bombs = keep_b


def create_drop_system(bus: EventBus) -> DropSystem:
    return DropSystem(bus=bus)


def spawn_drops_on_enemy_defeated(
    drop_system: DropSystem,
    *,
    run_context: RunContext,
    enemy: Enemy,
    drop_tables: dict,
    player_pos,
    player_current_hp,
    player_max_hp,
    player_alive: bool,
    table_id: str | None = None,
) -> list[str]:
    """在敌人死亡位置调度一次掉落。"""
    if not player_alive:
        return []
    table = drop_tables.get(table_id or enemy.drop_table_id, drop_tables.get("std_drops"))
    if table is None:
        return []
    return drop_system.spawn_drops(
        run_context=run_context,
        drop_table=table,
        position=enemy.position,
        player_pos=player_pos,
        player_current_hp=player_current_hp,
        player_max_hp=player_max_hp,
    )
