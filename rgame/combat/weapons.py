"""武器循环。

按《战斗互动系统》§4 +《武器切换系统》：

- READY → ACQUIRE_TARGET → WINDUP → FIRE/HIT → COOLDOWN → READY；
- 玩家武器栈最多 3 把，仅 ``active_weapon`` 自动索敌、自动攻击；
- 切换延迟基准 0.25 秒，剩余冷却保存；新武器应用延迟；非激活武器冷却冻结。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .targeting import TargetingSystem, TargetCandidate
from .damage import DamageRequest


EQUIP_DELAY = 0.25  # 《武器切换系统》§4
MIN_ATTACK_INTERVAL = 0.12  # 《战斗互动系统》§4 下限


class WeaponPhase(str, Enum):
    READY = "ready"
    ACQUIRE = "acquire"
    WINDUP = "windup"
    FIRE = "fire"
    COOLDOWN = "cooldown"
    EQUIPPING = "equipping"
    DISABLED = "disabled"


@dataclass
class WeaponState:
    """单把武器的局内状态。"""

    weapon_id: str
    config: dict
    phase: WeaponPhase = WeaponPhase.READY
    cooldown_left: float = 0.0
    windup_left: float = 0.0
    equip_left: float = 0.0          # 0.25s 切换延迟
    target: Optional[str] = None
    targeting: Optional[TargetingSystem] = None
    level: int = 1
    rarity: str = "common"
    max_level: int = 6
    breakthrough_unlocked: bool = False
    extra_projectiles: int = 0
    extra_projectile_dmg_share: float = 0.45
    # 卡牌影响范围
    dmg_pct_bonus: float = 0.0
    aspd_pct_bonus: float = 0.0
    range_pct_bonus: float = 0.0
    arc_deg_bonus: float = 0.0
    tol_deg_bonus: float = 0.0
    attack_speed_multiplier: float = 1.0
    damage_multiplier: float = 1.0
    base_damage_boost: float = 0.0  # 来自合成卡 / 升级 / 武器共鸣
    crit_chance_bonus: float = 0.0
    crit_multiplier_bonus: float = 0.0
    penetration_bonus: int = 0
    extra_proj_capped_at: int = 6

    def interval(self) -> float:
        base = float(self.config.get("attack_interval", 0.5))
        spd = max(0.05, self.attack_speed_multiplier * (1.0 + self.aspd_pct_bonus))
        iv = base / spd
        return max(MIN_ATTACK_INTERVAL, iv)

    def sense(self) -> float:
        base = float(self.config.get("sense_radius", 300))
        # 射程卡必须同步扩大索敌范围，否则只改 attack_range 会因看不见目标而无效。
        return max(base * (1.0 + max(0.0, self.range_pct_bonus)), self.attack_range() * 1.08)

    def attack_range(self) -> float:
        base = float(self.config.get("attack_range", 200))
        return base * (1.0 + max(0.0, self.range_pct_bonus))

    def fire_tolerance(self) -> float:
        base = float(self.config.get("fire_tolerance_deg", 12))
        arc = float(self.config.get("attack_arc_deg", 90))
        return min(base + self.tol_deg_bonus, 35.0 if arc <= 90 else 120.0)

    def base_damage(self) -> float:
        return float(self.config.get("base_damage", 10)) * (1.0 + self.dmg_pct_bonus) * self.damage_multiplier + self.base_damage_boost


@dataclass
class WeaponSystem:
    """玩家武器栈管理。

    玩家最多持有 3 把；激活武器唯一；切换按 LIFO 与 A→B→C→A 循环。
    """

    stack: list[WeaponState] = field(default_factory=list)
    active_index: int = -1
    last_switch_time: float = -1.0
    can_switch_lock_left: float = 0.0  # 全局切换按钮 0.25 秒冷却
    max_weapons: int = 3

    # ---- 初始化 ----------------------------------------------------------

    def populate(self, weapon_configs: list[dict], active_weapon_id: str | None = None) -> None:
        self.stack = [
            WeaponState(
                weapon_id=c["id"],
                config=c,
                rarity=str(c.get("rarity", "common")),
                max_level=int(c.get("max_level", 6)),
            )
            for c in weapon_configs
        ]
        self.max_weapons = 3
        if not self.stack:
            self.active_index = -1
        else:
            if active_weapon_id:
                idx = self._index_of(active_weapon_id)
                self.active_index = idx if idx >= 0 else 0
            else:
                self.active_index = 0
            if self.active_index >= 0:
                self.stack[self.active_index].phase = WeaponPhase.READY

    # ---- 状态查询 --------------------------------------------------------

    @property
    def active(self) -> WeaponState | None:
        if 0 <= self.active_index < len(self.stack):
            return self.stack[self.active_index]
        return None

    def _index_of(self, weapon_id: str) -> int:
        for i, w in enumerate(self.stack):
            if w.weapon_id == weapon_id:
                return i
        return -1

    # ---- 武器切换 --------------------------------------------------------

    def request_switch(self) -> bool:
        """玩家按 Q / 切换按钮。

        仅在 ``RUNNING`` + 持有 ≥2 把 + 不在锁定冷却期 才会真正切换。
        返回是否发生切换。
        """
        if len(self.stack) < 2:
            return False
        return self.request_select((self.active_index + 1) % len(self.stack))

    def request_select(self, index: int) -> bool:
        """直接装备指定槽位，供鼠标点击武器栏使用。"""
        if not (0 <= index < len(self.stack)) or index == self.active_index:
            return False
        if self.can_switch_lock_left > 0:
            return False
        old = self.stack[self.active_index]
        old.target = None
        old.targeting = None
        # 取消前摇攻击
        if old.phase == WeaponPhase.WINDUP:
            old.phase = WeaponPhase.READY
        # 找到下一把合法武器
        self.active_index = index
        new = self.stack[self.active_index]
        new.phase = WeaponPhase.EQUIPPING
        new.equip_left = EQUIP_DELAY
        self.can_switch_lock_left = EQUIP_DELAY
        return True

    def step_lock_cooldown(self, dt: float) -> None:
        if self.can_switch_lock_left > 0:
            self.can_switch_lock_left = max(0.0, self.can_switch_lock_left - dt)

    # ---- 武器增减 -------------------------------------------------------

    def gain_weapon(self, weapon_config: dict) -> tuple[WeaponState, str | None, bool]:
        """获得新武器，按 LIFO 规则处理。

        返回 (new_weapon_state, discarded_weapon_id or None, was_active)。
        """
        new_w = WeaponState(
            weapon_id=weapon_config["id"],
            config=weapon_config,
            rarity=str(weapon_config.get("rarity", "common")),
            max_level=int(weapon_config.get("max_level", 6)),
        )
        discarded = None
        was_active = False
        if len(self.stack) >= self.max_weapons:
            # LIFO：弹出栈顶（最近一次获得）
            top = self.stack.pop()
            discarded = top.weapon_id
            if top.phase in (WeaponPhase.WINDUP, WeaponPhase.FIRE, WeaponPhase.READY):
                # 直接砍断：丢弃的武器正在打就让它继续用快照结算（不再发射新东西）
                pass
            if self.active_index >= len(self.stack):
                self.active_index = max(0, len(self.stack) - 1)
        self.stack.append(new_w)
        # 新武器自动激活
        self.active_index = len(self.stack) - 1
        new_w.phase = WeaponPhase.EQUIPPING
        new_w.equip_left = EQUIP_DELAY
        self.can_switch_lock_left = EQUIP_DELAY
        return new_w, discarded, was_active


# =============================================================================
# 主循环：weapon_tick
# =============================================================================
def weapon_tick(
    ws: WeaponSystem,
    *,
    dt: float,
    now: float,
    candidates: list[TargetCandidate],
    attacker_pos: tuple[float, float],
    attacker_facing_deg: float,
    can_attack: bool,
    crit_rng_roll: float,
    projectile_emit,
) -> list[dict]:
    """推进武器状态机；返回需要外部发射的``emits``列表。

    :param projectile_emit: ``callable(weapon_id, snapshot, target_id, target_pos)``，
        由外部 :class:`ProjectileSystem` 接收来创建投射物。
    """
    emits: list[dict] = []
    if not ws.active:
        return emits

    w = ws.active
    ws.step_lock_cooldown(dt)

    if w.phase == WeaponPhase.DISABLED:
        return emits
    if w.phase == WeaponPhase.EQUIPPING:
        w.equip_left = max(0.0, w.equip_left - dt)
        if w.equip_left <= 0:
            w.phase = WeaponPhase.READY
        return emits
    if not can_attack:
        w.phase = WeaponPhase.ACQUIRE
        return emits

    sense = w.sense()
    range_ = w.attack_range()
    tol = w.fire_tolerance()
    arc = float(w.config.get("attack_arc_deg", 90))

    if w.targeting is None:
        w.targeting = TargetingSystem(sense_radius=sense, target_fov_deg=360.0)
    else:
        # 卡牌可在战斗中动态改变射程，缓存的索敌器也要立即更新。
        w.targeting.sense_radius = sense

    # 推进相机的面向：默认随最近朝向；如果有目标，逐步转向。
    if w.targeting.cooldown_left > 0:
        w.targeting.step_cooldown(dt)

    if w.phase == WeaponPhase.READY:
        # 进行一次索敌
        target = w.targeting.acquire(
            attacker_pos=attacker_pos,
            attacker_facing_deg=attacker_facing_deg,
            candidates=candidates,
            current_time=now,
            attack_range=range_,
        )
        if target is None:
            return emits
        w.target = target.entity_id
        if w.phase == WeaponPhase.READY:
            w.windup_left = float(w.config.get("windup_time", 0.10))
            w.phase = WeaponPhase.WINDUP
    # WINDUP
    if w.phase == WeaponPhase.WINDUP:
        # 目标是否仍合法 / 进入开火容差
        cand = next((c for c in candidates if c.entity_id == w.target), None)
        if cand is None or not cand.alive or cand.faction != "enemy":
            w.phase = WeaponPhase.READY
            return emits
        d_to = ((cand.position[0] - attacker_pos[0]) ** 2 + (cand.position[1] - attacker_pos[1]) ** 2) ** 0.5
        if d_to > sense * 1.15:
            w.phase = WeaponPhase.READY
            return emits
        # 是否完成 windup
        w.windup_left -= dt
        if w.windup_left <= 0:
            # 进入 FIRE：在 FIRE 内创建 projectile，然后立即进入 COOLDOWN
            dmg = w.base_damage()
            snapshot = {
                "weapon_id": w.weapon_id,
                "damage": dmg,
                "crit_chance": min(0.75, float(w.config.get("crit_chance", 0.05)) + w.crit_chance_bonus),
                "crit_multiplier": max(1.0, float(w.config.get("crit_multiplier", 1.5)) + w.crit_multiplier_bonus),
                "crit_roll": crit_rng_roll,
                "projectile_count": int(w.config.get("projectile_count", 1)) + w.extra_projectiles,
                "penetration": int(w.config.get("penetration", 1)) + w.penetration_bonus,
                "is_melee": bool(w.config.get("is_melee", False)),
                "omnidirectional": bool(w.config.get("omnidirectional", False)),
                "arc_deg": arc + w.arc_deg_bonus,
                "tolerance_deg": tol,
                "projectile_speed": float(w.config.get("projectile_speed", 0)),
                "projectile_lifetime": float(w.config.get("projectile_lifetime", 0)),
                "attack_range": range_,
                "sense_radius": sense,
                "extra_dmg_share": w.extra_projectile_dmg_share,
                "level": w.level,
            }
            projectile_emit(snapshot, cand, attacker_pos, attacker_facing_deg)
            emits.append({"weapon_id": w.weapon_id, "target_id": cand.entity_id})
            w.phase = WeaponPhase.COOLDOWN
            w.cooldown_left = max(MIN_ATTACK_INTERVAL, w.interval())
    elif w.phase == WeaponPhase.COOLDOWN:
        w.cooldown_left -= dt
        if w.cooldown_left <= 0:
            w.cooldown_left = 0
            w.phase = WeaponPhase.READY
    return emits
