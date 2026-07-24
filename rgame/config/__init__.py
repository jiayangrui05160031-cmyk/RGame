"""数据配置契约（按《数据与配置契约》）。"""

from .contract import (
    SchemaError,
    validate_enemy,
    validate_weapon,
    validate_card,
    validate_drop_table,
    validate_preset,
    validate_achievement,
    validate_stage,
    validate_config_bundle,
    ConfigBundle,
)
from .content import (
    load_default_bundle,
    DEFAULT_STAGES,
    DEFAULT_PRESETS,
    DEFAULT_ENEMIES,
    DEFAULT_WEAPONS,
    DEFAULT_CARDS,
    DEFAULT_DROP_TABLES,
    DEFAULT_ACHIEVEMENTS,
)

__all__ = [
    "SchemaError",
    "validate_enemy",
    "validate_weapon",
    "validate_card",
    "validate_drop_table",
    "validate_preset",
    "validate_achievement",
    "validate_stage",
    "validate_config_bundle",
    "ConfigBundle",
    "load_default_bundle",
    "DEFAULT_STAGES",
    "DEFAULT_PRESETS",
    "DEFAULT_ENEMIES",
    "DEFAULT_WEAPONS",
    "DEFAULT_CARDS",
    "DEFAULT_DROP_TABLES",
    "DEFAULT_ACHIEVEMENTS",
]
