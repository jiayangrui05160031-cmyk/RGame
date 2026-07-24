"""玩家域：属性、状态、移动、输入抽象、成长接口。"""

from .player import (
    Player,
    PlayerStatus,
    apply_player_damage,
    heal_player,
    revive_player,
    effective_stats,
    player_step,
    PlayerGrowthSource,
)
from .input_provider import (
    InputAction,
    InputProvider,
    KeyboardInputProvider,
    TouchInputProvider,
    CompositeInputProvider,
)
from .movement import (
    normalize_move,
    apply_movement,
    clamp_to_playable_bounds,
)

__all__ = [
    "Player",
    "PlayerStatus",
    "apply_player_damage",
    "heal_player",
    "revive_player",
    "effective_stats",
    "player_step",
    "PlayerGrowthSource",
    "InputAction",
    "InputProvider",
    "KeyboardInputProvider",
    "TouchInputProvider",
    "CompositeInputProvider",
    "normalize_move",
    "apply_movement",
    "clamp_to_playable_bounds",
]
