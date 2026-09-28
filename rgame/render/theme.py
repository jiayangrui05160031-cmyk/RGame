"""rgame 视觉主题（深空战术风）。

设计原则：
- 深海军蓝玻璃面板、细青色描边与少量斜切角
- 青蓝作为主交互色，紫色代表虚空，琥珀色表示奖励和危险
- 角色材质统一为象牙白装甲、蓝钢结构与冷色发光核心

颜色按"语义色"分组：HP / SHIELD / ARMOR / XP / HEAL / BUFF / BOMB / DANGER
"""
from __future__ import annotations

from typing import Tuple

# =============================================================================
# 基础色板
# =============================================================================
# 画布 / 背景
BG_DARK = (6, 12, 26)         # 深空底色
BG_PANEL = (11, 22, 40)       # 深色玻璃面板
BG_PANEL_ALT = (18, 36, 58)   # 嵌套面板
BG_WORLD_VEIL = (3, 7, 18)    # 战斗场景半透遮罩
BLACK_OUTLINE = (3, 7, 16)    # 海军蓝描边
SHADOW = (0, 0, 0)

# 文字
TEXT_PRIMARY = (229, 241, 255)
TEXT_DIM = (140, 163, 190)
TEXT_ACCENT = (151, 231, 255)
TEXT_DARK = (7, 17, 32)
TEXT_OUTLINE = (3, 7, 16)

# =============================================================================
# 角色 / 敌人
# =============================================================================
PLAYER_PRIMARY = (55, 220, 255)     # 主角 cyan
PLAYER_CORE = (232, 251, 255)
PLAYER_TRIM = (28, 82, 138)

ENEMY_COMMON = (246, 94, 129)        # 普怪珊瑚红
ENEMY_ELITE = (255, 190, 92)         # 精英琥珀金
ENEMY_SUPER = (195, 110, 255)        # 超级虚空紫
ENEMY_SPAWN_RING = (81, 227, 255)

# =============================================================================
# 武器 / 投射物
# =============================================================================
PROJ_PLAYER = (85, 232, 255)
PROJ_ENEMY = (255, 151, 100)
PROJ_BOMB = (255, 92, 128)
PROJ_LASER = (206, 247, 255)

# =============================================================================
# 拾取
# =============================================================================
PICKUP_XP = (116, 243, 202)
PICKUP_HEAL = (135, 242, 176)
PICKUP_BUFF = (180, 204, 255)
PICKUP_SHIELD = (87, 204, 255)
PICKUP_BOMB = (255, 104, 135)

# =============================================================================
# HUD 语义色（HP / SHIELD / ARMOR / XP）
# =============================================================================
HP_FILL = (255, 79, 115)
HP_BACK = (68, 24, 46)
HP_BORDER = (255, 220, 235)

SHIELD_FILL = (61, 203, 255)
SHIELD_BORDER = (193, 241, 255)

ARMOR_FILL = (255, 184, 88)
ARMOR_BORDER = (255, 232, 183)

XP_FILL = (95, 227, 186)
XP_BACK = (16, 57, 63)

# 警告 / 危险
DANGER = (255, 73, 117)
DANGER_BG = (102, 25, 63)
WARN = (255, 178, 83)

# 卡牌稀有度
CARD_BRONZE = (205, 145, 105)
CARD_BRONZE_DARK = (92, 53, 45)
CARD_SILVER = (151, 207, 240)
CARD_SILVER_DARK = (43, 76, 112)
CARD_GOLD = (255, 201, 103)
CARD_GOLD_DARK = (117, 77, 38)
CARD_COLOR = (216, 125, 255)
CARD_COLOR_DARK = (81, 43, 137)

# UI 强调
ACCENT = (57, 221, 255)
ACCENT_2 = (197, 132, 255)
ACCENT_3 = (255, 190, 92)

# =============================================================================
# 敌人 config_id -> 资源路径（单一事实来源）
# =============================================================================
ENEMY_SPRITE_PATHS = {
    "spinner_chaser": "chars/spinner_chaser.png",
    "wingblade_sprinter": "chars/wingblade_sprinter.png",
    "shellguard_heavy": "chars/shellguard_heavy.png",
    "lantern_shooter": "chars/lantern_shooter.png",
    "crystal_sniper": "chars/crystal_sniper-v2.png",
    "multinode_spreader": "chars/multinode_spreader.png",
    "minelayer_bomber": "chars/minelayer_bomber.png",
    "mine_leech": "v2/enemies/mine_leech_sheet.png",
    "rail_turret": "v2/enemies/rail_turret_sheet.png",
}
ENEMY_ROSTER_SHEET_PATH = "v3/enemies/enemy_roster_sheet.png"

PLAYER_SPRITE_PATH = "chars/player_hero_transparent.png"
SUPER_BOSS_SPRITE_PATH = "chars/super_boss.png"
UI_DESIGN_PATH = "ui/ui_design.png"

# 渲染尺寸：所有角色/敌人贴图按此基础尺寸缩放
SPRITE_BASE_PX = 78  # 收敛贴图占比，给战斗特效和背景留出呼吸空间


# =============================================================================
# 工具函数
# =============================================================================
def blend(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    """线性插值两个 RGB 颜色。t=0 → c1, t=1 → c2。"""
    t = max(0.0, min(1.0, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def with_alpha(c: Tuple[int, int, int], a: int) -> Tuple[int, int, int, int]:
    """RGB → RGBA。"""
    return (c[0], c[1], c[2], max(0, min(255, a)))
