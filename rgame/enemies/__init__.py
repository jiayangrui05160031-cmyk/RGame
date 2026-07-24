"""敌人域：原型、状态机、生成导演、超级怪兽。"""

from .enemies import (
    Enemy,
    EnemyState,
    spawn_enemy,
    step_enemy,
)
from .spawn_director import SpawnDirector, Sector, ENEMY_HARD_CAP
from .time_scaling import (
    stage_modifiers,
    enemy_spawned_snapshot,
    elite_bonus_score,
    time_visual_tier,
    enemy_stat_multiplier,
)
from .super_enemy import (
    SuperEnemyDirector,
    SuperSkill,
    SUPER_BASE_HEALTH_MULT,
)

__all__ = [
    "Enemy",
    "EnemyState",
    "spawn_enemy",
    "step_enemy",
    "SpawnDirector",
    "Sector",
    "ENEMY_HARD_CAP",
    "stage_modifiers",
    "enemy_spawned_snapshot",
    "elite_bonus_score",
    "time_visual_tier",
    "enemy_stat_multiplier",
    "SuperEnemyDirector",
    "SuperSkill",
    "SUPER_BASE_HEALTH_MULT",
]
