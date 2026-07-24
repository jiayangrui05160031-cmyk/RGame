"""战斗域：伤害管线、武器自动索敌/前摇/冷却、投射物。"""

from .damage import (
    DamageRequest,
    DamageResult,
    DamageStage,
    apply_damage_to_target,
    calc_damage,
    armory_reduction,
    clamp_player_damage,
)
from .targeting import TargetingSystem, choose_target
from .weapons import WeaponSystem, WeaponState, weapon_tick
from .projectiles import ProjectileSystem, Projectile

__all__ = [
    "DamageRequest",
    "DamageResult",
    "DamageStage",
    "apply_damage_to_target",
    "calc_damage",
    "armory_reduction",
    "clamp_player_damage",
    "TargetingSystem",
    "choose_target",
    "WeaponSystem",
    "WeaponState",
    "weapon_tick",
    "ProjectileSystem",
    "Projectile",
]
