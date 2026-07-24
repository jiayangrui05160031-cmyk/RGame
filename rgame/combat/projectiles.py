"""投射物与对象池。

按《战斗互动系统》§7：

- 位置 / 速度 / 阵营 / 伤害 / 存活时间 / 穿透剩余；
- 高速投射物使用连续碰撞或子步进；
- 超出可玩区或达到存活时间立即回收；
- 全局硬上限基准 500。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .damage import (
    DamageRequest,
    calc_damage,
    apply_damage_to_target,
    DamageResult,
)
from ..core.event_bus import Event, EventBus


PROJECTILE_POOL = 500  # 基线


@dataclass
class Projectile:
    entity_id: str
    owner: str
    faction: str  # "player" / "enemy"
    position: tuple[float, float]
    velocity: tuple[float, float]
    damage: float
    radius: float
    lifetime: float
    spawn_time: float
    penetration_left: int
    crit_chance: float
    crit_multiplier: float
    crit_roll: float
    targets_hit: set[str] = field(default_factory=set)
    bounces: bool = False
    bounce_left: int = 0
    weapon_id: str | None = None
    source_id: str | None = None
    extra_dmg_share: float = 0.45
    alive: bool = True
    is_melee: bool = False
    splash_radius: float = 0.0
    attack_angle: float = 0.0          # 弧度，非制导发射时锁定
    attack_arc_deg: float = 360.0      # 近战扇形；360 为环形
    visual_kind: str = "bullet"       # bullet / laser / slash / boss_orb
    initial_speed: float = 0.0         # 用于首快后慢的敌方弹道表现
    deceleration: float = 0.0          # 每秒减速量（世界单位）
    min_speed: float = 0.0             # 减速下限，避免弹体停在场上


@dataclass
class ProjectileSystem:
    """投射物系统：玩家 + 敌人共用。"""

    projectiles: list[Projectile] = field(default_factory=list)
    pool_capacity: int = PROJECTILE_POOL
    _id_seq: int = 0
    bus: Optional[EventBus] = None

    def reset(self) -> None:
        self.projectiles.clear()
        self._id_seq = 0

    def make_id(self) -> str:
        self._id_seq += 1
        return f"proj_{self._id_seq}"

    def emit(
        self,
        *,
        owner: str,
        faction: str,
        origin: tuple[float, float],
        target_pos: tuple[float, float],
        damage: float,
        radius: float,
        speed: float,
        lifetime: float,
        penetration: int,
        crit_chance: float,
        crit_multiplier: float,
        crit_roll: float,
        weapon_id: str | None,
        source_id: str | None,
        bounces: bool = False,
        bounce_left: int = 0,
        now: float = 0.0,
        is_melee: bool = False,
        splash_radius: float = 0.0,
        extra_dmg_share: float = 0.45,
        burst_arc_deg: float = 0.0,
        burst_count: int = 1,
        attack_angle: float | None = None,
        attack_arc_deg: float = 360.0,
        visual_kind: str = "bullet",
        deceleration: float | None = None,
        min_speed: float | None = None,
    ) -> list[Projectile]:
        """创建一组投射物（处理多发、扇形）。返回新建的列表。"""
        if len(self.projectiles) >= self.pool_capacity:
            return []
        out: list[Projectile] = []
        dx = target_pos[0] - origin[0]
        dy = target_pos[1] - origin[1]
        d = math.hypot(dx, dy)
        if d < 1e-6 and burst_count == 1:
            dx, dy = 1.0, 0.0
            d = 1.0
        ux, uy = dx / d, dy / d
        if burst_count <= 1 or burst_arc_deg <= 0:
            vels = [(ux * speed, uy * speed)]
        else:
            # burst_count 个角度分布在 [-arc/2, +arc/2]
            vels = []
            step = burst_arc_deg / max(1, burst_count - 1)
            start = -burst_arc_deg / 2
            for i in range(burst_count):
                deg = math.radians(start + step * i)
                rot_x = ux * math.cos(deg) - uy * math.sin(deg)
                rot_y = ux * math.sin(deg) + uy * math.cos(deg)
                vels.append((rot_x * speed, rot_y * speed))
        locked_angle = math.atan2(dy, dx) if attack_angle is None else attack_angle
        # 敌方弹体默认采用“出膛快、远处慢”的非制导弹道；玩家弹体保持原速度。
        if deceleration is None:
            deceleration = max(80.0, speed * 0.42) if faction == "enemy" and speed > 0 else 0.0
        if min_speed is None:
            min_speed = speed * 0.44 if faction == "enemy" and speed > 0 else speed
        for vx, vy in vels:
            p = Projectile(
                entity_id=self.make_id(),
                owner=owner,
                faction=faction,
                position=origin,
                velocity=(vx, vy),
                damage=damage,
                radius=radius,
                lifetime=lifetime,
                spawn_time=now,
                penetration_left=penetration,
                crit_chance=crit_chance,
                crit_multiplier=crit_multiplier,
                crit_roll=crit_roll,
                bounces=bounces,
                bounce_left=bounce_left,
                weapon_id=weapon_id,
                source_id=source_id,
                is_melee=is_melee,
                splash_radius=splash_radius,
                attack_angle=locked_angle,
                attack_arc_deg=attack_arc_deg,
                visual_kind=visual_kind,
                extra_dmg_share=extra_dmg_share,
                initial_speed=speed,
                deceleration=max(0.0, deceleration),
                min_speed=max(0.0, min_speed),
            )
            self.projectiles.append(p)
            out.append(p)
        return out

    def step(self, dt: float, now: float, bounds) -> list[Projectile]:
        """推进投射物。返回本步结束时仍存活的对象引用（同对象可读取）。"""
        keep: list[Projectile] = []
        for p in self.projectiles:
            if not p.alive:
                continue
            if p.deceleration > 0:
                current_speed = math.hypot(p.velocity[0], p.velocity[1])
                target_speed = max(p.min_speed, current_speed - p.deceleration * dt)
                if current_speed > 1e-6 and target_speed < current_speed:
                    scale = target_speed / current_speed
                    p.velocity = (p.velocity[0] * scale, p.velocity[1] * scale)
            # 推进
            nx = p.position[0] + p.velocity[0] * dt
            ny = p.position[1] + p.velocity[1] * dt
            p.position = (nx, ny)
            p.lifetime -= dt
            if p.lifetime <= 0:
                p.alive = False
                continue
            # 越界 / 出可玩区
            if (
                nx < bounds.min_x - 8
                or nx > bounds.max_x + 8
                or ny < bounds.min_y - 8
                or ny > bounds.max_y + 8
            ):
                if p.bounces and p.bounce_left > 0:
                    # 反弹后把弹体夹回场内并继续保留；旧代码 continue 前未加入
                    # keep，导致所有所谓反弹弹体第一次撞墙就直接消失。
                    if nx < bounds.min_x or nx > bounds.max_x:
                        p.velocity = (-p.velocity[0], p.velocity[1])
                    if ny < bounds.min_y or ny > bounds.max_y:
                        p.velocity = (p.velocity[0], -p.velocity[1])
                    p.position = (
                        max(bounds.min_x, min(bounds.max_x, nx)),
                        max(bounds.min_y, min(bounds.max_y, ny)),
                    )
                    p.bounce_left -= 1
                    keep.append(p)
                    continue
                p.alive = False
                continue
            keep.append(p)
        self.projectiles = keep
        return keep

    def apply_to_target(
        self,
        p: Projectile,
        *,
        target_id: str,
        target_max_shield: float,
        target_current_shield: float,
        target_alive: bool,
        target_faction: str,
        target_armor: float,
        target_vuln_pct: float = 0.0,
        target_max_hp: float = 0.0,
        attack_cap: float = math.inf,
        attack_cap_active: bool = False,
        attacker_pen_pct: float = 0.0,
    ) -> tuple[DamageResult, dict]:
        req = DamageRequest(
            source_id=p.source_id or p.owner,
            target_id=target_id,
            source_is_player=p.faction == "player",
            base_damage=p.damage,
            crit_chance=p.crit_chance,
            crit_multiplier=p.crit_multiplier,
            crit_roll=p.crit_roll,
            target_armor=target_armor,
            target_vuln_pct=target_vuln_pct,
            attack_cap_active=attack_cap_active,
            attack_cap=attack_cap,
            attacker_pen_pct=attacker_pen_pct,
        )
        res, upd = apply_damage_to_target(
            req,
            target_max_shield=target_max_shield,
            target_current_shield=target_current_shield,
            target_alive=target_alive,
            target_faction=target_faction,
            source_faction=p.faction,
        )
        return res, upd
