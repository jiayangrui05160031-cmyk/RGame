"""敌人状态机。

按《怪兽要求》：

    SPAWNING → SEEKING → WINDUP → ATTACKING → RECOVERY → SEEKING → DYING → DEAD
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..core.event_bus import Event, EventBus


class EnemyState(str, Enum):
    SPAWNING = "spawning"
    SEEKING = "seeking"
    WINDUP = "windup"
    ATTACKING = "attacking"
    RECOVERY = "recovery"
    DYING = "dying"
    DEAD = "dead"


@dataclass
class Enemy:
    """敌人实例。

    数值字段为"生成快照"，关卡/时间强化只作用在快照，不在出场后修改。
    """

    entity_id: str
    config_id: str
    archetype: str
    position: tuple[float, float]
    facing: float
    max_hp: float
    current_hp: float
    move_speed: float
    contact_damage: float
    armor: float
    attack_range: float
    attack_interval: float
    windup_time: float
    cooldown_time: float
    collision_radius: float
    state: EnemyState = EnemyState.SPAWNING
    state_left: float = 0.0
    is_elite: bool = False
    elite_affixes: tuple[str, ...] = field(default_factory=tuple)
    time_form: str = "T0"
    base_kill_score: int = 10
    xp_value: int = 1
    drop_table_id: str = "std_drops"
    attack_cooldown_left: float = 0.0
    contact_cooldown_until: float = 0.0
    is_super: bool = False
    tags: tuple[str, ...] = field(default_factory=tuple)
    # 远程投射物参数（仅对 ranged/spreader 启用）
    projectile_speed: float = 0.0
    projectile_lifetime: float = 0.0
    projectile_damage: float = 0.0
    projectile_radius: float = 6.0
    spread_arc_deg: float = 0.0
    spread_projectile_count: int = 1
    ideal_distance: float = 0.0
    strafe_direction: int = 1
    phase_step_cooldown_left: float = 0.0
    phase_flash_left: float = 0.0
    support_cooldown_left: float = 0.0
    support_pulse_left: float = 0.0
    support_target_ids: tuple[str, ...] = field(default_factory=tuple)
    support_amount_pct: float = 0.12
    support_range: float = 250.0
    support_cooldown: float = 5.0
    # 炸弹投放参数
    drops_bomb: bool = False
    bomb_spawn_interval: float = 2.5
    bomb_spawn_cooldown: float = 0.0
    spawn_time: float = 0.0
    last_attack_time: float = 0.0
    attack_target_position: Optional[tuple[float, float]] = None
    pending_defeat: bool = False
    defeat_event_id: Optional[str] = None
    current_target_id: Optional[str] = None


# =============================================================================
# 工厂
# =============================================================================
def _instantiate_snapshot(
    cfg: dict,
    *,
    hp_mul: float,
    dmg_mul: float,
    armor_bonus: float,
    elapsed_min: int,
    endless_cycle: int,
) -> dict:
    """返回生成快照数值。"""
    hp_base = float(cfg.get("max_hp", 1))
    damage_base = float(cfg.get("contact_damage", 0))
    # 时间 / 无尽倍率
    hp_time = 1.10 ** elapsed_min
    dmg_time = 1.06 ** elapsed_min
    hp_endless = 1.20 ** endless_cycle
    dmg_endless = 1.10 ** endless_cycle
    armor_time = 2 * elapsed_min + 4 * endless_cycle

    # 关卡/时间：让 bomb_damage 类参数可选项
    return {
        "max_hp": hp_base * hp_mul * hp_time * hp_endless,
        "contact_damage": damage_base * dmg_mul * dmg_time * dmg_endless,
        "armor": float(cfg.get("armor", 0)) + armor_bonus + armor_time,
    }


def spawn_enemy(
    *,
    config: dict,
    position: tuple[float, float],
    rng,
    time_form: str,
    is_elite: bool = False,
    elite_affixes: tuple[str, ...] = (),
    hp_multiplier: float = 1.0,
    damage_multiplier: float = 1.0,
    armor_bonus: float = 0.0,
    elapsed_min: int = 0,
    endless_cycle: int = 0,
    now: float = 0.0,
) -> Enemy:
    """依据配置与时间快照生成敌人。"""
    snap = _instantiate_snapshot(
        config,
        hp_mul=hp_multiplier,
        dmg_mul=damage_multiplier,
        armor_bonus=armor_bonus,
        elapsed_min=elapsed_min,
        endless_cycle=endless_cycle,
    )
    if is_elite:
        # 精英：生命 2.5 倍（按基准 0 分钟），分数 4 倍
        snap["max_hp"] *= 2.5
        # 不在生成快照中修改 contact_damage，避免精英被基础伤害翻倍
    enemy = Enemy(
        entity_id=f"e_{rng.randint(0, 0xFFFF):04x}_{rng.randint(0, 0xFFFF):04x}",
        config_id=config["id"],
        archetype=config.get("archetype", ""),
        position=position,
        facing=0.0,
        max_hp=snap["max_hp"],
        current_hp=snap["max_hp"],
        move_speed=float(config.get("move_speed", 100)),
        contact_damage=snap["contact_damage"],
        armor=snap["armor"],
        attack_range=float(config.get("attack_range", 50)),
        attack_interval=float(config.get("attack_interval", 1.0)),
        windup_time=float(config.get("windup_time", 0.3)),
        cooldown_time=float(config.get("cooldown_time", 0.5)),
        collision_radius=float(config.get("collision_radius", 16)),
        state=EnemyState.SPAWNING,
        state_left=0.8,  # 0.6–1.0s 出生提示
        is_elite=is_elite,
        elite_affixes=elite_affixes,
        time_form=time_form,
        tags=tuple(config.get("tags", ())),
        base_kill_score=int(config.get("base_kill_score", 10)),
        xp_value=int(config.get("xp_value", 1)),
        drop_table_id=str(config.get("drop_table_id", "std_drops")),
        attack_cooldown_left=0.0,
        projectile_speed=float(config.get("projectile_speed", 0.0)),
        projectile_lifetime=float(config.get("projectile_lifetime", 0.0)),
        projectile_damage=float(config.get("projectile_damage", 0.0)),
        projectile_radius=float(config.get("projectile_radius", 6.0)),
        spread_arc_deg=float(config.get("spread_arc_deg", 0.0)),
        spread_projectile_count=int(config.get("spread_projectile_count", 1)),
        ideal_distance=float(config.get("ideal_distance", 0.0)),
        strafe_direction=1 if rng.random() < 0.5 else -1,
        phase_step_cooldown_left=float(rng.uniform(1.2, 2.5)) if "phase" in config.get("tags", ()) else 0.0,
        support_cooldown_left=float(rng.uniform(0.8, 1.8)) if "support" in config.get("tags", ()) else 0.0,
        support_amount_pct=float(config.get("support_amount_pct", 0.12)),
        support_range=float(config.get("support_range", 250.0)),
        support_cooldown=float(config.get("support_cooldown", 5.0)),
        drops_bomb=bool(config.get("drops_bomb", False)),
        bomb_spawn_interval=float(config.get("bomb_spawn_interval", 2.5)),
        bomb_spawn_cooldown=0.0,
        spawn_time=now,
    )
    return enemy


# =============================================================================
# 推进
# =============================================================================
def step_enemy(
    e: Enemy,
    *,
    dt: float,
    now: float,
    player_pos: tuple[float, float],
    player_alive: bool,
    bombs_active_count: int,
    bus: EventBus,
    projectile_emit,
) -> None:
    """单步推进敌人。

    :param projectile_emit: ``callable(enemy, target_pos)``，由外部 :class:`ProjectileSystem` 处理。
    """
    if e.state == EnemyState.DEAD or e.state == EnemyState.DYING:
        return
    if e.state == EnemyState.SPAWNING:
        e.state_left -= dt
        if e.state_left <= 0:
            e.state = EnemyState.SEEKING
            e.state_left = 0
        return

    dx = player_pos[0] - e.position[0]
    dy = player_pos[1] - e.position[1]
    dist = math.hypot(dx, dy)
    facing_target = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    diff = ((facing_target - e.facing + 540.0) % 360.0) - 180.0
    if not (e.state in (EnemyState.WINDUP, EnemyState.ATTACKING) and e.attack_target_position is not None):
        e.facing = (e.facing + max(-120, min(120, diff * dt * 4)) + 360.0) % 360.0

    if e.attack_cooldown_left > 0:
        e.attack_cooldown_left = max(0.0, e.attack_cooldown_left - dt)
    if e.bomb_spawn_cooldown > 0:
        e.bomb_spawn_cooldown = max(0.0, e.bomb_spawn_cooldown - dt)
    if e.phase_step_cooldown_left > 0:
        e.phase_step_cooldown_left = max(0.0, e.phase_step_cooldown_left - dt)
    if e.phase_flash_left > 0:
        e.phase_flash_left = max(0.0, e.phase_flash_left - dt)
    if e.support_pulse_left > 0:
        e.support_pulse_left = max(0.0, e.support_pulse_left - dt)

    # 以数据能力判断远程兵，不再把可发射兵种写死在两个 archetype 名称中。
    keeps_distance = e.projectile_speed > 0 or e.drops_bomb or "ranged" in e.tags
    shoots_projectiles = e.projectile_speed > 0 and e.projectile_lifetime > 0

    if e.state == EnemyState.SEEKING:
        # 相位潜猎者偶尔从玩家侧前方切入，保留安全距离避免瞬移到碰撞体内。
        if "phase" in e.tags and e.phase_step_cooldown_left <= 0 and 180 <= dist <= 360:
            player_to_enemy = math.atan2(-dy, -dx)
            side = 0.88 * e.strafe_direction
            blink_radius = max(145.0, min(260.0, dist - 68.0))
            blink_angle = player_to_enemy + side
            e.position = (
                player_pos[0] + math.cos(blink_angle) * blink_radius,
                player_pos[1] + math.sin(blink_angle) * blink_radius,
            )
            e.phase_step_cooldown_left = 5.2
            e.phase_flash_left = 0.5
            e.strafe_direction *= -1
            dx = player_pos[0] - e.position[0]
            dy = player_pos[1] - e.position[1]
            dist = math.hypot(dx, dy)
        if e.drops_bomb and bombs_active_count < 3 and e.bomb_spawn_cooldown <= 0 and dist < 380 and dist > 90:
            e.bomb_spawn_cooldown = e.bomb_spawn_interval
            # 投放到玩家与敌人之间（偏移让玩家有机会反应）
            bomb_pos = (
                e.position[0] + (player_pos[0] - e.position[0]) * 0.4,
                e.position[1] + (player_pos[1] - e.position[1]) * 0.4,
            )
            projectile_emit(e, bomb_pos, kind="bomb")
            e.last_attack_time = now
            e.state = EnemyState.SEEKING
        # 远程 vs 近战
        if keeps_distance:
            if dist > e.ideal_distance * 1.2 and dist > 0:
                # 靠近
                norm = dist if dist > 0 else 1.0
                e.position = (
                    e.position[0] + (dx / norm) * e.move_speed * dt,
                    e.position[1] + (dy / norm) * e.move_speed * dt,
                )
            elif dist < e.ideal_distance * 0.7 and dist > 0:
                # 后退
                norm = dist if dist > 0 else 1.0
                e.position = (
                    e.position[0] - (dx / norm) * e.move_speed * 0.6 * dt,
                    e.position[1] - (dy / norm) * e.move_speed * 0.6 * dt,
                )
            if "strafing" in e.tags and dist > 0 and dist < e.ideal_distance * 1.35:
                norm = dist
                strafe_speed = e.move_speed * 0.72 * e.strafe_direction
                e.position = (
                    e.position[0] - (dy / norm) * strafe_speed * dt,
                    e.position[1] + (dx / norm) * strafe_speed * dt,
                )
            if dist <= e.attack_range and e.attack_cooldown_left <= 0 and player_alive:
                e.state = EnemyState.WINDUP
                e.state_left = e.windup_time
                if shoots_projectiles:
                    e.attack_target_position = (player_pos[0], player_pos[1])
                    e.facing = (math.degrees(math.atan2(
                        e.attack_target_position[1] - e.position[1],
                        e.attack_target_position[0] - e.position[0],
                    )) + 360.0) % 360.0
        else:
            # 近战：直线追
            if dist > 0:
                norm = dist
                e.position = (
                    e.position[0] + (dx / norm) * e.move_speed * dt,
                    e.position[1] + (dy / norm) * e.move_speed * dt,
                )
            if dist <= e.attack_range and e.attack_cooldown_left <= 0 and player_alive:
                e.state = EnemyState.WINDUP
                e.state_left = e.windup_time
    elif e.state == EnemyState.WINDUP:
        e.state_left -= dt
        if e.state_left <= 0:
            # 锁定前摇结束时的方向 / 位置
            dx = player_pos[0] - e.position[0]
            dy = player_pos[1] - e.position[1]
            dist = math.hypot(dx, dy)
            if dist > e.attack_range * 1.05:
                # 目标已离开范围：取消前摇（可挥空）
                e.state = EnemyState.RECOVERY
                e.state_left = 0.4
                e.attack_cooldown_left = e.attack_interval
                e.attack_target_position = None
            else:
                e.state = EnemyState.ATTACKING
                e.state_left = 0.06
    elif e.state == EnemyState.ATTACKING:
        e.state_left -= dt
        if e.state_left <= 0:
            # 真实结算
            dx = player_pos[0] - e.position[0]
            dy = player_pos[1] - e.position[1]
            dist = math.hypot(dx, dy)
            if dist <= e.attack_range:
                if shoots_projectiles:
                    # 使用前摇开始时锁定的位置，预警线因此是真实可闪避的。
                    target_pos = e.attack_target_position or (player_pos[0], player_pos[1])
                    projectile_emit(e, target_pos, kind="projectile")
                    e.last_attack_time = now
                    if "strafing" in e.tags:
                        e.strafe_direction *= -1
                else:
                    # 近战接触：先看无敌 / 接触冷却
                    e.last_attack_time = now
            e.state = EnemyState.RECOVERY
            e.state_left = e.cooldown_time
            e.attack_cooldown_left = e.attack_interval
            e.attack_target_position = None
    elif e.state == EnemyState.RECOVERY:
        e.state_left -= dt
        if e.state_left <= 0:
            e.state = EnemyState.SEEKING
            e.state_left = 0
            e.attack_target_position = None
