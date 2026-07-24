"""掉落域：有利/危险掉落、炸弹、3 秒寿命、防连出、合并。"""

from .drops import (
    Pickup,
    HazardBomb,
    PickupKind,
    DropSystem,
    create_drop_system,
    spawn_drops_on_enemy_defeated,
)

__all__ = [
    "Pickup",
    "HazardBomb",
    "PickupKind",
    "DropSystem",
    "create_drop_system",
    "spawn_drops_on_enemy_defeated",
]
