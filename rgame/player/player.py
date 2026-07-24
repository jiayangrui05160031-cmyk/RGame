"""玩家：数据、状态、伤害接口、移动、无敌帧、被动成长。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

from ..combat.damage import DamageRequest, apply_damage_to_target, DamageResult


class PlayerStatus(str, Enum):
    ACTIVE = "active"
    HIT = "hit"
    DYING = "dying"
    DEAD = "dead"


INVULNERABILITY_DEFAULT = 0.35  # 《角色细节》§1
PASSIVE_HP_PER_MIN = 0.02       # ×1.02
PASSIVE_DMG_PER_MIN = 0.015
PASSIVE_ARMOR_PER_MIN = 0.5


@dataclass
class PlayerGrowthSource:
    """成长账本。便于 UI 聚合查看。"""
    base_hp: float = 0.0
    base_damage: float = 0.0
    base_armor: float = 0.0
    crit_chance_bonus: float = 0.0
    crit_multiplier_bonus: float = 0.0
    pickup_radius_pct: float = 0.0
    move_speed_pct: float = 0.0
    aspd_pct_bonus: float = 0.0
    dmg_pct_bonus: float = 0.0
    range_pct_bonus: float = 0.0
    arc_deg_bonus: float = 0.0
    tol_deg_bonus: float = 0.0
    base_damage_boost: float = 0.0
    penetration_bonus: int = 0
    extra_projectiles: int = 0
    extra_projectile_dmg_share: float = 0.45
    low_hp_atk_pct: float = 0.0
    low_hp_move_pct: float = 0.0
    low_hp_threshold: float = 0.35
    max_shield_extra: float = 0.0
    max_hp_pct_bonus: float = 0.0
    shield_regen_rate: float = 0.0
    break_invuln_duration: float = 0.0
    break_invuln_cooldown: float = 0.0
    # 唯一彩色标记
    prism_flare: int = 0
    prism_flare_dmg_share: float = 0.45


@dataclass
class Player:
    """玩家数据。"""

    entity_id: str
    position: tuple[float, float]
    facing: float = 0.0
    base_max_hp: float = 100
    base_move_speed: float = 320
    base_pickup_radius: float = 90
    base_crit_chance: float = 0.05
    base_crit_multiplier: float = 1.5
    base_base_damage_boost: float = 0.0
    base_armor: float = 0.0

    # 护盾与生命
    current_hp: float = 100
    current_shield: float = 0.0
    max_shield: float = 0.0
    current_armor: float = 0

    # 状态
    status: PlayerStatus = PlayerStatus.ACTIVE
    invuln_left: float = 0.0
    break_invuln_cd_left: float = 0.0
    death_time: float = 0.0
    last_damage_time: float = 0.0

    # 成长 / 卡牌影响
    growth: PlayerGrowthSource = field(default_factory=PlayerGrowthSource)
    extra_max_hp_pct: float = 0.0
    # 计数
    damage_taken_total: float = 0.0
    shield_absorbed_total: float = 0.0
    raw_attack_power: float = 0.0    # 攻击侧累计
    effective_attack_power: float = 0.0
    overflow_attack_power: float = 0.0

    # 调试
    debug_damage_log: list[dict] = field(default_factory=list)


def effective_stats(p: Player) -> dict:
    """返回基础 + 卡牌 / 被动成长聚合后的最终值。"""
    base_hp = p.base_max_hp * (1.0 + p.extra_max_hp_pct + p.growth.max_hp_pct_bonus)
    base_damage = 1.0 * (1.0 + p.growth.dmg_pct_bonus) + p.growth.base_damage_boost
    base_armor = p.base_armor + p.growth.base_armor
    return {
        "max_hp": base_hp,
        "current_hp": min(p.current_hp, base_hp),
        "max_shield": p.max_shield + p.growth.max_shield_extra,
        "current_shield": min(p.current_shield, p.max_shield + p.growth.max_shield_extra),
        "base_damage": base_damage,
        "move_speed": p.base_move_speed * (1.0 + p.growth.move_speed_pct),
        "pickup_radius": p.base_pickup_radius * (1.0 + p.growth.pickup_radius_pct),
        "crit_chance": min(0.75, p.base_crit_chance + p.growth.crit_chance_bonus),
        "crit_multiplier": max(1.0, p.base_crit_multiplier + p.growth.crit_multiplier_bonus),
        "armor": base_armor,
        "aspd_pct": p.growth.aspd_pct_bonus,
    }


def apply_player_damage(p: Player, *, raw_damage: float, source_id: str, now: float) -> tuple[float, float]:
    """对玩家应用一次伤害（先扣护盾，再扣生命，触发无敌帧）。

    返回 ``(hp_damage, absorbed)``。
    """
    if p.status == PlayerStatus.DEAD or p.status == PlayerStatus.DYING:
        return 0.0, 0.0
    if p.invuln_left > 0:
        return 0.0, 0.0
    absorbed = min(p.current_shield, raw_damage)
    p.current_shield -= absorbed
    remain = raw_damage - absorbed
    p.current_hp = max(0.0, p.current_hp - remain)
    p.damage_taken_total += raw_damage
    p.shield_absorbed_total += absorbed
    p.last_damage_time = now
    p.invuln_left = INVULNERABILITY_DEFAULT
    if p.current_shield <= 0 and p.growth.break_invuln_duration > 0 and p.break_invuln_cd_left <= 0:
        # 不灭屏障：破盾给 1 秒无敌（与常规无敌帧叠加取大）
        p.invuln_left = max(p.invuln_left, p.growth.break_invuln_duration)
        p.break_invuln_cd_left = p.growth.break_invuln_cooldown or 20.0
    if p.current_hp <= 0:
        p.status = PlayerStatus.DYING
        p.death_time = now
    else:
        p.status = PlayerStatus.HIT
    p.debug_damage_log.append({
        "src": source_id,
        "raw": raw_damage,
        "absorbed": absorbed,
        "remain": remain,
        "hp_after": p.current_hp,
        "shield_after": p.current_shield,
        "t": now,
    })
    return remain, absorbed


def heal_player(p: Player, amount: float, *, source: str = "heal") -> float:
    """治疗，返回实际生效量。"""
    if p.status == PlayerStatus.DEAD or p.status == PlayerStatus.DYING:
        return 0.0
    eff = effective_stats(p)
    cap = eff["max_hp"]
    old = p.current_hp
    p.current_hp = min(cap, p.current_hp + amount)
    return p.current_hp - old


def revive_player(p: Player, *, target_hp_pct: float = 0.0) -> None:
    p.status = PlayerStatus.ACTIVE
    p.current_hp = max(1.0, p.base_max_hp * target_hp_pct)
    p.current_shield = 0
    p.invuln_left = 0
    p.break_invuln_cd_left = 0


def player_step(p: Player, dt: float) -> None:
    """每帧更新。"""
    if p.invuln_left > 0:
        p.invuln_left = max(0.0, p.invuln_left - dt)
    if p.break_invuln_cd_left > 0:
        p.break_invuln_cd_left = max(0.0, p.break_invuln_cd_left - dt)
    if p.status == PlayerStatus.HIT:
        # 受击只是短暂表现状态；无敌帧结束后必须回到 ACTIVE。
        # 旧实现永久停在 HIT，生成导演会把玩家视为“非存活”并停止刷怪。
        if p.invuln_left <= 0:
            p.status = PlayerStatus.ACTIVE
    # 护盾再生（非受伤 + RUNNING）
    if p.growth.shield_regen_rate > 0 and p.invuln_left <= 0:
        cap = p.max_shield + p.growth.max_shield_extra
        if p.current_shield < cap:
            p.current_shield = min(cap, p.current_shield + p.growth.shield_regen_rate * dt)
