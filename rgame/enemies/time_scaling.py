"""敌人 / 关卡 / 时间 / 无尽循环的强化公式。

按《关卡与计分系统》§4, §5：

- 关卡倍率 + 时间倍率 + 无尽循环倍率；
- 玩家被动成长（每分钟 1.02/1.015/0.5 armor）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class StageModifiers:
    hp_multiplier: float
    damage_multiplier: float
    armor_bonus: float
    spawn_budget_multiplier: float
    elite_chance: float
    clear_score: int | None
    visual_tier: str


def stage_modifiers(
    *,
    stage_index: int,
    endless_cycle: int,
    elapsed_minutes: int,
    stage_cfg: dict,
) -> StageModifiers:
    """返回当前阶段与时间快照下的强化参数。"""
    if stage_cfg.get("id") == "endless":
        hp = 2.80
        dmg = 1.80
        arm = 18
        budget = 1.60
        elite_base = 0.12
        max_elite = 0.35
        visual = "VX" if endless_cycle > 0 else "V3"
    else:
        hp = float(stage_cfg.get("hp_multiplier", 1.0))
        dmg = float(stage_cfg.get("damage_multiplier", 1.0))
        arm = int(stage_cfg.get("armor_bonus", 0))
        budget = float(stage_cfg.get("spawn_budget_multiplier", 1.0))
        elite_base = float(stage_cfg.get("elite_base_chance", 0.02))
        max_elite = float(stage_cfg.get("max_elite_chance", 0.25))
        visual = ["V0", "V0", "V1", "V2"][min(stage_index, 3)]
    # 时间 / 无尽倍率
    hp *= 1.10 ** elapsed_minutes
    dmg *= 1.06 ** elapsed_minutes
    arm += 2 * elapsed_minutes
    budget *= 1.08 ** elapsed_minutes
    if endless_cycle > 0:
        hp *= 1.20 ** endless_cycle
        dmg *= 1.10 ** endless_cycle
        arm += 4 * endless_cycle
        budget *= 1.08 ** endless_cycle
    # 精英概率
    elite = min(max_elite, elite_base + 0.02 * (elapsed_minutes // 2))
    return StageModifiers(
        hp_multiplier=hp,
        damage_multiplier=dmg,
        armor_bonus=arm,
        spawn_budget_multiplier=budget,
        elite_chance=elite,
        clear_score=stage_cfg.get("clear_score"),
        visual_tier=visual,
    )


def enemy_spawned_snapshot(cfg: dict, mods: StageModifiers) -> dict:
    """把敌人配置套上当前强化，得到生成快照。"""
    hp_base = float(cfg.get("max_hp", 1))
    dmg_base = float(cfg.get("contact_damage", 0))
    return {
        "max_hp": hp_base * mods.hp_multiplier,
        "contact_damage": dmg_base * mods.damage_multiplier,
        "armor": float(cfg.get("armor", 0)) + mods.armor_bonus,
        "xp_value": cfg.get("xp_value", 1),
        "base_kill_score": cfg.get("base_kill_score", 10),
    }


def elite_bonus_score(base_score: int) -> int:
    """精英结算分数倍率 4。"""
    return base_score * 4


def time_visual_tier(stage_index: int, endless_cycle: int) -> str:
    if endless_cycle > 0:
        return "VX"
    return ["V0", "V0", "V1", "V2"][min(stage_index, 3)]


def enemy_stat_multiplier(mods: StageModifiers) -> float:
    """返回用于伤害/生命同时放大的乘积（便于引用）。"""
    return mods.hp_multiplier


# =============================================================================
# 玩家被动成长
# =============================================================================
def player_passive_growth_for_minute(minute: int) -> dict:
    """按《关卡与计分系统》§6：

    - 基础最大生命倍率 ×1.02；
    - 基础攻击倍率 ×1.015；
    - 基础护甲 +0.5。

    注意：实际战斗有怪兽 50% 上限。
    """
    return {
        "max_hp_pct": 1.02 ** minute,
        "damage_pct": 1.015 ** minute,
        "armor_flat": 0.5 * minute,
    }
