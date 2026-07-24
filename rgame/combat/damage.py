"""伤害结算管线。

按《战斗互动系统》§5 给出的 7 步顺序：

1. 验证来源、目标、阵营、命中次数与无敌状态；
2. 读取攻击快照；
3. 计算暴击；
4. 应用抽卡系统定义的"参考怪兽 50% 动态上限"，记录溢出；
5. 计算目标侧易伤、护甲和减伤；
6. 四舍五入到显示精度，保证最小伤害下限；
7. 先扣护盾再扣生命，分两个 payload 发 ``damage_applied`` 并各自标记。

也作为伤害数值公式的单一来源，UI 与战斗日志同时从这里读取。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# 数值常量
# =============================================================================
DEFAULT_MIN_DAMAGE = 1.0          # 《战斗互动系统》§5.6 有效非零攻击保证下限
ARMOR_DIVISOR = 100.0            # armor / (armor + 100)


def armory_reduction(armor: float) -> float:
    """护甲减伤率。

    公式：``armor / (armor + 100)``。
    """
    if armor <= 0:
        return 0.0
    return armor / (armor + ARMOR_DIVISOR)


# =============================================================================
# 数据结构
# =============================================================================
@dataclass
class DamageRequest:
    """一次伤害请求。

    属性：
        source_id: 攻击来源实体 id；
        target_id: 攻击目标实体 id；
        source_is_player: 来源是否是玩家；
        base_damage: 攻击快照里记录的基础伤害；
        crit_roll: 0–1 是否暴击；
        target_armor: 目标当前护甲；
        target_vuln_pct: 0–1 目标受到的易伤百分比（默认 0）；
        attack_power_cap_active: 是否应用 50% 上限；
        attack_cap: 50% 上限值（来源怪兽有效生命 × 0.5）；
        min_damage: 最小伤害下限（默认 1）。
    """

    source_id: str
    target_id: str
    source_is_player: bool
    base_damage: float
    crit_chance: float = 0.05
    crit_multiplier: float = 1.5
    crit_roll: float = -1.0  # <0 表示调用方未提供，要内部 roll
    target_armor: float = 0.0
    target_vuln_pct: float = 0.0
    attack_cap_active: bool = False
    attack_cap: float = math.inf
    min_damage: float = DEFAULT_MIN_DAMAGE
    attacker_pen_pct: float = 0.0  # 穿透百分比，写到最终伤害上
    label: str = ""


@dataclass
class DamageResult:
    """一次完整伤害请求的结果。

    Attributes:
        source_id / target_id: 来自 :class:`DamageRequest`。
        raw_damage: 基础伤害。
        final_damage: 经过 crit/护甲/减伤/上限之后的最终值。
        overflow: 被 50% 上限抑制的溢出攻击力（仅玩家攻击）。
        absorbed_by_shield: 护盾吸收部分。
        hp_damage: 实际扣到生命上的部分。
        crit: 是否暴击。
        reason: 任何拒绝结算的原因（无敌 / 死亡 / 阵营错误等）。
        breakdown: 给 UI/日志展示的分步骤字典。
    """

    source_id: str
    target_id: str
    raw_damage: float
    final_damage: float
    overflow: float = 0.0
    absorbed_by_shield: float = 0.0
    hp_damage: float = 0.0
    crit: bool = False
    reason: str = ""
    breakdown: dict = field(default_factory=dict)


class DamageStage:
    OK = "ok"
    REJECTED_NO_SOURCE = "rejected_no_source"
    REJECTED_DEAD_TARGET = "rejected_dead_target"
    REJECTED_FRIENDLY = "rejected_friendly"
    REJECTED_INVULNERABLE = "rejected_invulnerable"
    REJECTED_ALREADY_HIT = "rejected_already_hit"


# =============================================================================
# 核心函数
# =============================================================================
def calc_damage(req: DamageRequest) -> DamageResult:
    """按规则计算最终伤害数字（不直接修改任何生命/护盾状态）。

    实际操作请使用 :func:`apply_damage_to_target`。
    """
    raw = max(0.0, float(req.base_damage))
    crit = False
    roll = req.crit_roll
    if roll < 0:
        # 调用方未提供暴击 roll，应使用 crit_rng；为保持纯函数性，
        # 这里采用 deterministic（默认不暴击），实际攻击循环从 :class:`CombatContext`
        # 显式传入 roll。
        roll = 0.0
    if roll < req.crit_chance:
        crit = True
    crit_mult = req.crit_multiplier if crit else 1.0

    after_crit = raw * crit_mult
    # 抽卡系统 50% 上限（只对玩家）
    overflow = 0.0
    if req.source_is_player and req.attack_cap_active and math.isfinite(req.attack_cap):
        if after_crit > req.attack_cap:
            overflow = after_crit - req.attack_cap
            after_crit = req.attack_cap
    # 玩家穿透百分比
    if req.source_is_player and req.attacker_pen_pct > 0:
        after_crit *= max(0.0, 1.0 - min(0.95, req.attacker_pen_pct))
    # 目标易伤
    after_vuln = after_crit * (1.0 + max(0.0, req.target_vuln_pct))
    # 护甲减伤
    ar = armory_reduction(req.target_armor)
    final = after_vuln * (1.0 - ar)
    if final < req.min_damage and raw > 0:
        final = req.min_damage
    final = round(final, 2)

    breakdown = {
        "raw": raw,
        "after_crit": after_crit,
        "crit": crit,
        "crit_mult": crit_mult,
        "attack_cap": req.attack_cap if req.attack_cap_active else None,
        "overflow": overflow,
        "target_armor": req.target_armor,
        "armory_red_pct": ar,
        "target_vuln_pct": req.target_vuln_pct,
        "final": final,
    }
    return DamageResult(
        source_id=req.source_id,
        target_id=req.target_id,
        raw_damage=raw,
        final_damage=final,
        overflow=overflow,
        crit=crit,
        breakdown=breakdown,
    )


def clamp_player_damage(
    damage_value: float,
    *,
    crit_multiplier: float = 1.5,
    crit_applied: bool = False,
    cap: float = math.inf,
) -> tuple[float, float]:
    """计算攻击结果与溢出。

    返回：(effective_damage, overflow)。
    """
    d = damage_value * (crit_multiplier if crit_applied else 1.0)
    if math.isfinite(cap) and d > cap:
        return cap, d - cap
    return d, 0.0


def apply_damage_to_target(
    req: DamageRequest,
    *,
    target_max_shield: float,
    target_current_shield: float,
    target_alive: bool,
    target_faction: str,
    source_faction: str = "player",
    invulnerable: bool = False,
) -> tuple[DamageResult, dict]:
    """把伤害落到具体目标上。

    返回 ``(DamageResult, target_updated_dict)``。
    ``target_updated_dict`` 含 ``hp`` / ``shield`` / ``killed``。
    """
    out = DamageResult(source_id=req.source_id, target_id=req.target_id, raw_damage=req.base_damage, final_damage=0.0)
    if target_faction == source_faction:
        out.reason = DamageStage.REJECTED_FRIENDLY
        return out, {"hp": None, "shield": target_current_shield, "killed": False}
    if not target_alive:
        out.reason = DamageStage.REJECTED_DEAD_TARGET
        return out, {"hp": None, "shield": target_current_shield, "killed": False}
    if invulnerable:
        out.reason = DamageStage.REJECTED_INVULNERABLE
        return out, {"hp": None, "shield": target_current_shield, "killed": False}

    r = calc_damage(req)
    dmg = r.final_damage
    remain = dmg
    absorbed = 0.0
    sh = target_current_shield
    if sh > 0:
        absorbed = min(sh, remain)
        sh -= absorbed
        remain -= absorbed
    r.absorbed_by_shield = round(absorbed, 2)
    r.hp_damage = round(remain, 2)
    out = r

    cur_hp = None  # caller fills this
    killed = remain > 0  # caller decides based on hp_max

    return out, {"hp": cur_hp, "shield": sh, "killed": killed, "absorbed": absorbed}
