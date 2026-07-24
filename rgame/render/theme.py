"""rgame 视觉主题（元气骑士风）。

设计原则：
- 粗黑描边（3–4px）：所有 HUD 面板、按钮、卡牌边框走 3-4px 黑色描边
- 高饱和度色块：HP 红、护盾蓝、护甲金、XP 绿、炸弹橙、主角 cyan
- 圆角胶囊：按钮/面板统一 radius=10
- 文字描黑：所有白色/亮色文字画一层 1px 黑色描边，避免背景干扰
- 角色贴图：所有主角/敌人/超级怪兽统一用 chars/ 下的 1024×1024 png，旋转 -90° 朝向

颜色按"语义色"分组：HP / SHIELD / ARMOR / XP / HEAL / BUFF / BOMB / DANGER
"""
from __future__ import annotations

from typing import Tuple

# =============================================================================
# 基础色板
# =============================================================================
# 画布 / 背景
BG_DARK = (15, 22, 36)        # 主菜单背景
BG_PANEL = (24, 32, 52)       # 面板填充
BG_PANEL_ALT = (32, 42, 64)   # 嵌套面板
BG_WORLD_VEIL = (10, 14, 26)  # 战斗场景半透遮罩
BLACK_OUTLINE = (8, 10, 16)   # 描边黑（不是纯黑，避免对比过强）
SHADOW = (0, 0, 0)

# 文字
TEXT_PRIMARY = (255, 255, 255)
TEXT_DIM = (172, 184, 200)
TEXT_ACCENT = (255, 230, 130)
TEXT_DARK = (24, 28, 40)
TEXT_OUTLINE = (12, 14, 22)

# =============================================================================
# 角色 / 敌人
# =============================================================================
PLAYER_PRIMARY = (90, 215, 255)     # 主角 cyan
PLAYER_CORE = (220, 248, 255)
PLAYER_TRIM = (38, 88, 140)

ENEMY_COMMON = (235, 90, 110)        # 普怪红
ENEMY_ELITE = (255, 195, 90)         # 精英金
ENEMY_SUPER = (220, 90, 240)         # 超级紫红
ENEMY_SPAWN_RING = (130, 220, 255)

# =============================================================================
# 武器 / 投射物
# =============================================================================
PROJ_PLAYER = (140, 235, 255)
PROJ_ENEMY = (255, 175, 80)
PROJ_BOMB = (255, 110, 80)
PROJ_LASER = (200, 240, 255)

# =============================================================================
# 拾取
# =============================================================================
PICKUP_XP = (130, 230, 170)
PICKUP_HEAL = (120, 235, 130)
PICKUP_BUFF = (200, 220, 255)
PICKUP_SHIELD = (140, 200, 255)
PICKUP_BOMB = (255, 100, 90)

# =============================================================================
# HUD 语义色（HP / SHIELD / ARMOR / XP）
# =============================================================================
HP_FILL = (228, 78, 96)
HP_BACK = (64, 24, 32)
HP_BORDER = (255, 235, 235)

SHIELD_FILL = (110, 200, 255)
SHIELD_BORDER = (220, 240, 255)

ARMOR_FILL = (210, 190, 120)
ARMOR_BORDER = (255, 245, 220)

XP_FILL = (130, 230, 170)
XP_BACK = (32, 56, 42)

# 警告 / 危险
DANGER = (255, 70, 80)
DANGER_BG = (200, 50, 60)
WARN = (255, 170, 60)

# 卡牌稀有度
CARD_BRONZE = (205, 142, 82)
CARD_BRONZE_DARK = (105, 62, 35)
CARD_SILVER = (210, 220, 232)
CARD_SILVER_DARK = (90, 110, 130)
CARD_GOLD = (250, 210, 110)
CARD_GOLD_DARK = (160, 110, 40)
CARD_COLOR = (240, 130, 250)
CARD_COLOR_DARK = (140, 50, 160)

# UI 强调
ACCENT = (90, 215, 255)
ACCENT_2 = (255, 130, 210)
ACCENT_3 = (255, 200, 100)

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
}

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
