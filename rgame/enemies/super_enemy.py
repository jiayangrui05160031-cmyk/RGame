"""超级怪兽系统：由引擎按分数门槛排队，1 秒警告与多形态非指向技能。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .enemies import Enemy, EnemyState, spawn_enemy
from .spawn_director import Sector
from ..core.event_bus import Event, EventBus
from ..core.run_context import RunContext


SUPER_BASE_HEALTH_MULT = 18.0


class SuperSkill(str, Enum):
    FIVE_FAN = "five_fan"          # 五向扇射
    THREE_BOMB = "three_bomb"      # 三连地爆
    GAP_RING = "gap_ring"          # 缺口环射
    LOCKED_DASH = "locked_dash"    # 锁向重冲
    EXPAND_RING = "expand_ring"    # 扩张冲击环
    TRI_LASER = "tri_laser"        # 锁定方向的三线棱镜炮
    VOID_TIDAL = "void_tidal"      # 旋转安全缺口的潮汐弹幕


SUPER_SKILLS_BASE = {
    SuperSkill.FIVE_FAN: 0.9,
    SuperSkill.THREE_BOMB: 1.1,
    SuperSkill.GAP_RING: 1.0,
    SuperSkill.LOCKED_DASH: 0.8,
    SuperSkill.EXPAND_RING: 1.2,
    SuperSkill.TRI_LASER: 1.18,
    SuperSkill.VOID_TIDAL: 1.0,
}

SUPER_SKILL_MIN_WINDUP = 0.6  # 0.6s 下限


@dataclass
class SuperEnemy:
    enemy: Enemy
    index_in_run: int                 # 第几只，从 1 起
    reference_archetype: str          # 选中的参考原型
    skill_pool: list[SuperSkill] = field(default_factory=list)
    skill_used_history: list[SuperSkill] = field(default_factory=list)
    skill_windup_left: float = 0.0
    skill_active_left: float = 0.0
    skill_recovery_left: float = 0.0
    current_skill: Optional[SuperSkill] = None
    in_warning: bool = False
    is_super: bool = True
    reference_health: float = 0.0
    reference_damage: float = 0.0
    reference_armor: float = 0.0
    super_health: float = 0.0
    super_damage: float = 0.0
    super_armor: float = 0.0
    super_kill_score: int = 0
    spawn_time: float = 0.0
    defeated: bool = False
    spawn_protect_left: float = 0.0  # 0.3s 出生保护
    dash_direction: tuple[float, float] = (0.0, 0.0)
    skill_fired: bool = False
    skill_wave_timer: float = 0.0
    skill_wave_index: int = 0
    skill_aim_angle: float = 0.0
    enraged: bool = False
    phase: int = 1
    break_gauge: float = 0.0
    break_gauge_max: float = 120.0
    broken_left: float = 0.0
    weakpoint_angle: float = 0.0


@dataclass
class SuperEnemyDirector:
    """超级怪兽的全局导演。"""

    queued: int = 0                     # 待生成数量
    progress: int = 0                   # 兼容旧击杀进度；当前 Boss 触发由引擎按分数控制
    cooldown: float = 0.0               # 两次警告至少 8 秒
    active: Optional[SuperEnemy] = None
    warning_left: float = 0.0
    next_index: int = 1                 # 第几只
    required_kills: int = 30            # 兼容旧进度 UI/测试；不再驱动首只 Boss 强制出现

    def reset(self) -> None:
        self.queued = 0
        self.progress = 0
        self.cooldown = 0.0
        self.active = None
        self.warning_left = 0.0
        self.next_index = 1
        self.required_kills = 30

    # ---- 进度推进 -------------------------------------------------------

    def on_eligible_kill(self, *, now: float) -> bool:
        """普通/精英的合法计分击杀会调用；返回是否触发阈值。"""
        # 已经排队的巨兽应先登场，避免同一帧批量结算继续灌入进度。
        if self.queued > 0:
            return False
        self.progress += 1
        if self.progress >= self.required_kills:
            self.progress -= self.required_kills
            self.queued += 1
            self.required_kills = 75
            return True
        return False

    # ---- 警告/生成 -----------------------------------------------------

    def can_warn(self, run_context: RunContext) -> bool:
        return (
            self.queued > 0
            and self.active is None
            and self.cooldown <= 0.0
            and run_context.state_machine.current.name == "RUNNING"
        )

    def start_warning(self, *, duration: float = 1.0) -> None:
        self.warning_left = duration
        self.queued -= 1
        self.cooldown = 8.0  # 至少 8 秒间隔

    def tick_warning(self, dt: float) -> bool:
        if self.warning_left <= 0:
            return False
        self.warning_left -= dt
        if self.warning_left <= 0:
            return True
        return False

    # ---- 生成真实超级怪兽 ---------------------------------------------

    def spawn(
        self,
        *,
        run_context: RunContext,
        reference_enemy_cfg: dict,
        reference_snapshot: dict,
        reference_archetype: str,
        position: tuple[float, float],
    ) -> SuperEnemy:
        i = self.next_index
        self.next_index += 1
        e = spawn_enemy(
            config=reference_enemy_cfg,
            position=position,
            rng=run_context.rng.get("super_rng"),
            time_form="T3",
            is_elite=False,
            hp_multiplier=SUPER_BASE_HEALTH_MULT * (1.12 ** (i - 1)),
            damage_multiplier=2.30 * (1.08 ** (i - 1)),
            armor_bonus=24 + 4 * (i - 1),
            elapsed_min=0,  # 快照只反映参考原型的当前关卡/时间
            endless_cycle=run_context.endless_cycle,
            now=run_context.timer.run_time,
        )
        # 取消"自带的生命/伤害再次加" —— 用刚才的快照值
        e.max_hp = reference_snapshot["max_hp"] * SUPER_BASE_HEALTH_MULT * (1.12 ** (i - 1))
        e.current_hp = e.max_hp
        e.contact_damage = reference_snapshot["contact_damage"] * 2.30 * (1.08 ** (i - 1))
        e.armor = float(reference_snapshot.get("armor", 0)) + 24 + 4 * (i - 1)
        e.base_kill_score = 120 + 20 * (i - 1)
        e.collision_radius = 64
        e.move_speed = max(115.0, e.move_speed * 0.9)
        e.drops_bomb = False
        e.is_elite = False
        # The combat, scoring and weakpoint paths inspect the Enemy instance.
        e.is_super = True
        e.state = EnemyState.SEEKING
        e.state_left = 0.0
        # 初始化技能池
        # 首只就开放完整技能池，避免连续几场只看到同一种开场弹幕。
        chosen = list(SuperSkill)
        super_e = SuperEnemy(
            enemy=e,
            index_in_run=i,
            reference_archetype=reference_archetype,
            skill_pool=chosen,
            reference_health=reference_snapshot["max_hp"],
            reference_damage=reference_snapshot["contact_damage"],
            reference_armor=reference_snapshot.get("armor", 0),
            super_health=e.max_hp,
            super_damage=e.contact_damage,
            super_armor=e.armor,
            super_kill_score=e.base_kill_score,
            spawn_time=run_context.timer.run_time,
            spawn_protect_left=0.3,
            weakpoint_angle=run_context.rng.get("super_rng").uniform(0, math.tau),
        )
        self.active = super_e
        return super_e

    # ---- 技能选择 -------------------------------------------------------

    def choose_next_skill(self, super_e: SuperEnemy, rng=None) -> SuperSkill:
        """根据《超级怪兽系统》§6 规则：

        - 第 1 只随机获 2 个技能；
        - 第 3、5 只 +1，上限 4；
        - 同一技能不能连续使用超过 2 次。
        """
        i = super_e.index_in_run
        target_count = 2
        if i >= 3:
            target_count += 1
        if i >= 5:
            target_count += 1
        target_count = min(4, target_count)
        if len(super_e.skill_pool) < target_count:
            all_skills = list(SuperSkill)
            for s in all_skills:
                if s not in super_e.skill_pool:
                    super_e.skill_pool.append(s)
                    if len(super_e.skill_pool) >= target_count:
                        break
        # 不能连续 2 次用同一技能
        hist = super_e.skill_used_history[-2:]
        pool = [s for s in super_e.skill_pool if not (len(hist) == 2 and hist[0] == hist[1] == s)]
        if not pool:
            pool = super_e.skill_pool
        # 使用本局命名随机流，保证回放种子能复现 Boss 招式序列。
        if len(pool) == 1:
            return pool[0]
        if rng is not None:
            return rng.choices(pool, k=1)[0]
        return random.choice(pool)

    def on_skill_used(self, super_e: SuperEnemy, skill: SuperSkill) -> None:
        super_e.skill_used_history.append(skill)
        if len(super_e.skill_used_history) > 8:
            super_e.skill_used_history = super_e.skill_used_history[-8:]

    def on_defeated(self) -> None:
        if self.active is not None:
            self.active.defeated = True
        self.active = None
