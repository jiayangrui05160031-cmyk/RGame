"""pygame 桌面端渲染 / 输入适配。

按《跨平台与手游适配》：

- 1920×1080 逻辑画布，按等比缩放铺满窗口；
- 安全区数据从 platform.system() / 等价字段获取（无则用系统常量）；
- 键鼠 + 触屏可同时启用；
- 战斗与选择 UI 都走此处的状态机。
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pygame

from ..core.state_machine import (
    BOOT, MAIN_MENU, MODE_SELECT, PRESET_SELECT, RUNNING, PAUSED,
    SUPER_WARNING, LEVEL_UP, CARD_SELECT, STAGE_CLEAR, ENDING, RESULT, ERROR,
)
from ..engine import (
    ACTIVE_SKILLS, CARD_COMBO_SETS, EQUIPMENT_ITEMS, SHOP_ITEMS, Engine,
    ENEMY_AFFIXES, WEAPON_RARITY_RULES,
)
from ..player.input_provider import (
    KeyboardInputProvider, TouchInputProvider, CompositeInputProvider,
)
from ..player.movement import PlayableBounds
from ..drops.drops import HazardBomb
from ..enemies.enemies import EnemyState
from ..enemies.super_enemy import SuperSkill
from ..save.save import load_account_history, profile_path_for_account, record_account_history
from . import theme as T


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
FONT_NAME = "microsoftyaheiui"


# 安全区（无系统数据时使用保守值）
SAFE_INSET = {
    "win": {"top": 32, "bottom": 32, "left": 32, "right": 32},
    "mac": {"top": 32, "bottom": 32, "left": 32, "right": 32},
    "android": {"top": 56, "bottom": 56, "left": 56, "right": 56},
    "ios": {"top": 88, "bottom": 96, "left": 70, "right": 70},
    "linux": {"top": 32, "bottom": 32, "left": 32, "right": 32},
}


def platform_name() -> str:
    if sys.platform.startswith("win"):
        return "win"
    if sys.platform.startswith("darwin"):
        return "mac"
    if sys.platform.startswith("linux"):
        return "linux"
    return "win"


def build_input_provider(window_w: int, window_h: int, platform: str = "win") -> CompositeInputProvider:
    kb = KeyboardInputProvider()
    safe = SAFE_INSET.get(platform, SAFE_INSET["win"])
    # 摇杆：左下，避开 HUD
    joy_radius = int(0.05 * min(window_w, window_h))
    joy_center = (safe["left"] + joy_radius + 24, window_h - safe["bottom"] - joy_radius - 24)
    # 切换按钮：右下
    btn_size = max(56, int(0.06 * min(window_w, window_h)))
    switch_rect = (window_w - safe["right"] - btn_size - 24, window_h - safe["bottom"] - btn_size - 24, btn_size, btn_size)
    # 暂停按钮：右上
    pause_size = max(48, int(0.05 * min(window_w, window_h)))
    pause_rect = (window_w - safe["right"] - pause_size - 24, safe["top"] + 24, pause_size, pause_size)
    touch = TouchInputProvider(
        joystick_center=joy_center,
        joystick_radius=joy_radius,
        switch_button_rect=switch_rect,
        pause_button_rect=pause_rect,
    )
    return CompositeInputProvider(kb, touch)


# =============================================================================
# 颜色常量 — 已迁出到 .theme，本文件只保留旧名作为向下兼容 shim，
# 让本文件内部代码不需大改。新代码请用 rgame.render.theme 命名空间。
# =============================================================================
COL_BG = T.BG_DARK
COL_TEXT = T.TEXT_PRIMARY
COL_TEXT_DIM = T.TEXT_DIM
COL_PLAYER = T.PLAYER_PRIMARY
COL_PLAYER_CORE = T.PLAYER_CORE
COL_ENEMY = T.ENEMY_COMMON
COL_ENEMY_ELITE = T.ENEMY_ELITE
COL_ENEMY_SUPER = T.ENEMY_SUPER
COL_PROJECTILE_PLAYER = T.PROJ_PLAYER
COL_PROJECTILE_ENEMY = T.PROJ_ENEMY
COL_PICKUP_XP = T.PICKUP_XP
COL_PICKUP_HEAL = T.PICKUP_HEAL
COL_PICKUP_BUFF = T.PICKUP_BUFF
COL_PICKUP_SHIELD = T.PICKUP_SHIELD
COL_BOMB = T.PICKUP_BOMB
COL_BOMB_DANGER = T.DANGER
COL_HP = T.HP_FILL
COL_HP_BACK = T.HP_BACK
COL_SHIELD = T.SHIELD_FILL
COL_ARMOR = T.ARMOR_FILL
COL_SUPER_BAR = T.ENEMY_SUPER
COL_HUD_BG = T.BG_PANEL
COL_HUD_BORDER = T.BLACK_OUTLINE
COL_BTN_ACTIVE = T.ACCENT
COL_BTN_INACTIVE = T.BG_PANEL_ALT
COL_PANEL = T.BG_PANEL
COL_PANEL_2 = T.BG_PANEL_ALT
COL_PANEL_ALPHA = 220
COL_ACCENT = T.ACCENT
COL_ACCENT_2 = T.ACCENT_2
COL_SAFE_AREA = (130, 110, 90)
COL_SAFE_AREA_DANGER = T.DANGER
COL_SAFE_AREA_BOMB = T.PICKUP_BOMB
COL_CARD_BORDER = T.BLACK_OUTLINE
COL_CARD_SILVER = T.CARD_SILVER
COL_CARD_GOLD = T.CARD_GOLD
COL_CARD_COLOR = T.CARD_COLOR
COL_TEXT_OUTLINE = T.TEXT_OUTLINE


# =============================================================================
# 颜色映射：按 tier（银/金/彩）
# =============================================================================
def rarity_color(rarity: str) -> tuple[int, int, int]:
    return {
        "铜": T.CARD_BRONZE,
        "银": T.CARD_SILVER,
        "金": T.CARD_GOLD,
    }.get(rarity, T.CARD_BRONZE)


# =============================================================================
# 工具
# =============================================================================
from functools import lru_cache

import pygame

from . import theme as T


class _UiState:
    ui_scale: float = 1.0


_app_state = _UiState()


_glow_cache: dict[tuple[int, tuple[int, int, int], int], pygame.Surface] = {}
_font_cache: dict[tuple[str, int, bool], pygame.font.Font] = {}
_panel_cache: dict[tuple, pygame.Surface] = {}


def _ui_size(base: int) -> int:
    """所有 HUD/菜单文字都按世界缩放比例换算字号。"""
    scale = getattr(_app_state, "ui_scale", 1.0) or 1.0
    return max(10, min(96, int(round(base * scale))))


def get_ui_font(base_size: int, *, bold: bool = False) -> pygame.font.Font:
    """获取按当前 UI 缩放的缓存字体，避免每次绘制反复创建字体对象。"""
    size = _ui_size(base_size)
    key = (FONT_NAME, size, bool(bold))
    cached = _font_cache.get(key)
    if cached is not None:
        return cached
    font = pygame.font.SysFont(FONT_NAME, size, bold=bold)
    _font_cache[key] = font
    return font


def clear_ui_cache() -> None:
    """在测试或字体/分辨率环境变化时清空 UI 缓存。"""
    _font_cache.clear()
    _panel_cache.clear()
    clear_glow_cache()


def draw_text(surf, text, pos, *, size=20, color=COL_TEXT, font=None,
              outline: int = 0, outline_color=COL_TEXT_OUTLINE):
    """绘制文字。outline>0 时画一层黑色描边（元气骑士风必备）。"""
    if font is None:
        font = get_ui_font(size)
    img = font.render(str(text), True, color)
    if outline > 0:
        shadow = font.render(str(text), True, outline_color)
        for ox, oy in (
            (-outline, 0), (outline, 0), (0, -outline), (0, outline),
            (-outline, -outline), (-outline, outline),
            (outline, -outline), (outline, outline),
        ):
            surf.blit(shadow, (pos[0] + ox, pos[1] + oy))
    surf.blit(img, pos)
    return img.get_width(), img.get_height()


def draw_text_center(surf, text, rect, *, color=COL_TEXT, font=None, y_offset=0,
                     outline: int = 0, outline_color=COL_TEXT_OUTLINE, size: int = 20):
    if font is None:
        font = get_ui_font(size)
    img = font.render(str(text), True, color)
    x = rect.centerx - img.get_width() // 2
    y = rect.centery - img.get_height() // 2 + y_offset
    if outline > 0:
        shadow = font.render(str(text), True, outline_color)
        for ox, oy in (
            (-outline, 0), (outline, 0), (0, -outline), (0, outline),
            (-outline, -outline), (-outline, outline),
            (outline, -outline), (outline, outline),
        ):
            surf.blit(shadow, (x + ox, y + oy))
    surf.blit(img, (x, y))
    return img.get_width(), img.get_height()


def make_glow(radius: int, color: tuple[int, int, int], alpha: int = 110) -> pygame.Surface:
    """按 (半径, 颜色, alpha) 缓存的辉光圆。

    旧实现每次创建新 Surface，P1-2：高频战斗下会成百上千次表面分配。
    """
    key = (int(max(4, radius)), tuple(int(c) for c in color), int(alpha))
    cached = _glow_cache.get(key)
    if cached is not None:
        return cached
    size = max(4, radius * 2 + 4)
    surf = pygame.Surface((size, size), pygame.SRCALPHA)
    cx = cy = size // 2
    for i in range(radius, 0, -1):
        a = int(alpha * (i / max(1, radius)) ** 2)
        pygame.draw.circle(surf, (*color, a), (cx, cy), i)
    _glow_cache[key] = surf
    return surf


def clear_glow_cache() -> None:
    """测试和分辨率变化时清缓存。"""
    _glow_cache.clear()


def draw_panel(surf, rect, *, border=COL_HUD_BORDER, fill=COL_PANEL, alpha=COL_PANEL_ALPHA, radius=14, outline=3):
    """元气骑士风面板：4px 黑色描边 + 高对比填充。

    面板本身只由尺寸和样式决定，缓存后每帧只需 blit，避免战斗 HUD
    持续分配大量短生命周期 Surface。
    """
    key = (rect.w, rect.h, tuple(border), tuple(fill), int(alpha), int(radius), int(outline))
    panel = _panel_cache.get(key)
    if panel is None:
        panel = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        if outline > 0:
            pygame.draw.rect(panel, border, (0, 0, rect.w, rect.h), border_radius=radius)
            inner = (outline, outline, max(1, rect.w - 2 * outline), max(1, rect.h - 2 * outline))
            pygame.draw.rect(panel, (*fill, alpha), inner, border_radius=max(2, radius - outline))
        else:
            pygame.draw.rect(panel, (*fill, alpha), (0, 0, rect.w, rect.h), border_radius=radius)
        pygame.draw.line(panel, (*T.ACCENT, 80), (outline + 6, outline + 2), (rect.w - outline - 6, outline + 2), 1)
        _panel_cache[key] = panel
    surf.blit(panel, rect.topleft)


def draw_button(surf, rect, label, *, font, active=False, accent=COL_ACCENT, accent_fill=None):
    """元气骑士风按钮：胶囊 + 3px 黑色描边 + 高饱和色。

    旧实现：active 状态下还把白字 + 黑描边叠在浅底板上 → 文字"重影"（子报告 + 用户截图）。
    新实现：active 用浅色填充 + 深色文字（无描边），inactive 仍用白字 + 黑描边。
    """
    if accent_fill is None:
        accent_fill = accent
    border = COL_HUD_BORDER
    pygame.draw.rect(surf, border, rect, border_radius=12)
    inner = rect.inflate(-4, -4)
    fill = accent_fill if active else COL_BTN_INACTIVE
    pygame.draw.rect(surf, fill, inner, border_radius=10)
    if active:
        pygame.draw.rect(surf, (*T.TEXT_PRIMARY, 32), inner.inflate(-8, -8), border_radius=8)
    text_color = T.TEXT_DARK if active else T.TEXT_PRIMARY
    draw_text_center(surf, label, rect, color=text_color, font=font,
                     outline=0 if active else 2, size=max(14, font.get_height()))


def fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def zh_weapon_name(weapon_id: str, fallback: str = "") -> str:
    names = {
        "w_melee_blade": "迅捷砍刀",
        "w_rifle_precise": "冰雹步枪",
        "w_shotgun_spread": "散射霰弹",
        "w_orbiter_omni": "环绕哨兵",
        "w_laser_charge": "光束矩阵",
        "w_laser_cannon": "激光炮",
        "w_arcane_orb": "奥术回响",
        "w_great_cleaver": "裂地大砍刀",
        "w_ricochet_ball": "棱镜弹球",
        "w_thunder_daggers": "雷鸣短刃",
        "w_frost_lance": "冰脊长枪",
        "w_flame_handcannon": "赤焰手炮",
        "w_starfall_bow": "星坠弓",
        "w_venom_knife": "毒雾匕首",
        "w_magnetic_ringblade": "磁暴环刃",
        "w_holy_scepter": "圣辉权杖",
        "w_blood_scythe": "血契镰刀",
        "w_void_pistols": "虚空双枪",
        "w_rockfall_hammer": "岩崩战锤",
        "w_wind_tachi": "风切太刀",
        "w_thunder_array": "四雷阵盘",
    }
    return names.get(weapon_id, fallback or weapon_id)


def prepare_character_asset(surface: pygame.Surface) -> pygame.Surface:
    """去掉素材中与画布边缘连通的近白背景并裁掉空白边缘。"""
    src = surface.convert_alpha()
    white = pygame.mask.from_threshold(
        src, (255, 255, 255, 255), threshold=(22, 22, 22, 255)
    )
    background = white.connected_component()
    if background.count() > 0:
        alpha_mask = background.to_surface(
            setcolor=(0, 0, 0, 0), unsetcolor=(255, 255, 255, 255)
        )
        src.blit(alpha_mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    visible = pygame.mask.from_surface(src, 8)
    rects = visible.get_bounding_rects()
    if not rects:
        return src
    bounds = rects[0].copy()
    for rect in rects[1:]:
        bounds.union_ip(rect)
    bounds.inflate_ip(12, 12)
    # clamp 只会移动同尺寸矩形；当精灵贴边且 inflate 后大于子画布时，
    # 仍可能越界。clip 才能保证精灵表切片安全裁剪。
    bounds = bounds.clip(src.get_rect())
    if bounds.w <= 0 or bounds.h <= 0:
        return src
    return src.subsurface(bounds).copy()


def draw_facing_arc(
    surface: pygame.Surface,
    center: tuple[int, int],
    *,
    angle: float,
    arc_deg: float,
    radius: int,
    color,
    width: int,
    samples: int = 24,
) -> None:
    """按游戏世界的 y 向下角度系画弧，和近战命中判定使用同一朝向。"""
    if arc_deg >= 359:
        pygame.draw.circle(surface, color, center, radius, width=width)
        return
    start = angle - math.radians(arc_deg * 0.5)
    points = []
    for i in range(max(2, samples)):
        a = start + math.radians(arc_deg) * i / max(1, samples - 1)
        points.append((center[0] + int(math.cos(a) * radius), center[1] + int(math.sin(a) * radius)))
    pygame.draw.lines(surface, color, False, points, width=width)


# =============================================================================
# 主 App
# =============================================================================
class RGameApp:
    """pygame 桌面端入口。

    启动：``python -m rgame`` 或 ``python main.py``。
    """

    def __init__(
        self,
        *,
        seed: int | None = None,
        platform: str = "win",
        enable_disk_log: bool = False,
        save_path: str = "rgame_profile.json",
        log_path: str = "rgame_run.log",
        windowed: bool = True,
    ) -> None:
        self.platform = platform
        self._enable_disk_log = enable_disk_log
        self._save_path = save_path
        self._log_path = log_path
        # pygame 初始化
        pygame.init()
        if windowed:
            self.screen_w = 1280
            self.screen_h = 720
        else:
            self.screen_w = SCREEN_WIDTH
            self.screen_h = SCREEN_HEIGHT
        self.screen = pygame.display.set_mode((self.screen_w, self.screen_h), pygame.RESIZABLE)
        pygame.display.set_caption("火星攻击")
        self.clock = pygame.time.Clock()
        # 等比缩放：1920×1080 → screen
        self.scale = min(self.screen_w / SCREEN_WIDTH, self.screen_h / SCREEN_HEIGHT)
        self.world_rect = pygame.Rect(0, 0, int(SCREEN_WIDTH * self.scale), int(SCREEN_HEIGHT * self.scale))
        self.world_rect.center = (self.screen_w // 2, self.screen_h // 2)
        # 输入
        self.input_provider = build_input_provider(self.screen_w, self.screen_h, self.platform)
        self.keyboard = self.input_provider.providers[0]
        self.touch = self.input_provider.providers[1]
        # 引擎
        self.engine = Engine(
            platform=self.platform,
            input_provider=self.input_provider,
            save_path=self._save_path,
            log_path=self._log_path,
            enable_disk_log=self._enable_disk_log,
            seed=seed,
        )
        # 字体
        self.font_small: pygame.font.Font
        self.font: pygame.font.Font
        self.font_mid: pygame.font.Font
        self.font_big: pygame.font.Font
        self._refresh_fonts()
        # 视觉资源
        self.assets_dir = Path(__file__).resolve().parents[1] / "assets"
        self.v2_assets_dir = self.assets_dir / "v2"
        self.bg_source: pygame.Surface | None = None
        self.stage_bg_sources: dict[int, pygame.Surface] = {}
        self.bg_scaled: pygame.Surface | None = None
        self.bg_scaled_key: tuple[int, int, int] | None = None
        # 主角贴图（元气骑士风骑士）
        self.player_sprite_source: pygame.Surface | None = None
        self.player_sprite_frames: list[pygame.Surface] = []
        self.player_attack_frames: list[pygame.Surface] = []
        self.player_sprite_scaled: pygame.Surface | None = None
        self.player_sprite_size: tuple[int, int] | None = None
        # 敌人贴图缓存：config_id -> 原始 Surface
        self.enemy_sprite_sources: dict[str, pygame.Surface] = {}
        self.enemy_sprite_frames: dict[str, list[pygame.Surface]] = {}
        # 超级 BOSS 贴图
        self.super_sprite_source: pygame.Surface | None = None
        self.super_sprite_frames: list[pygame.Surface] = []
        self.super_enraged_frames: list[pygame.Surface] = []
        self.weapon_icon_sources: dict[str, pygame.Surface] = {}
        self.equipment_icon_sources: dict[str, pygame.Surface] = {}
        self.combo_icon_sources: dict[str, pygame.Surface] = {}
        self.affix_icon_sources: dict[str, pygame.Surface] = {}
        self.event_icon_sources: dict[str, pygame.Surface] = {}
        self.prop_sources: dict[str, pygame.Surface] = {}
        self.ui_art_sources: dict[str, pygame.Surface] = {}
        self.boss_ui_sources: dict[str, pygame.Surface] = {}
        self.effect_sources: dict[str, pygame.Surface] = {}
        self.pickup_icon_sources: dict[str, pygame.Surface] = {}
        self.card_frame_sources: dict[str, pygame.Surface] = {}
        self._feedback_sounds: dict[str, pygame.mixer.Sound] = {}
        self._audio_ready = False
        self._music_track: str | None = None
        # 通用缩放缓存：(config_id, target_size) -> Surface
        self._sprite_scale_cache: dict[tuple, pygame.Surface] = {}
        self._scene_overlay_cache: dict[tuple, pygame.Surface] = {}
        self._load_assets()
        # 状态
        self.running = True
        self.last_real_dt = 1 / 60
        self.selection_state = {"main": 0, "mode": 0, "preset": 0, "result": 0, "card": 0, "level": 0, "shop": 0}  # UI 选项
        self.skill_select_index = 0
        self.skill_ids = ["bomb_trap", "roll", "axe_orbit"]
        self.login_active = True
        self.account_input = getattr(self.engine.profile, "account_name", "default") or "default"
        self.account_history = load_account_history(self._save_path)
        self.login_selected_index = 0
        self.login_typing_new = not bool(self.account_history)
        if self.account_history:
            self.account_input = self.account_history[0]
        self.show_achievements = False
        self.show_shop = False
        self.show_history = False
        self.shop_selected_index = 0
        self.shop_category_index = 0
        self.achievement_selected_index = 0
        self.weapon_config_slot = 0
        self.weapon_pool_index = 0
        self.equipment_config_slot = 0
        self.equipment_pool_index = 0
        self.history_selected_index = 0
        self.ach_notice: dict | None = None
        self.last_ach_text = ""
        self._seen_enemy_hp: dict[str, float] = {}
        self._seen_enemy_pos: dict[str, tuple[float, float]] = {}
        self._seen_player_hp = self.engine.player.current_hp
        self._floaters: list[dict] = []
        self._hit_bursts: list[dict] = []
        self._enemy_hit_flash: dict[str, float] = {}
        self._seen_visual_events: set[str] = set()
        self._screen_shake = 0.0
        # 子报告 P0-2：4 条浮动通知 (weapon_synergy / random_event / challenge / killstreak)
        # 以前 y 都贴在 world_rect.y+100~+200，会互相覆盖。这里改成单槽位 + 互斥 + 按到时间排队。
        self._notice_state: dict[str, dict] = {}
        self._notice_order: list[str] = []
        self._notice_capacity = 3  # 屏幕中央最多堆 3 条
        self._notice_slot_height = 48  # 每条占 48px，按 ui_scale 缩放在 draw 时生效
        self._polled_shortcut_state = {"j": False, "k": False, "q": False, "l": False}
        # P6：活动中的组合技屏幕特效
        self._combo_fx_list: list[dict] = []
        # P7：成就徽章临时状态
        self._achievement_badge_center = (0, 0)
        # P9：商店搜索输入
        self._shop_search_input = ""
        # 子报告 P0-3：保留开关，默认关闭，恢复"代码 = 实际行为"承诺。
        self._touch_controls_enabled = False
        # 当前 ui 缩放，由 RGameApp 在初始化和 _resize 时更新。
        from . import pygame_app as _self_module
        _self_module._app_state.ui_scale = self.scale

    def _refresh_fonts(self) -> None:
        """按当前窗口缩放刷新字体引用，避免 resize 后字号仍沿用旧窗口。"""
        from . import pygame_app as _self_module
        _self_module._app_state.ui_scale = self.scale
        _font_cache.clear()
        self.font_small = get_ui_font(16)
        self.font = get_ui_font(22)
        self.font_mid = get_ui_font(30)
        self.font_big = get_ui_font(48)

    def _load_assets(self) -> None:
        bg_path = self.v2_assets_dir / "backgrounds" / "arena_bg_stage1-v2.png"
        if not bg_path.exists():
            bg_path = self.assets_dir / "arena_bg.png"
        if bg_path.exists():
            try:
                self.bg_source = pygame.image.load(str(bg_path)).convert()
            except pygame.error:
                self.bg_source = None
        for stage in (2, 3, 4, 5):
            stage_bg_path = self.v2_assets_dir / "backgrounds" / f"arena_bg_stage{stage}-v2.png"
            if not stage_bg_path.exists():
                stage_bg_path = self.assets_dir / f"arena_bg_stage{stage}.png"
            if stage_bg_path.exists():
                try:
                    self.stage_bg_sources[stage] = pygame.image.load(str(stage_bg_path)).convert()
                except pygame.error:
                    pass
        # 新交付的精灵表优先；只使用前两行，避开交付表中不透明的占位底色。
        hero_sheet = self.v2_assets_dir / "player" / "player_base_sheet.png"
        attack_sheet = self.v2_assets_dir / "player" / "player_attack_sheet.png"
        self.player_sprite_frames = self._load_sheet_frames(hero_sheet, rows=2)
        self.player_attack_frames = self._load_sheet_frames(attack_sheet, rows=2)
        if self.player_sprite_frames:
            self.player_sprite_source = self.player_sprite_frames[0]
        # 主角：保留旧资源作为外部素材缺失时的 fallback
        hero_path = self.assets_dir / T.PLAYER_SPRITE_PATH
        if self.player_sprite_source is None and hero_path.exists():
            try:
                self.player_sprite_source = pygame.image.load(str(hero_path)).convert_alpha()
            except pygame.error:
                self.player_sprite_source = None
        if self.player_sprite_source is None:
            player_path = self.assets_dir / "player_ship.png"
            if player_path.exists():
                try:
                    self.player_sprite_source = pygame.image.load(str(player_path)).convert_alpha()
                except pygame.error:
                    self.player_sprite_source = None
        # ===== [新增] 轻捷/重装形态 sprite sheet 加载 =====
        self.player_form_sheets: dict[str, list[pygame.Surface]] = {}
        for form_id in ("nimble", "heavy"):
            form_path = self.v2_assets_dir / "player" / f"player_{form_id}_sheet.png"
            if form_path.exists():
                frames = self._load_sheet_frames(form_path, rows=2)
                if frames:
                    self.player_form_sheets[form_id] = frames
        # 普通敌人：新精灵表优先，旧素材作为回退。
        for cfg_id, rel in T.ENEMY_SPRITE_PATHS.items():
            sheet_path = self.v2_assets_dir / "enemies" / f"{cfg_id}_sheet.png"
            frames = self._load_sheet_frames(sheet_path, rows=2)
            if frames:
                self.enemy_sprite_frames[cfg_id] = frames
                self.enemy_sprite_sources[cfg_id] = frames[0]
                continue
            p = self.assets_dir / rel
            if p.exists():
                try:
                    loaded = pygame.image.load(str(p)).convert_alpha()
                    self.enemy_sprite_sources[cfg_id] = prepare_character_asset(loaded)
                except pygame.error:
                    pass
        # ===== [新增] 敌人时间形态贴图 T1/T2/T3 =====
        self.enemy_tier_sprites: dict[str, dict[int, pygame.Surface]] = {}
        for cfg_id in T.ENEMY_SPRITE_PATHS:
            self.enemy_tier_sprites[cfg_id] = {}
            for tier in (1, 2, 3):
                tier_path = self.v2_assets_dir / "enemies" / f"{cfg_id}_t{tier}.png"
                loaded = self._load_clean_asset(tier_path)
                if loaded is not None:
                    self.enemy_tier_sprites[cfg_id][tier] = loaded
        # ===== [新增] 敌人破损贴图 damage1/damage2 =====
        self.enemy_damage_sprites: dict[str, dict[int, pygame.Surface]] = {}
        for cfg_id in T.ENEMY_SPRITE_PATHS:
            self.enemy_damage_sprites[cfg_id] = {}
            for dmg_level in (1, 2):
                dmg_path = self.v2_assets_dir / "enemies" / f"{cfg_id}_damage{dmg_level}.png"
                loaded = self._load_clean_asset(dmg_path)
                if loaded is not None:
                    self.enemy_damage_sprites[cfg_id][dmg_level] = loaded
        # 超级 BOSS：普通与狂暴贴图分离，可由半血阶段切换。
        self.super_sprite_frames = self._load_sheet_frames(
            self.v2_assets_dir / "boss" / "super_boss_normal_sheet.png", rows=2
        )
        self.super_enraged_frames = self._load_sheet_frames(
            self.v2_assets_dir / "boss" / "super_boss_enraged_sheet.png", rows=2
        )
        if self.super_sprite_frames:
            self.super_sprite_source = self.super_sprite_frames[0]
        boss_path = self.assets_dir / T.SUPER_BOSS_SPRITE_PATH
        if self.super_sprite_source is None and boss_path.exists():
            try:
                self.super_sprite_source = pygame.image.load(str(boss_path)).convert_alpha()
            except pygame.error:
                self.super_sprite_source = None

        weapon_names = {
            "w_melee_blade": "weapon_quick_cleaver.png",
            "w_rifle_precise": "weapon_hailstorm_rifle.png",
            "w_shotgun_spread": "weapon_buckshot_spreader.png",
            "w_orbiter_omni": "weapon_orbital_sentry.png",
            "w_laser_charge": "weapon_beam_lattice.png",
            "w_laser_cannon": "weapon_laser_cannon.png",
            "w_arcane_orb": "weapon_arcane_echo.png",
            "w_great_cleaver": "weapon_great_cleaver.png",
            "w_ricochet_ball": "weapon_ricochet_ball.png",
            "w_thunder_daggers": "weapon_thunder_daggers.png",
            "w_frost_lance": "weapon_frost_lance.png",
            "w_flame_handcannon": "weapon_flame_handcannon.png",
            "w_starfall_bow": "weapon_starfall_bow.png",
            "w_venom_knife": "weapon_venom_knife.png",
            "w_magnetic_ringblade": "weapon_magnetic_ringblade.png",
            "w_holy_scepter": "weapon_holy_scepter.png",
            "w_blood_scythe": "weapon_blood_scythe.png",
            "w_void_pistols": "weapon_void_pistols.png",
            "w_rockfall_hammer": "weapon_rockfall_hammer.png",
            "w_wind_tachi": "weapon_wind_tachi.png",
            "w_thunder_array": "weapon_thunder_array.png",
            "w_railbow": "weapon_railbow.png",
            "w_ember_drone": "weapon_ember_drone.png",
        }
        for weapon_id, filename in weapon_names.items():
            loaded = self._load_clean_asset(self.v2_assets_dir / "weapons" / filename)
            if loaded is not None:
                self.weapon_icon_sources[weapon_id] = loaded
        for equipment_id in EQUIPMENT_ITEMS:
            loaded = self._load_clean_asset(self.v2_assets_dir / "equipment" / f"{equipment_id}.png")
            if loaded is not None:
                self.equipment_icon_sources[equipment_id] = loaded
        for effect_id, filename in {
            "slash": "fx_slash_light.png", "great_slash": "fx_slash_great_cleaver.png",
            "laser": "fx_laser_cannon_beam.png", "ricochet": "projectile_ricochet_ball.png",
            "enemy_arcane": "projectile_enemy_arcane.png", "enemy_shard": "projectile_enemy_shard.png",
            "enemy_rail": "projectile_enemy_rail.png", "boss_orb": "projectile_boss_orb.png",
            "boss_enrage": "fx_boss_enrage.png", "boss_dash": "fx_boss_dash.png",
            "bomb_warning": "fx_boss_bomb_warning.png",
            "thunder_glyph": "fx_thunder_glyph.png", "thunder_column": "fx_thunder_column.png",
            "thunder_explosion": "fx_thunder_explosion.png", "thunder_residue": "fx_thunder_residue.png",
            "thunder_chain_arc": "fx_thunder_chain_arc.png",
            "roll_trail": "fx_roll_trail.png", "roll_afterimage": "fx_roll_afterimage.png",
            "roll_landing": "fx_roll_landing.png", "roll_spark": "fx_roll_spark.png",
        }.items():
            loaded = self._load_clean_asset(self.v2_assets_dir / "effects" / filename)
            if loaded is not None:
                self.effect_sources[effect_id] = loaded
        for kind, filename in {
            "xp": "pickup_xp.png", "heal": "pickup_heal.png",
            "armor": "pickup_armor.png", "shield_restore": "pickup_shield.png",
        }.items():
            loaded = self._load_clean_asset(self.v2_assets_dir / "pickups" / filename)
            if loaded is not None:
                self.pickup_icon_sources[kind] = loaded
        for rarity, filename in {
            "铜": "card_frame_bronze.png", "银": "card_frame_silver.png", "金": "card_frame_gold.png",
        }.items():
            loaded = self._load_clean_asset(self.v2_assets_dir / "cards" / filename)
            if loaded is not None:
                self.card_frame_sources[rarity] = loaded
        for combo_id in ("steam_burst", "thunder_chain", "corrupt_blood", "focused_lattice", "earth_shock"):
            loaded = self._load_rgba_asset(self.v2_assets_dir / "icons" / "combos" / f"icon_combo_{combo_id}.png")
            if loaded is not None:
                self.combo_icon_sources[combo_id] = loaded
        for affix_id in ENEMY_AFFIXES:
            loaded = self._load_rgba_asset(self.v2_assets_dir / "icons" / "affixes" / f"icon_affix_{affix_id}.png")
            if loaded is not None:
                self.affix_icon_sources[affix_id] = loaded
        for event_id in ("supply_pod", "black_market", "alien_relic", "unstable_energy", "rescue_beacon", "meteor_rain"):
            loaded = self._load_rgba_asset(self.v2_assets_dir / "icons" / "events" / f"icon_event_{event_id}.png")
            if loaded is not None:
                self.event_icon_sources[event_id] = loaded
        for art_id, filename in {
            "combo_panel": "ui_combo_panel.png", "combo_active": "ui_combo_active.png",
            "combo_inactive": "ui_combo_inactive.png", "event_banner": "ui_event_banner.png",
            "challenge_panel": "ui_challenge_panel.png", "hit_flash": "ui_hit_flash.png",
            "invincible": "ui_invincible.png",
        }.items():
            loaded = self._load_rgba_asset(self.v2_assets_dir / "ui" / filename)
            if loaded is not None:
                self.ui_art_sources[art_id] = loaded
        # ===== [新增] 成就图标加载 =====
        self.achievement_icons: dict[str, pygame.Surface] = {}
        from ..achievements.achievements import ACHIEVEMENT_ICON_MAP
        for ach_key, filename in ACHIEVEMENT_ICON_MAP.items():
            icon_path = self.v2_assets_dir / "icons" / "achievements" / f"{filename}.png"
            loaded = self._load_rgba_asset(icon_path)
            if loaded is not None:
                self.achievement_icons[ach_key] = loaded
        for art_id, filename in {
            "weakpoint": "icon_boss_weakpoint.png", "warning_circle": "fx_boss_warning_circle.png",
            "edge_warning": "fx_screen_edge_warning.png", "break_gauge": "ui_boss_break_gauge.png",
        }.items():
            loaded = self._load_rgba_asset(self.v2_assets_dir / "ui" / "boss" / filename)
            if loaded is not None:
                self.boss_ui_sources[art_id] = loaded
        for prop_id, filename in {
            "crate": "prop_abandoned_crate.png", "pillar": "prop_alien_pillar.png",
            "antenna": "prop_broken_antenna.png", "pipe": "prop_cracked_pipe.png",
            "rock": "prop_small_rock.png",
            # === 新场景装饰（生图后启用）===
            "mars_crystal": "prop_mars_crystal.png",
            "dead_robot": "prop_dead_robot.png",
            "energy_barrel": "prop_energy_barrel.png",
            "satellite_dish": "prop_satellite_dish.png",
            "broken_turret": "prop_broken_turret.png",
            "ancient_glyph": "prop_ancient_glyph.png",
        }.items():
            loaded = self._load_rgba_asset(self.v2_assets_dir / "props" / filename)
            if loaded is not None:
                self.prop_sources[prop_id] = loaded
        self._load_feedback_sounds()

    def _load_clean_asset(self, path: Path) -> pygame.Surface | None:
        if not path.exists():
            return None
        try:
            return prepare_character_asset(pygame.image.load(str(path)).convert_alpha())
        except pygame.error:
            return None

    def _load_rgba_asset(self, path: Path) -> pygame.Surface | None:
        """加载已经交付为透明 PNG 的 UI 图标，不再移除白色像素。"""
        if not path.exists():
            return None
        try:
            return pygame.image.load(str(path)).convert_alpha()
        except pygame.error:
            return None

    def _load_feedback_sounds(self) -> None:
        """音频设备不可用时静默回退，不能影响游戏启动。"""
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._audio_ready = True
        except pygame.error:
            return
        sound_dir = self.assets_dir / "audio" / "sfx"
        for event_type, filename in {
            "weapon_synergy_activated": "sfx_combo_activated.wav",
            "random_event_started": "sfx_event_spawn.wav",
            "challenge_completed": "sfx_challenge_complete.wav",
            "challenge_failed": "sfx_challenge_failed.wav",
            "boss_phase_changed": "sfx_boss_phase.wav",
            "boss_broken": "sfx_boss_break.wav",
            "affix_minion_spawned": "sfx_affix_spawn.wav",
            "steam_burst": "sfx_steam_burst.wav",
            "thunder_chain": "sfx_thunder_chain.wav",
            "corrupt_blood": "sfx_corrupt_blood_heal.wav",
            "focused_lattice": "sfx_focused_lattice.wav",
            "earth_shock": "sfx_earth_shock.wav",
        }.items():
            path = sound_dir / filename
            if path.exists():
                try:
                    sound = pygame.mixer.Sound(str(path))
                    sound.set_volume(0.42)
                    self._feedback_sounds[event_type] = sound
                except pygame.error:
                    continue

    def _load_sheet_frames(self, path: Path, *, columns: int = 4, rows: int = 2) -> list[pygame.Surface]:
        if not path.exists():
            return []
        try:
            sheet = pygame.image.load(str(path)).convert_alpha()
        except pygame.error:
            return []
        cell_w = sheet.get_width() // columns
        cell_h = sheet.get_height() // max(1, rows)
        if cell_w <= 0 or cell_h <= 0:
            return []
        frames: list[pygame.Surface] = []
        for row in range(min(rows, sheet.get_height() // cell_h)):
            for col in range(columns):
                cell = sheet.subsurface(pygame.Rect(col * cell_w, row * cell_h, cell_w, cell_h)).copy()
                frames.append(prepare_character_asset(cell))
        return frames

    def _scaled_art(self, source: pygame.Surface | None, key: tuple, size: tuple[int, int]) -> pygame.Surface | None:
        if source is None:
            return None
        target = (max(2, size[0]), max(2, size[1]))
        cache_key = ("__art__", *key, target)
        cached = self._sprite_scale_cache.get(cache_key)
        if cached is not None:
            return cached
        scaled = pygame.transform.smoothscale(source, target)
        self._sprite_scale_cache[cache_key] = scaled
        return scaled

    def _blit_effect(
        self,
        effect_id: str,
        center: tuple[int, int],
        size: tuple[int, int],
        *,
        angle: float = 0.0,
        alpha: int = 255,
        key_extra: tuple = (),
    ) -> bool:
        art = self._scaled_art(self.effect_sources.get(effect_id), (effect_id, *key_extra), size)
        if art is None:
            return False
        img = art.copy()
        if alpha < 255:
            img.set_alpha(max(0, min(255, alpha)))
        if abs(angle) > 0.01:
            img = pygame.transform.rotate(img, angle)
        self.screen.blit(img, img.get_rect(center=center))
        return True

    def _background_surface(self) -> pygame.Surface | None:
        stage = 5 if self.engine.context.mode == "endless" else min(5, self.engine.context.stage_index)
        source = self.stage_bg_sources.get(stage, self.bg_source)
        if source is None:
            return None
        size = (max(1, self.world_rect.w), max(1, self.world_rect.h))
        cache_key = (stage, size[0], size[1])
        if self.bg_scaled is None or self.bg_scaled_key != cache_key:
            self.bg_scaled = pygame.transform.smoothscale(source, size)
            self.bg_scaled_key = cache_key
        return self.bg_scaled

    def _player_sprite(self, size: int, frame_index: int = 0, *, attacking: bool = False) -> pygame.Surface | None:
        frames = self.player_attack_frames if attacking and self.player_attack_frames else self.player_sprite_frames
        source = frames[frame_index % len(frames)] if frames else self.player_sprite_source
        if source is None:
            return None
        target = (max(8, size), max(8, size))
        cache_key = ("__player_attack__" if attacking else "__player__", frame_index % max(1, len(frames)), target)
        cached = self._sprite_scale_cache.get(cache_key)
        if cached is not None:
            return cached
        scaled = pygame.transform.smoothscale(source, target)
        self._sprite_scale_cache[cache_key] = scaled
        return scaled

    def _enemy_sprite(self, config_id: str, size: int, frame_index: int = 0,
                     time_form: str = "T0", damage_level: int = 0) -> pygame.Surface | None:
        """敌人贴图缩放缓存。支持时间形态（T1/T2/T3）和破损（damage1/damage2）变体优先。"""
        src = None
        frames = self.enemy_sprite_frames.get(config_id, [])
        # 破损贴图优先于时间形态（破损是在当前形态上的损坏版本）
        if damage_level > 0:
            src = self.enemy_damage_sprites.get(config_id, {}).get(damage_level)
        if src is None and time_form in ("T1", "T2", "T3"):
            tier = {"T1": 1, "T2": 2, "T3": 3}.get(time_form, 0)
            src = self.enemy_tier_sprites.get(config_id, {}).get(tier)
        if src is None:
            src = frames[frame_index % len(frames)] if frames else self.enemy_sprite_sources.get(config_id)
        if src is None:
            return None
        target = (max(8, size), max(8, size))
        key = (config_id, time_form, damage_level, frame_index % max(1, len(frames)), target)
        cached = self._sprite_scale_cache.get(key)
        if cached is not None:
            return cached
        s = pygame.transform.smoothscale(src, target)
        self._sprite_scale_cache[key] = s
        return s

    def _super_sprite(self, size: int, frame_index: int = 0, *, enraged: bool = False) -> pygame.Surface | None:
        frames = self.super_enraged_frames if enraged and self.super_enraged_frames else self.super_sprite_frames
        source = frames[frame_index % len(frames)] if frames else self.super_sprite_source
        if source is None:
            return None
        target = (max(8, size), max(8, size))
        key = ("__super_enraged__" if enraged else "__super__", frame_index % max(1, len(frames)), target)
        cached = self._sprite_scale_cache.get(key)
        if cached is not None:
            return cached
        s = pygame.transform.smoothscale(source, target)
        self._sprite_scale_cache[key] = s
        return s

    # ---- 事件循环 --------------------------------------------------------

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            self.last_real_dt = dt
            self._poll_events()
            # 引擎 tick 用逻辑 dt，受 LOGIC_DT_MAX 限制
            self.engine.tick(dt)
            if getattr(self.engine, "running_should_exit", False):
                self.running = False
            self._render()
            pygame.display.flip()
        # 关闭
        self.engine._persist_profile()
        self.engine.logger.close()
        pygame.quit()

    def _poll_events(self) -> None:
        # 先用 get_pressed() 设置 baseline，防止输入法拦截 KEYDOWN 导致按键丢失。
        # get_pressed 在 IME 激活、alt-tab 回来后可能短暂全 False，但下一帧会立即恢复，
        # 远比 KEYDOWN 被输入法吃掉导致完全不能动要好。
        self._sync_keyboard_state()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                return
            elif ev.type == pygame.KEYDOWN:
                self._on_key_down(ev)
            elif ev.type == pygame.KEYUP:
                self._on_key_up(ev)
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                self._on_mouse(ev)
            elif ev.type == pygame.MOUSEMOTION:
                self._on_motion(ev)
            elif ev.type == pygame.MOUSEBUTTONUP:
                self._on_mouse_up(ev)
            elif ev.type == pygame.VIDEORESIZE:
                self._resize(ev.w, ev.h)
            elif ev.type == pygame.WINDOWFOCUSLOST:
                self._clear_movement_keys()
            elif ev.type == pygame.WINDOWFOCUSGAINED:
                self._sync_keyboard_state()
        self._poll_keyboard_shortcuts()
        self._update_mouse_movement()

    def _clear_movement_keys(self) -> None:
        for key in ("w", "a", "s", "d"):
            self.keyboard.update_key(key, False)

    def _sync_keyboard_state(self) -> None:
        keys = pygame.key.get_pressed()
        self.keyboard.update_key("w", bool(keys[pygame.K_w] or keys[pygame.K_UP]))
        self.keyboard.update_key("a", bool(keys[pygame.K_a] or keys[pygame.K_LEFT]))
        self.keyboard.update_key("s", bool(keys[pygame.K_s] or keys[pygame.K_DOWN]))
        self.keyboard.update_key("d", bool(keys[pygame.K_d] or keys[pygame.K_RIGHT]))

    def _poll_keyboard_shortcuts(self) -> None:
        keys = pygame.key.get_pressed()
        now = {
            "j": bool(keys[pygame.K_j]),
            "k": bool(keys[pygame.K_k]),
            "q": bool(keys[pygame.K_q]),
            "l": bool(keys[pygame.K_l]),
        }
        st = self.engine.state()
        if now["j"] and not self._polled_shortcut_state["j"] and st == "RUNNING":
            self.keyboard.request_active_skill()
        if (now["k"] and not self._polled_shortcut_state["k"] or now["q"] and not self._polled_shortcut_state["q"]) and st == "RUNNING":
            self.keyboard.request_switch()
        if now["l"] and not self._polled_shortcut_state["l"] and st == "MAIN_MENU":
            self.show_history = True
        self._polled_shortcut_state = now

    def _on_key_down(self, ev) -> None:
        if self.login_active:
            self._handle_login_key(ev)
            return
        if self.show_achievements:
            if ev.key == pygame.K_ESCAPE:
                self.show_achievements = False
                return
            count = max(1, len(self.engine.bundle.achievements))
            if ev.key in (pygame.K_a, pygame.K_LEFT):
                self.achievement_selected_index = (self.achievement_selected_index - 1) % count
            elif ev.key in (pygame.K_d, pygame.K_RIGHT):
                self.achievement_selected_index = (self.achievement_selected_index + 1) % count
            elif ev.key in (pygame.K_w, pygame.K_UP):
                self.achievement_selected_index = (self.achievement_selected_index - 3) % count
            elif ev.key in (pygame.K_s, pygame.K_DOWN):
                self.achievement_selected_index = (self.achievement_selected_index + 3) % count
            return
        if self.show_shop:
            if ev.key == pygame.K_ESCAPE:
                self.show_shop = False
                return
            if ev.key in (pygame.K_a, pygame.K_LEFT):
                self.shop_category_index = (self.shop_category_index - 1) % len(self._shop_categories())
                self.shop_selected_index = 0
                return
            if ev.key in (pygame.K_d, pygame.K_RIGHT):
                self.shop_category_index = (self.shop_category_index + 1) % len(self._shop_categories())
                self.shop_selected_index = 0
                return
            if ev.key in (pygame.K_w, pygame.K_UP):
                self.shop_selected_index = (self.shop_selected_index - 1) % max(1, len(self._shop_entries()))
                return
            if ev.key in (pygame.K_s, pygame.K_DOWN):
                self.shop_selected_index = (self.shop_selected_index + 1) % max(1, len(self._shop_entries()))
                return
            if ev.key == pygame.K_SLASH:
                self._shop_search_input = ""
                self.shop_selected_index = 0
                return
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self._buy_selected_shop_item()
                return
        if self.show_history:
            if ev.key == pygame.K_ESCAPE:
                self.show_history = False
                return
            if ev.key in (pygame.K_w, pygame.K_UP):
                runs = getattr(self.engine.profile, "recent_runs_summary", []) or []
                self.history_selected_index = (self.history_selected_index - 1) % max(1, len(runs[:30]))
                return
            if ev.key in (pygame.K_s, pygame.K_DOWN):
                runs = getattr(self.engine.profile, "recent_runs_summary", []) or []
                self.history_selected_index = (self.history_selected_index + 1) % max(1, len(runs[:30]))
                return
        if ev.key == pygame.K_ESCAPE:
            if self.show_history:
                self.show_history = False
                return
            # T2：PAUSED 状态让 _handle_pause_key 接管（↑/↓ 切换 + Enter 确认 + Esc = 继续）
            if self.engine.state() == "PAUSED":
                self._handle_pause_key(ev.key)
                return
            self.keyboard.request_pause()
            return
        if ev.key == pygame.K_l and self.engine.state() == "MAIN_MENU":
            self.show_history = True
            return
        if self._handle_menu_key(ev.key):
            return
        # T2：PAUSED 状态下其他按键也走暂停菜单
        if self.engine.state() == "PAUSED":
            self._handle_pause_key(ev.key)
            return
        if ev.key in (pygame.K_k, pygame.K_q):
            self.keyboard.request_switch()
            return
        if ev.key == pygame.K_j:
            self.keyboard.request_active_skill()
            return
        if ev.key == pygame.K_r:
            self.keyboard.request_refresh()
            return
        if ev.key in (pygame.K_1, pygame.K_2, pygame.K_3):
            self.keyboard._select_index_requested = ev.key - pygame.K_1
            return
        movement_keys = {
            pygame.K_w: "w", pygame.K_UP: "w", pygame.K_a: "a", pygame.K_LEFT: "a",
            pygame.K_s: "s", pygame.K_DOWN: "s", pygame.K_d: "d", pygame.K_RIGHT: "d",
        }
        if ev.key in movement_keys:
            self._mouse_move_target = None
            self.touch.on_touch_release(0)
            self.keyboard.update_key(movement_keys[ev.key], True)
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.keyboard._select_index_requested = 0
        if ev.key == pygame.K_m:
            self.engine._persist_profile()

    def _login_account(self) -> None:
        account = (self.account_input or "default").strip() or "default"
        self.account_input = account
        path = profile_path_for_account(self._save_path, account)
        self.engine.switch_account(account, save_path=path)
        self.account_history = record_account_history(self._save_path, account)
        self.login_active = False
        self.show_history = False
        self.show_achievements = False
        self.show_shop = False

    def _login_options(self) -> list[tuple[str, str]]:
        options = [("account", account) for account in getattr(self, "account_history", [])[:3]]
        options.append(("new", "新建账号"))
        return options

    def _open_login_overlay(self) -> None:
        self.account_history = load_account_history(self._save_path)
        current = getattr(self.engine.profile, "account_name", "default") or "default"
        self.account_input = current
        self.login_selected_index = 0
        self.login_typing_new = not bool(self.account_history)
        for i, account in enumerate(self.account_history[:3]):
            if account.strip().lower() == current.strip().lower():
                self.login_selected_index = i
                self.login_typing_new = False
                break
        self.login_active = True

    def _handle_login_key(self, ev) -> None:
        options = self._login_options()
        self.login_selected_index = max(0, min(self.login_selected_index, len(options) - 1))
        if ev.key in (pygame.K_w, pygame.K_UP, pygame.K_a, pygame.K_LEFT):
            self.login_selected_index = (self.login_selected_index - 1) % len(options)
            kind, value = options[self.login_selected_index]
            self.login_typing_new = kind == "new"
            if kind == "account":
                self.account_input = value
            else:
                self.account_input = ""
            return
        if ev.key in (pygame.K_s, pygame.K_DOWN, pygame.K_d, pygame.K_RIGHT):
            self.login_selected_index = (self.login_selected_index + 1) % len(options)
            kind, value = options[self.login_selected_index]
            self.login_typing_new = kind == "new"
            if kind == "account":
                self.account_input = value
            else:
                self.account_input = ""
            return
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            kind, value = options[self.login_selected_index]
            if kind == "account":
                self.account_input = value
                self._login_account()
            else:
                if not self.login_typing_new:
                    self.account_input = ""
                    self.login_typing_new = True
                else:
                    self._login_account()
            return
        if ev.key == pygame.K_ESCAPE:
            if self.login_typing_new and self.account_history:
                self.login_typing_new = False
                self.login_selected_index = 0
                self.account_input = self.account_history[0]
            else:
                self.account_input = "default"
                self._login_account()
            return
        if ev.key == pygame.K_BACKSPACE and self.login_typing_new:
            self.account_input = self.account_input[:-1]
            return
        if ev.unicode and ev.unicode.isprintable() and self.login_typing_new and len(self.account_input) < 24:
            self.account_input += ev.unicode
            return

    def _enqueue_notice(self, key: str, payload: dict, *, ttl: float, time_attr: str | None = None) -> None:
        """把一条通知压入中央顶部的槽位队列，旧的过期后让位。

        子报告 P0-2：原本 4 条通知 y 都贴 world_rect.y+100/+164/+202，互相覆盖。
        """
        now = self.engine.timer.run_time
        # 已被覆盖就直接跳过
        existing = self._notice_state.get(key)
        if existing is not None:
            existing["payload"] = payload
            existing["ttl"] = ttl
            existing["started_at"] = now
            return
        entry = {"payload": payload, "ttl": max(0.2, float(ttl)), "started_at": now, "time_attr": time_attr}
        self._notice_state[key] = entry
        self._notice_order.append(key)
        while len(self._notice_order) > max(1, int(self._notice_capacity)):
            old = self._notice_order.pop(0)
            self._notice_state.pop(old, None)

    def _draw_notice_stack(self, top_y: int) -> None:
        """在 world_rect.y + 一定偏移逐条渲染通知，互斥按 _notice_order。"""
        now = self.engine.timer.run_time
        # 清掉过期
        alive: list[str] = []
        for key in list(self._notice_order):
            entry = self._notice_state.get(key)
            if entry is None:
                continue
            if now - entry["started_at"] > entry["ttl"]:
                self._notice_state.pop(key, None)
                continue
            alive.append(key)
        self._notice_order = alive

        slot_h = int(self._notice_slot_height * self.scale)
        gap = int(8 * self.scale)
        y = top_y + int(10 * self.scale)
        for i, key in enumerate(self._notice_order):
            entry = self._notice_state.get(key)
            if entry is None:
                continue
            self._draw_notice_slot(key, entry, y + i * (slot_h + gap), slot_h)
            if i + 1 >= max(1, int(self._notice_capacity)):
                break

    def _draw_notice_slot(self, key: str, entry: dict, y: int, slot_h: int) -> None:
        payload = entry.get("payload", {}) or {}
        if key == "random_event":
            text = f"事件：{payload.get('name', '')}  {int(payload.get('left', 0))}s"
            color = T.ACCENT_3
            desc = payload.get("desc", "")
            rect = pygame.Rect(self.world_rect.centerx - 250, y, 500, slot_h)
            draw_panel(self.screen, rect, border=T.ACCENT_3, fill=T.BG_PANEL, alpha=218, radius=12, outline=3)
            icon = self._scaled_art(self.event_icon_sources.get(payload.get("id", "")), ("event", payload.get("id", "")), (slot_h - 8, slot_h - 8))
            if icon is not None:
                self.screen.blit(icon, icon.get_rect(center=(rect.x + 24, rect.centery)))
            draw_text_center(self.screen, text, pygame.Rect(rect.x + 48, rect.y + 4, rect.w - 60, slot_h - 24), color=color, font=self.font_small, outline=1, size=14)
            if desc:
                draw_text_center(self.screen, desc, pygame.Rect(rect.x + 48, rect.y + slot_h - 22, rect.w - 60, 20), color=T.TEXT_DIM, font=self.font_small, outline=1, size=12)
        elif key == "weapon_synergy":
            text = f"组合技激活：{payload.get('name', '')}"
            rect = pygame.Rect(self.world_rect.centerx - 220, y, 440, slot_h - 8)
            draw_panel(self.screen, rect, border=T.CARD_GOLD, fill=T.BG_PANEL, alpha=220, radius=12, outline=3)
            draw_text_center(self.screen, text, rect, color=T.CARD_GOLD, font=self.font, outline=2, size=18)
        elif key == "challenge":
            text = f"挑战完成：{payload.get('name', '')}"
            rect = pygame.Rect(self.world_rect.centerx - 220, y, 440, slot_h - 8)
            draw_panel(self.screen, rect, border=T.ACCENT, fill=T.BG_PANEL, alpha=220, radius=12, outline=3)
            draw_text_center(self.screen, text, rect, color=T.ACCENT, font=self.font, outline=2, size=18)
        elif key == "killstreak":
            text = f"{int(payload.get('count', 0))} 连杀！"
            rect = pygame.Rect(self.world_rect.centerx - 130, y, 260, slot_h - 8)
            draw_panel(self.screen, rect, border=T.CARD_COLOR, fill=T.BG_PANEL, alpha=220, radius=12, outline=3)
            draw_text_center(self.screen, text, rect, color=T.CARD_COLOR, font=self.font_mid, outline=2, size=24)
        else:
            return

    def _shop_entries(self) -> list[tuple[str, dict]]:
        base = list(SHOP_ITEMS.items())
        # P9：tab + 搜索过滤
        key = self._shop_categories()[self.shop_category_index % len(self._shop_categories())][0]
        return self._shop_filter(base, key, getattr(self, "_shop_search_input", ""))

    # ---- T1: 战内面板激活态 -------------------------------------------------
    @staticmethod
    def _build_progress_summary(card_combo_counts: dict, combo_unlocked: set, weapon_synergy: list) -> dict:
        """返回左下"常驻面板"的内容：无任何进度时 visible=False，整个面板隐藏。

        - 集卡共鸣：只列 count>0 的组合键
        - 武器组合技：只列 active=True 的行
        - 至少有一项有进度时 visible=True
        """
        active_cards = {k: min(3, int(v)) for k, v in card_combo_counts.items() if int(v) > 0}
        card_rows = [
            {"id": k, "count": c, "done": k in combo_unlocked}
            for k, c in active_cards.items()
        ]
        weapon_rows = [r for r in weapon_synergy if r.get("active")]
        return {
            "visible": bool(card_rows) or bool(weapon_rows),
            "card_rows": card_rows,
            "weapon_rows": weapon_rows,
        }

    # ---- T2: 暂停选项布局 --------------------------------------------------
    @staticmethod
    def _build_pause_layout(width: int, height: int) -> dict:
        """暂停 3 选项矩形：继续 / 重开当前 / 返回主菜单"""
        base = min(width, height)
        pw = min(int(0.65 * base), width - 80)
        ph = int(0.45 * base)
        panel = pygame.Rect((width - pw) // 2, (height - ph) // 2, pw, ph)
        title = pygame.Rect(panel.x, panel.y + int(0.04 * ph), panel.w, int(0.16 * ph))
        btn_w = min(int(0.55 * base), panel.w - int(0.18 * pw))
        btn_h = int(0.10 * base)
        gap = int(0.02 * base)
        y = title.bottom + int(0.06 * ph)
        btns = []
        for _ in range(3):
            b = pygame.Rect(panel.centerx - btn_w // 2, y, btn_w, btn_h)
            btns.append(b)
            y += btn_h + gap
        return {"panel": panel, "title": title, "buttons": btns}

    # ---- T3: 开局装备 / 核心 / 技能 选择逻辑 ------------------------------
    @staticmethod
    def _default_equipment_selection(pool: list, slot_count: int = 2) -> list:
        """从已解锁池默认填满前 slot_count 个；池为空返回空列表。"""
        if not pool:
            return []
        return list(pool[:slot_count])

    @staticmethod
    def _skill_preview(skill_id: str) -> dict:
        previews = {
            "bomb_trap": {
                "name": "四雷爆破",
                "cooldown": 18.0,
                "desc": "放下延时雷阵，造成大范围雷元素伤害。",
                "difficulty": "简单",
            },
            "roll": {
                "name": "翻滚位移",
                "cooldown": 5.0,
                "desc": "短距离无敌闪避，可穿过弹幕与窄缝。",
                "difficulty": "简单",
            },
            "axe_orbit": {
                "name": "斧刃格挡",
                "cooldown": 20.0,
                "desc": "身边环绕三片刃，反弹并切割来袭弹。",
                "difficulty": "中等",
            },
        }
        return previews.get(skill_id, {"name": skill_id, "cooldown": 0.0, "desc": "", "difficulty": ""})

    def _shop_categories(self) -> list[tuple[str, str]]:
        return [("all", "全部"), ("weapon", "武器"), ("equipment", "装备"), ("upgrade", "强化")]

    def _buy_selected_shop_item(self) -> None:
        entries = self._shop_entries()
        if not entries:
            return
        self.shop_selected_index = max(0, min(self.shop_selected_index, len(entries) - 1))
        self.engine.purchase_shop_item(entries[self.shop_selected_index][0])

    def _shop_page_start(self, count: int, visible_count: int = 6) -> int:
        if count <= visible_count:
            return 0
        return max(0, min(self.shop_selected_index - visible_count // 2, count - visible_count))

    def _pool_page_start(self, count: int, focus_index: int, visible_count: int = 7) -> int:
        if count <= visible_count:
            return 0
        return max(0, min(focus_index - visible_count // 2, count - visible_count))

    def _on_key_up(self, ev) -> None:
        movement_keys = {
            pygame.K_w: "w", pygame.K_UP: "w", pygame.K_a: "a", pygame.K_LEFT: "a",
            pygame.K_s: "s", pygame.K_DOWN: "s", pygame.K_d: "d", pygame.K_RIGHT: "d",
        }
        if ev.key in movement_keys:
            self.keyboard.update_key(movement_keys[ev.key], False)

    def _on_mouse(self, ev) -> None:
        if ev.button == 3:
            self._mouse_move_target = None
            self.touch.on_touch_release(0)
            return
        if ev.button != 1:
            return
        x, y = ev.pos
        # pause
        if self._pause_rect().collidepoint(x, y):
            self.keyboard.request_pause()
            return
        # 右下角可见武器槽可直接点击装备。
        if self.engine.state() == "RUNNING":
            for i in range(len(self.engine.weapon_sys.stack)):
                if self._weapon_slot_rect(i).collidepoint(x, y):
                    self.keyboard.request_weapon_index(i)
                    return
        # 菜单 / 卡牌点击（由系统 UI 命中区域处理）
        self._handle_ui_click(x, y)
        if self.engine.state() == "RUNNING" and self.world_rect.collidepoint(x, y):
            self._mouse_move_target = self._screen_to_world((x, y))

    def _on_motion(self, ev) -> None:
        if self.engine.state() == "RUNNING" and ev.buttons[0] and self.world_rect.collidepoint(ev.pos):
            self._mouse_move_target = self._screen_to_world(ev.pos)

    def _on_mouse_up(self, ev) -> None:
        pass

    def _screen_to_world(self, pos: tuple[int, int]) -> tuple[float, float]:
        x = (pos[0] - self.world_rect.x) / max(0.0001, self.scale)
        y = (pos[1] - self.world_rect.y) / max(0.0001, self.scale)
        return (
            max(48.0, min(SCREEN_WIDTH - 48.0, x)),
            max(48.0, min(SCREEN_HEIGHT - 48.0, y)),
        )

    def _update_mouse_movement(self) -> None:
        if self.engine.state() != "RUNNING" or self._mouse_move_target is None:
            self.touch.on_touch_release(0)
            return
        px, py = self.engine.player.position
        dx = self._mouse_move_target[0] - px
        dy = self._mouse_move_target[1] - py
        distance = math.hypot(dx, dy)
        if distance <= 14:
            self._mouse_move_target = None
            self.touch.on_touch_release(0)
            return
        r = self.touch.joy_radius
        jx, jy = self.touch.joy_center
        self.touch._stick_pos = (jx + dx / distance * r, jy + dy / distance * r)

    def _resize(self, w: int, h: int) -> None:
        if w < 320: w = 320
        if h < 240: h = 240
        self.screen_w = w
        self.screen_h = h
        self.screen = pygame.display.set_mode((self.screen_w, self.screen_h), pygame.RESIZABLE)
        self.scale = min(self.screen_w / SCREEN_WIDTH, self.screen_h / SCREEN_HEIGHT)
        self.world_rect = pygame.Rect(0, 0, int(SCREEN_WIDTH * self.scale), int(SCREEN_HEIGHT * self.scale))
        self.world_rect.center = (self.screen_w // 2, self.screen_h // 2)
        # 重新设置摇杆 / 按钮位置
        safe = SAFE_INSET.get(self.platform, SAFE_INSET["win"])
        joy_radius = int(0.06 * min(self.screen_w, self.screen_h))
        self.touch.joy_center = (safe["left"] + joy_radius + 24, self.screen_h - safe["bottom"] - joy_radius - 24)
        self.touch.joy_radius = joy_radius
        # 同步全局 UI 字号缩放，并清理旧窗口尺寸的 UI 缓存。
        self._refresh_fonts()
        self._sprite_scale_cache.clear()
        self._scene_overlay_cache.clear()
        self.bg_scaled = None
        self.bg_scaled_key = None

    # ---- UI 区域（屏幕坐标）------------------------------------------------

    def _switch_rect(self) -> pygame.Rect:
        safe = SAFE_INSET.get(self.platform, SAFE_INSET["win"])
        btn_size = max(56, int(0.06 * min(self.screen_w, self.screen_h)))
        return pygame.Rect(self.screen_w - safe["right"] - btn_size - 24, self.screen_h - safe["bottom"] - btn_size - 24, btn_size, btn_size)

    def _weapon_slot_rect(self, index: int) -> pygame.Rect:
        weapon_y = self.world_rect.bottom - 108
        weapon_x = self.world_rect.right - 344
        return pygame.Rect(weapon_x + index * 112, weapon_y, 104, 72)

    def _pause_rect(self) -> pygame.Rect:
        safe = SAFE_INSET.get(self.platform, SAFE_INSET["win"])
        pause_size = max(48, int(0.05 * min(self.screen_w, self.screen_h)))
        return pygame.Rect(self.screen_w - safe["right"] - pause_size - 24, safe["top"] + 24, pause_size, pause_size)

    def _joystick_rect(self) -> pygame.Rect:
        jx, jy = self.touch.joy_center
        r = self.touch.joy_radius
        return pygame.Rect(jx - r, jy - r, r * 2, r * 2)

    def _handle_ui_click(self, x: int, y: int) -> None:
        st = self.engine.state()
        # 子报告 P0-3：游戏中点击右上暂停按钮立即触发暂停。
        if st == "RUNNING" and self._pause_rect().collidepoint(x, y):
            self.keyboard.request_pause()
            return
        if self.login_active:
            panel = pygame.Rect(self.screen_w // 2 - 330, self.screen_h // 2 - 230, 660, 460)
            login_btn = pygame.Rect(self.screen_w // 2 - 150, panel.bottom - 66, 300, 52)
            options = self._login_options()
            for i, (kind, value) in enumerate(options):
                row = pygame.Rect(panel.x + 90, panel.y + 226 + i * 40, panel.w - 180, 36)
                if row.collidepoint(x, y):
                    self.login_selected_index = i
                    self.login_typing_new = kind == "new"
                    if kind == "account":
                        self.account_input = value
                        self._login_account()
                    else:
                        self.account_input = ""
                    return
            if login_btn.collidepoint(x, y):
                kind, value = options[self.login_selected_index]
                if kind == "account":
                    self.account_input = value
                elif not self.login_typing_new:
                    self.account_input = ""
                    self.login_typing_new = True
                    return
                self._login_account()
                return
            return
        if self.show_achievements:
            panel = pygame.Rect(self.screen_w // 2 - 560, 70, 1120, min(640, self.screen_h - 120))
            close = pygame.Rect(panel.right - 60, panel.y + 18, 42, 42)
            if close.collidepoint(x, y):
                self.show_achievements = False
            return
        if self.show_shop:
            panel = pygame.Rect(self.screen_w // 2 - 560, 70, 1120, min(640, self.screen_h - 120))
            close = pygame.Rect(panel.right - 60, panel.y + 18, 42, 42)
            if close.collidepoint(x, y):
                self.show_shop = False
                return
            for i, _cat in enumerate(self._shop_categories()):
                tab = pygame.Rect(panel.x + 34 + i * 116, panel.y + 108, 104, 38)
                if tab.collidepoint(x, y):
                    self.shop_category_index = i
                    self.shop_selected_index = 0
                    return
            entries = self._shop_entries()
            first = self._shop_page_start(len(entries), visible_count=5)
            list_panel = pygame.Rect(panel.x + 30, panel.y + 158, 540, 382)
            for offset, _entry in enumerate(entries[first:first + 5]):
                i = first + offset
                row = pygame.Rect(list_panel.x + 14, list_panel.y + 16 + offset * 70, list_panel.w - 28, 60)
                if row.collidepoint(x, y):
                    self.shop_selected_index = i
                    return
            detail_panel = pygame.Rect(panel.x + 590, panel.y + 158, panel.w - 620, 260)
            buy = pygame.Rect(detail_panel.right - 188, detail_panel.bottom - 58, 160, 44)
            if buy.collidepoint(x, y):
                self._buy_selected_shop_item()
                return
            return
        if self.show_history:
            panel = pygame.Rect(self.screen_w // 2 - 520, 92, 1040, min(600, self.screen_h - 140))
            close = pygame.Rect(panel.right - 60, panel.y + 18, 42, 42)
            if close.collidepoint(x, y):
                self.show_history = False
                return
            runs = list(getattr(self.engine.profile, "recent_runs_summary", []) or [])
            first = self._history_page_start(runs)
            visible = runs[first:first + 6]
            for offset, _run in enumerate(visible):
                row = pygame.Rect(panel.x + 28, panel.y + 96 + offset * 78, 420, 66)
                if row.collidepoint(x, y):
                    self.history_selected_index = first + offset
                    return
            return
        # 模式选择：屏幕中央 3 个按钮
        if st == "MODE_SELECT":
            cw, ch = self.screen_w, self.screen_h
            for i, label in enumerate(["常规关 1-5", "无尽模式（已解锁）" if self.engine.profile.campaign_cleared else "无尽模式（未解锁）", "返回"]):
                btn = pygame.Rect(cw // 2 - 220, 200 + i * 84, 440, 72)
                if btn.collidepoint(x, y):
                    self.keyboard.request_select(i)
                    return
        elif st == "PRESET_SELECT":
            cw, ch = self.screen_w, self.screen_h
            for i, label in enumerate(["武器槽 1", "武器槽 2", "装备槽 1", "装备槽 2", "开始游戏"]):
                btn = pygame.Rect(cw // 2 - 565, 190 + i * 66, 310, 54)
                if btn.collidepoint(x, y):
                    self.selection_state["preset"] = i
                    if i in (0, 1):
                        self.weapon_config_slot = i
                    elif i in (2, 3):
                        self.equipment_config_slot = i - 2
                    else:
                        self.engine.active_skill_id = self.skill_ids[self.skill_select_index]
                        self.keyboard.request_select(0)
                    return
            active_slot = self.selection_state["preset"]
            if active_slot in (0, 1, 2, 3):
                is_equipment = active_slot in (2, 3)
                pool = self.engine.account_equipment_pool() if is_equipment else self.engine.account_weapon_pool()
                focus = self.equipment_pool_index if is_equipment else self.weapon_pool_index
                first = self._pool_page_start(len(pool), focus, 5)
                list_rect = pygame.Rect(cw // 2 - 181, 190, 742, 302)
                for offset, item_id in enumerate(pool[first:first + 5]):
                    i = first + offset
                    row = pygame.Rect(list_rect.x + 12, list_rect.y + 8 + offset * 58, list_rect.w - 24, 52)
                    if row.collidepoint(x, y):
                        if is_equipment:
                            self.equipment_pool_index = i
                            self.equipment_config_slot = active_slot - 2
                            self.engine.select_equipment(item_id, slot=self.equipment_config_slot)
                        else:
                            self.weapon_pool_index = i
                            self.weapon_config_slot = active_slot
                            self.engine.select_starting_weapon(item_id, slot=self.weapon_config_slot)
                        return
            for i in range(3):
                chip = pygame.Rect(cw // 2 - 330 + i * 220, 560, 200, 48)
                if chip.collidepoint(x, y):
                    self.skill_select_index = i
                    return
        elif st == "CARD_SELECT":
            cw = self.screen_w
            for i in range(3):
                btn = pygame.Rect(cw // 2 - 380 + i * 260, self.screen_h - 360, 240, 320)
                if btn.collidepoint(x, y):
                    self.keyboard.request_select(i)
                    return
            refresh = pygame.Rect(self.screen_w - 280, self.screen_h - 200, 240, 60)
            if refresh.collidepoint(x, y):
                self.keyboard.request_refresh()
                return
        elif st == "LEVEL_UP":
            cw = self.screen_w
            for i in range(3):
                btn = pygame.Rect(cw // 2 - 380 + i * 260, self.screen_h - 360, 240, 320)
                if btn.collidepoint(x, y):
                    self.keyboard.request_select(i)
                    return
        elif st == "RESULT":
            for i in range(3):
                btn = pygame.Rect(self.screen_w // 2 - 200, self.screen_h - 360 + i * 80, 400, 68)
                if btn.collidepoint(x, y):
                    self.keyboard.request_select(i)
                    return
        elif st == "STAGE_CLEAR":
            btn = pygame.Rect(self.screen_w // 2 - 150, self.screen_h - 200, 300, 60)
            if btn.collidepoint(x, y):
                self.keyboard.request_select(0)
                return
        elif st == "MAIN_MENU":
            for i in range(6):
                btn = pygame.Rect(self.screen_w // 2 - 160, 324 + i * 62, 320, 54)
                if btn.collidepoint(x, y):
                    self.selection_state["main"] = i
                    if i == 1:
                        self.show_shop = True
                    elif i == 2:
                        self.show_achievements = True
                    elif i == 3:
                        self.show_history = True
                    elif i == 4:
                        self._open_login_overlay()
                    elif i == 5:
                        self.keyboard.request_select(5)
                    else:
                        self.keyboard.request_select(i)
                    return

    def _handle_menu_key(self, key: int) -> bool:
        st = self.engine.state()
        if st not in ("MAIN_MENU", "MODE_SELECT", "PRESET_SELECT", "RESULT", "CARD_SELECT", "LEVEL_UP", "STAGE_CLEAR"):
            return False
        counts = {"MAIN_MENU": 6, "MODE_SELECT": 3, "PRESET_SELECT": 5, "RESULT": 3, "CARD_SELECT": 3, "LEVEL_UP": 3, "STAGE_CLEAR": 1}
        state_key = {
            "MAIN_MENU": "main",
            "MODE_SELECT": "mode",
            "PRESET_SELECT": "preset",
            "RESULT": "result",
            "CARD_SELECT": "card",
            "LEVEL_UP": "level",
            "STAGE_CLEAR": "level",
        }[st]
        if st == "PRESET_SELECT" and key in (pygame.K_a, pygame.K_LEFT):
            if self.selection_state["preset"] == 4:
                return True
            if self.selection_state["preset"] in (2, 3):
                pool = self.engine.account_equipment_pool()
                self.equipment_pool_index = (self.equipment_pool_index - 1) % max(1, len(pool))
            else:
                pool = self.engine.account_weapon_pool()
                self.weapon_pool_index = (self.weapon_pool_index - 1) % max(1, len(pool))
            return True
        if st == "PRESET_SELECT" and key in (pygame.K_d, pygame.K_RIGHT):
            if self.selection_state["preset"] == 4:
                return True
            if self.selection_state["preset"] in (2, 3):
                pool = self.engine.account_equipment_pool()
                self.equipment_pool_index = (self.equipment_pool_index + 1) % max(1, len(pool))
            else:
                pool = self.engine.account_weapon_pool()
                self.weapon_pool_index = (self.weapon_pool_index + 1) % max(1, len(pool))
            return True
        if st == "PRESET_SELECT" and key in (pygame.K_q, pygame.K_a, pygame.K_LEFT):
            # T3：技能左切也支持 A/Left（保留 Q 历史键位）
            self.skill_select_index = (self.skill_select_index - 1) % len(self.skill_ids)
            return True
        if st == "PRESET_SELECT" and key in (pygame.K_e, pygame.K_d, pygame.K_RIGHT):
            self.skill_select_index = (self.skill_select_index + 1) % len(self.skill_ids)
            return True
        if key in (pygame.K_w, pygame.K_UP):
            self.selection_state[state_key] = (self.selection_state[state_key] - 1) % counts[st]
            return True
        if key in (pygame.K_s, pygame.K_DOWN):
            self.selection_state[state_key] = (self.selection_state[state_key] + 1) % counts[st]
            return True
        if st in ("CARD_SELECT", "LEVEL_UP") and key in (pygame.K_a, pygame.K_LEFT):
            self.selection_state[state_key] = (self.selection_state[state_key] - 1) % counts[st]
            return True
        if st in ("CARD_SELECT", "LEVEL_UP") and key in (pygame.K_d, pygame.K_RIGHT):
            self.selection_state[state_key] = (self.selection_state[state_key] + 1) % counts[st]
            return True
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            idx = self.selection_state[state_key]
            if st == "MAIN_MENU" and idx == 1:
                self.show_shop = True
            elif st == "MAIN_MENU" and idx == 2:
                self.show_achievements = True
            elif st == "MAIN_MENU" and idx == 3:
                self.show_history = True
            elif st == "MAIN_MENU" and idx == 4:
                self._open_login_overlay()
            elif st == "PRESET_SELECT" and idx in (0, 1):
                self.weapon_config_slot = idx
                pool = self.engine.account_weapon_pool()
                if pool:
                    self.weapon_pool_index = max(0, min(self.weapon_pool_index, len(pool) - 1))
                    self.engine.select_starting_weapon(pool[self.weapon_pool_index], slot=idx)
            elif st == "PRESET_SELECT" and idx in (2, 3):
                self.equipment_config_slot = idx - 2
                pool = self.engine.account_equipment_pool()
                if pool:
                    self.equipment_pool_index = max(0, min(self.equipment_pool_index, len(pool) - 1))
                    self.engine.select_equipment(pool[self.equipment_pool_index], slot=self.equipment_config_slot)
            else:
                if st == "PRESET_SELECT":
                    self.engine.active_skill_id = self.skill_ids[self.skill_select_index]
                    idx = 0
                if st == "STAGE_CLEAR":
                    idx = 0
                self.keyboard.request_select(idx)
            return True
        return False

    # ---- 渲染 -------------------------------------------------------------

    def _render(self) -> None:
        self.screen.fill(T.BG_DARK)
        st = self.engine.state()
        if st == "RESULT":
            self._set_music_track("bgm_result")
        elif st in ("RUNNING", "PAUSED", "CARD_SELECT", "LEVEL_UP", "SUPER_WARNING", "STAGE_CLEAR"):
            if self.engine.super_director.active is not None:
                self._set_music_track("bgm_boss")
            elif self.engine.active_random_event is not None:
                self._set_music_track("bgm_event_layer")
            else:
                self._set_music_track("bgm_normal_stage")
        else:
            self._set_music_track(None)
        if st in ("MAIN_MENU", "MODE_SELECT", "PRESET_SELECT", "RESULT", "BOOT", "ERROR"):
            self._render_menu(st)
            # HUD 隐藏
        else:
            self._render_world()
            self._render_hud(st)
            if st == "PAUSED":
                self._render_pause_overlay()
            elif st == "CARD_SELECT":
                self._render_card_select()
            elif st == "LEVEL_UP":
                self._render_level_up()
            elif st == "SUPER_WARNING":
                self._render_super_warning()
            elif st == "STAGE_CLEAR":
                self._render_stage_clear()
        # 成就提示（按文档：2.5s，不暂停）
        if self.engine.ach_sys.notifications:
            self._render_achievement_notice()
        if self.show_shop:
            self._render_shop_overlay()
        if self.show_achievements:
            self._render_achievements_overlay()
        if self.show_history:
            self._render_history_overlay()
        if self.login_active:
            self._render_login_overlay()
        # FPS
        draw_text(self.screen, f"帧率 {self.engine.debug.fps:.1f}", (8, 8), size=14, color=T.TEXT_DIM, font=self.font_small, outline=1)

    def _world_to_screen(self, pos):
        shake = int(5 * self.scale) if self._screen_shake > 0 else 0
        ox = int(math.sin(self.engine.timer.run_time * 88) * shake)
        oy = int(math.cos(self.engine.timer.run_time * 73) * shake)
        x = self.world_rect.x + pos[0] * self.scale + ox
        y = self.world_rect.y + pos[1] * self.scale + oy
        return (int(x), int(y))

    def _render_world(self) -> None:
        self._sync_combat_feedback()
        # 1. 背景阶段
        self._render_background()
        # 2. 危险炸弹提示（先画，玩家最清楚）
        for b in self.engine.drop_sys.bombs:
            self._draw_bomb(b)
        # 3. 玩家
        self._draw_player()
        self._render_active_skill_effects()
        # 4. 敌人 / 超级怪兽
        for e in self.engine.spawn_director.enemies:
            self._draw_enemy(e)
        # 5. 投射物
        for p in self.engine.projectile_sys.projectiles:
            self._draw_projectile(p)
        # 6. 掉落
        for p in self.engine.drop_sys.pickups:
            self._draw_pickup(p)
        self._render_damage_numbers()
        # 7. 召唤 / 安全区（若有）
        # HUD 之上元素：成就提示 / 警告
        # 覆盖 UI（按钮 / 摇杆）
        self._render_combat_feedback()
        self._render_touch_controls()

    def _sync_combat_feedback(self) -> None:
        dt = max(0.0, min(0.08, self.last_real_dt))
        for event_type in (
            "weapon_synergy_activated", "random_event_started", "challenge_completed",
            "challenge_failed", "boss_phase_changed", "boss_broken", "affix_minion_spawned",
            "weapon_synergy_triggered",
        ):
            for ev in self.engine.event_bus.history(event_type):
                if ev.id in self._seen_visual_events:
                    continue
                self._seen_visual_events.add(ev.id)
                sound_key = event_type
                if event_type == "weapon_synergy_triggered":
                    sound_key = str(ev.payload.get("combo_id", ""))
                self._play_feedback_sound(sound_key)
                # P6：组合技触发 → 加入屏幕特效（移到 for 循环内，避免 ev 未绑定）
                if event_type == "weapon_synergy_triggered":
                    combo_id = str(ev.payload.get("combo_id", ""))
                    self._combo_fx_list.append({
                        "combo_id": combo_id,
                        "age": 0.0,
                        "ttl": 1.2,
                        "player_pos": self.engine.player.position,
                    })
        for ev in self.engine.event_bus.history("player_bomb_triggered"):
            if ev.id in self._seen_visual_events:
                continue
            self._seen_visual_events.add(ev.id)
            pos = tuple(ev.payload.get("position", self.engine.player.position))
            radius = float(ev.payload.get("radius", 150.0))
            self._hit_bursts.append({"pos": pos, "ttl": 0.62, "age": 0.0, "radius": radius, "color": (105, 220, 255), "kind": "thunder"})
            self._floaters.append({
                "pos": pos, "text": "雷爆", "ttl": 0.72, "age": 0.0,
                "color": (180, 245, 255), "vy": -58.0, "xoff": -14.0,
            })
            self._screen_shake = min(0.30, self._screen_shake + 0.10)
        now_ids = set()
        for e in self.engine.spawn_director.enemies:
            now_ids.add(e.entity_id)
            old = self._seen_enemy_hp.get(e.entity_id, e.current_hp)
            if e.current_hp < old - 0.01:
                amount = old - e.current_hp
                self._spawn_hit_feedback(
                    e.position,
                    amount=amount,
                    color=COL_ENEMY_SUPER if e.is_super else (COL_ENEMY_ELITE if e.is_elite else COL_ENEMY),
                    target_id=e.entity_id,
                )
            self._seen_enemy_hp[e.entity_id] = e.current_hp
            self._seen_enemy_pos[e.entity_id] = e.position
        for eid in list(self._seen_enemy_hp):
            if eid not in now_ids:
                pos = self._seen_enemy_pos.get(eid)
                old_hp = self._seen_enemy_hp.get(eid, 1)
                if pos and old_hp > 0:
                    self._hit_bursts.append({"pos": pos, "ttl": 0.45, "age": 0.0, "radius": 48.0, "color": COL_PICKUP_XP, "kind": "defeat"})
                self._seen_enemy_hp.pop(eid, None)
                self._seen_enemy_pos.pop(eid, None)
                self._enemy_hit_flash.pop(eid, None)

        hp = self.engine.player.current_hp
        if hp < self._seen_player_hp - 0.01:
            amount = self._seen_player_hp - hp
            self._spawn_player_damage_feedback(amount)
        self._seen_player_hp = hp

        for eid in list(self._enemy_hit_flash):
            self._enemy_hit_flash[eid] = max(0.0, self._enemy_hit_flash[eid] - dt)
            if self._enemy_hit_flash[eid] <= 0:
                self._enemy_hit_flash.pop(eid, None)
        self._screen_shake = max(0.0, self._screen_shake - dt)

    def _play_feedback_sound(self, sound_key: str) -> None:
        sound = self._feedback_sounds.get(sound_key)
        if sound is not None:
            try:
                sound.play()
            except pygame.error:
                pass

    def _set_music_track(self, track: str | None) -> None:
        """按当前战况切换循环音乐；缺文件或无音频设备时保持静默。"""
        if not self._audio_ready or track == self._music_track:
            return
        path = self.assets_dir / "audio" / "music" / f"{track}.mp3" if track else None
        try:
            if path is None:
                pygame.mixer.music.stop()
                self._music_track = None
            elif path.exists():
                pygame.mixer.music.load(str(path))
                pygame.mixer.music.set_volume(0.30)
                pygame.mixer.music.play(-1, fade_ms=360)
                self._music_track = track
        except pygame.error:
            pass

    def _spawn_hit_feedback(self, pos, *, amount: float, color, target_id: str) -> None:
        self._enemy_hit_flash[target_id] = 0.14
        self._hit_bursts.append({"pos": pos, "ttl": 0.28, "age": 0.0, "radius": 30.0, "color": color, "kind": "hit"})
        self._floaters.append({
            "pos": pos,
            "text": str(int(max(1, round(amount)))),
            "ttl": 0.62,
            "age": 0.0,
            "color": (255, 230, 160) if amount >= 25 else COL_TEXT,
            "vy": -42.0,
            "xoff": ((hash(target_id) % 17) - 8) * 1.8,
        })
        # P8：战斗音效空间化
        sound_key = "crit" if amount >= 25 else "hit"
        snd = self._battle_sound(sound_key)
        if snd["name"] and snd["name"] in self._feedback_sounds:
            try:
                self._feedback_sounds[snd["name"]].set_volume(snd["volume"])
                self._feedback_sounds[snd["name"]].play()
            except pygame.error:
                pass

    def _spawn_player_damage_feedback(self, amount: float) -> None:
        pos = self.engine.player.position
        self._screen_shake = min(0.22, self._screen_shake + 0.08)
        self._hit_bursts.append({"pos": pos, "ttl": 0.34, "age": 0.0, "radius": 42.0, "color": COL_BOMB_DANGER, "kind": "player"})
        self._floaters.append({
            "pos": pos,
            "text": f"-{int(max(1, round(amount)))}",
            "ttl": 0.72,
            "age": 0.0,
            "color": (255, 110, 110),
            "vy": -50.0,
            "xoff": -18.0,
        })

    def _render_combat_feedback(self) -> None:
        dt = max(0.0, min(0.08, self.last_real_dt))
        keep_bursts = []
        for burst in self._hit_bursts:
            burst["age"] += dt
            t = burst["age"] / max(0.001, burst["ttl"])
            if t >= 1.0:
                continue
            x, y = self._world_to_screen(burst["pos"])
            color = burst["color"]
            radius = int((10 + burst["radius"] * t) * self.scale)
            alpha = int(190 * (1.0 - t))
            if burst.get("kind") == "defeat":
                pygame.draw.circle(self.screen, (*color, alpha), (x, y), max(4, radius), width=max(2, int(4 * self.scale)))
                pygame.draw.circle(self.screen, (*COL_ACCENT, alpha // 2), (x, y), max(2, radius // 2), width=1)
            elif burst.get("kind") == "thunder":
                if self._blit_effect(
                    "thunder_explosion", (x, y),
                    (max(48, radius * 2), max(48, radius * 2)),
                    alpha=max(0, min(255, alpha + 45)), key_extra=("burst",),
                ):
                    self._blit_effect(
                        "thunder_residue", (x, y),
                        (max(32, int(radius * 1.55)), max(32, int(radius * 1.55))),
                        alpha=max(0, min(255, alpha)), key_extra=("residue",),
                    )
                    keep_bursts.append(burst)
                    continue
                core = max(5, int(18 * self.scale * (1.0 - t * 0.35)))
                pygame.draw.circle(self.screen, (*COL_HUD_BORDER, alpha), (x, y), max(4, radius), width=max(3, int(7 * self.scale)))
                pygame.draw.circle(self.screen, (*color, alpha), (x, y), max(4, radius), width=max(2, int(4 * self.scale)))
                pygame.draw.circle(self.screen, (*T.TEXT_PRIMARY, min(230, alpha + 35)), (x, y), core)
                for i in range(10):
                    a = self.engine.timer.run_time * 10 + i * math.tau / 10
                    inner = radius * (0.20 + 0.45 * t)
                    outer = radius * (0.78 + 0.18 * math.sin(i + t * 8))
                    p1 = (x + int(math.cos(a) * inner), y + int(math.sin(a) * inner))
                    p2 = (x + int(math.cos(a + 0.16) * outer), y + int(math.sin(a + 0.16) * outer))
                    pygame.draw.line(self.screen, (*color, alpha), p1, p2, max(1, int(3 * self.scale)))
            else:
                pygame.draw.circle(self.screen, (*color, alpha), (x, y), max(3, radius), width=max(2, int(3 * self.scale)))
                pygame.draw.line(self.screen, (*color, alpha), (x - radius, y), (x + radius, y), 1)
                pygame.draw.line(self.screen, (*color, alpha), (x, y - radius), (x, y + radius), 1)
            keep_bursts.append(burst)
        self._hit_bursts = keep_bursts

        keep_floaters = []
        for floater in self._floaters:
            floater["age"] += dt
            t = floater["age"] / max(0.001, floater["ttl"])
            if t >= 1.0:
                continue
            wx = floater["pos"][0] + floater.get("xoff", 0.0)
            wy = floater["pos"][1] + floater.get("vy", -40.0) * floater["age"]
            x, y = self._world_to_screen((wx, wy))
            alpha = int(255 * (1.0 - max(0.0, t - 0.35) / 0.65))
            color = floater["color"]
            img = self.font_small.render(floater["text"], True, color)
            shadow = self.font_small.render(floater["text"], True, (0, 0, 0))
            shadow.set_alpha(alpha)
            img.set_alpha(alpha)
            self.screen.blit(shadow, (x + 1, y + 1))
            self.screen.blit(img, (x, y))
            keep_floaters.append(floater)
        self._floaters = keep_floaters

        # ---- P6：组合技屏幕特效（每帧绘制 flash + 6 角星） ---------------
        keep_combo = []
        for cefx in self._combo_fx_list:
            cefx["age"] += dt
            if cefx["age"] >= cefx["ttl"]:
                continue
            keep_combo.append(cefx)
            fx = self._combo_fx(cefx["combo_id"], cefx["age"], cefx["ttl"])
            # 屏幕闪
            flash = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
            flash.fill((*fx["color"][:3], fx["alpha"] // 4))
            self.screen.blit(flash, (0, 0))
            # 玩家脚下 6 角星
            px, py = self._world_to_screen(cefx["player_pos"])
            r = fx["hex_radius"]
            points = []
            for i in range(6):
                a = math.tau * i / 6 - math.pi / 2 + cefx["age"] * 2.5
                points.append((px + int(math.cos(a) * r), py + int(math.sin(a) * r)))
                a2 = a + math.tau / 12
                points.append((px + int(math.cos(a2) * r * 0.6), py + int(math.sin(a2) * r * 0.6)))
            if len(points) >= 3:
                sc = (*fx["color"][:3], fx["alpha"])
                pygame.draw.polygon(self.screen, sc, points, width=max(2, int(3 * self.scale)))
        self._combo_fx_list = keep_combo

    def _render_background(self) -> None:
        bg = self._background_surface()
        if bg is not None:
            self.screen.blit(bg, self.world_rect.topleft)
        else:
            pygame.draw.rect(self.screen, T.BG_DARK, self.world_rect)
            cx, cy = self.world_rect.center
            for r, alpha in ((520, 32), (360, 42), (220, 52)):
                glow = make_glow(int(r * self.scale), T.ACCENT, alpha)
                self.screen.blit(glow, glow.get_rect(center=(cx, cy)))
            step = max(48, int(96 * self.scale))
            for x in range(self.world_rect.x, self.world_rect.right, step):
                pygame.draw.line(self.screen, T.BG_PANEL_ALT, (x, self.world_rect.y), (x, self.world_rect.bottom), 1)
            for y in range(self.world_rect.y, self.world_rect.bottom, step):
                pygame.draw.line(self.screen, T.BG_PANEL_ALT, (self.world_rect.x, y), (self.world_rect.right, y), 1)
            pygame.draw.circle(self.screen, (27, 58, 82), (cx, cy), int(300 * self.scale), width=2)
            pygame.draw.circle(self.screen, (18, 40, 64), (cx, cy), int(150 * self.scale), width=1)
        stage = self.engine.context.stage_index if self.engine.context.mode != "endless" else 5
        stage_tints = {
            1: (20, 70, 105, 42),
            2: (145, 48, 20, 58),
            3: (105, 25, 145, 66),
            4: (20, 120, 78, 62),
            5: (120, 35, 180, 64),
        }
        tint_key = ("stage_tint", stage, self.world_rect.w, self.world_rect.h)
        tint = self._scene_overlay_cache.get(tint_key)
        if tint is None:
            tint = pygame.Surface((self.world_rect.w, self.world_rect.h), pygame.SRCALPHA)
            tint.fill(stage_tints.get(stage, stage_tints[1]))
            self._scene_overlay_cache[tint_key] = tint
        self.screen.blit(tint, self.world_rect.topleft)
        # 静态场景装饰：只在边缘出现，提供场景辨识度且不遮挡战斗中心。
        prop_layout = (
            ("rock", 0.08, 0.18, 82), ("crate", 0.90, 0.24, 92),
            ("pipe", 0.12, 0.78, 104), ("antenna", 0.86, 0.75, 108),
            ("pillar", 0.52, 0.10, 96),
        )
        for prop_id, px, py, size in prop_layout:
            prop = self._scaled_art(self.prop_sources.get(prop_id), ("prop", prop_id), (int(size * self.scale), int(size * self.scale)))
            if prop is not None:
                prop.set_alpha(155)
                self.screen.blit(prop, prop.get_rect(center=(self.world_rect.x + int(self.world_rect.w * px), self.world_rect.y + int(self.world_rect.h * py))))
        # 每关增加不同的动态图层，让换关不仅是 HUD 数字变化。
        cx, cy = self.world_rect.center
        if stage == 2:
            for i in range(14):
                a = self.engine.timer.run_time * 0.18 + i * math.tau / 14
                rr = int((260 + (i % 4) * 75) * self.scale)
                px, py = cx + int(math.cos(a) * rr), cy + int(math.sin(a) * rr)
                pygame.draw.circle(self.screen, (255, 105, 55), (px, py), max(2, int(4 * self.scale)))
        elif stage == 3:
            for i in range(4):
                rr = int((170 + i * 105 + math.sin(self.engine.timer.run_time * 1.8 + i) * 18) * self.scale)
                pygame.draw.circle(self.screen, (155, 70, 220), (cx, cy), rr, width=max(1, int(2 * self.scale)))
        elif stage == 4:
            step = max(55, int(110 * self.scale))
            offset = int(self.engine.timer.run_time * 22) % step
            for x in range(self.world_rect.x - step + offset, self.world_rect.right, step):
                pygame.draw.line(self.screen, (55, 185, 125), (x, self.world_rect.y), (x, self.world_rect.bottom), 1)
        # 半透遮罩（让贴图更突出）
        veil_key = ("world_veil", self.world_rect.w, self.world_rect.h)
        veil = self._scene_overlay_cache.get(veil_key)
        if veil is None:
            veil = pygame.Surface((self.world_rect.w, self.world_rect.h), pygame.SRCALPHA)
            veil.fill((4, 8, 16, 105))
            self._scene_overlay_cache[veil_key] = veil
        self.screen.blit(veil, self.world_rect.topleft)
        # 世界边界：粗黑描边
        pygame.draw.rect(self.screen, COL_HUD_BORDER, self.world_rect, width=3)
        # 出生圈（2 秒内）
        if self.engine.timer.stage_time < 2.0:
            cx, cy = self._world_to_screen((960, 540))
            pygame.draw.circle(self.screen, (*T.ACCENT, 100), (cx, cy), int(220 * self.scale), width=3)
            pygame.draw.circle(self.screen, (*T.ACCENT, 40), (cx, cy), int(260 * self.scale), width=2)

    def _draw_player(self) -> None:
        x, y = self._world_to_screen(self.engine.player.position)
        r = int(26 * self.scale)
        attack_age = self.engine.timer.run_time - self.engine.last_player_attack_time
        attacking = 0 <= attack_age <= (0.24 if self.engine.last_player_attack_is_melee else 0.13)
        # 近战先显示非指向性的锁定扇区/圆形范围，再画挥砍亮边。
        if attacking and self.engine.last_player_attack_is_melee:
            range_px = int(self.engine.last_player_attack_range * self.scale)
            arc_deg = self.engine.last_player_attack_arc
            overlay = pygame.Surface((range_px * 2 + 12, range_px * 2 + 12), pygame.SRCALPHA)
            center = range_px + 6
            if arc_deg >= 359:
                pygame.draw.circle(overlay, (*T.ACCENT_3, 34), (center, center), range_px)
                pygame.draw.circle(overlay, (*T.ACCENT_3, 190), (center, center), range_px, width=max(2, int(3 * self.scale)))
            else:
                points = [(center, center)]
                start = self.engine.last_player_attack_angle - math.radians(arc_deg * 0.5)
                for i in range(19):
                    a = start + math.radians(arc_deg) * i / 18
                    points.append((center + int(math.cos(a) * range_px), center + int(math.sin(a) * range_px)))
                pygame.draw.polygon(overlay, (*T.ACCENT_3, 38), points)
                pygame.draw.lines(overlay, (*T.ACCENT_3, 205), False, points[1:], max(2, int(4 * self.scale)))
            self.screen.blit(overlay, overlay.get_rect(center=(x, y)))
            # 刀光直接按与命中判定相同的世界角度采样，避免图片自身朝向造成视觉偏移。
            progress = min(1.0, attack_age / 0.24)
            heavy = self.engine.last_player_attack_weapon == "w_great_cleaver"
            draw_facing_arc(
                self.screen, (x, y), angle=self.engine.last_player_attack_angle,
                arc_deg=arc_deg * (0.86 if heavy else 0.72),
                radius=int(range_px * (0.70 + progress * 0.16)),
                color=T.ACCENT_3 if heavy else T.ACCENT, width=max(3, int((8 if heavy else 5) * self.scale)),
            )
        if getattr(self.engine, "roll_left", 0.0) > 0 and self.engine.roll_start_pos and self.engine.roll_target_pos:
            sx, sy = self._world_to_screen(self.engine.roll_start_pos)
            tx, ty = self._world_to_screen(self.engine.roll_target_pos)
            progress = 1.0 - self.engine.roll_left / max(0.001, self.engine.roll_duration)
            trail_len = max(36, int(math.hypot(tx - sx, ty - sy)))
            angle = -math.degrees(math.atan2(ty - sy, tx - sx))
            trail_center = ((sx + tx) // 2, (sy + ty) // 2)
            drew_trail = self._blit_effect(
                "roll_trail", trail_center,
                (trail_len, max(34, int(86 * self.scale))),
                angle=angle, alpha=170, key_extra=("active",),
            )
            if not drew_trail:
                pygame.draw.line(self.screen, COL_HUD_BORDER, (sx, sy), (tx, ty), max(7, int(12 * self.scale)))
                pygame.draw.line(self.screen, (100, 235, 255), (sx, sy), (tx, ty), max(3, int(6 * self.scale)))
            for i in range(4):
                t = max(0.0, progress - i * 0.12)
                gx = sx + int((tx - sx) * t)
                gy = sy + int((ty - sy) * t)
                ghost_r = max(10, int((23 - i * 3) * self.scale))
                alpha = max(35, int(120 * (1.0 - i / 4) * (1.0 - progress * 0.3)))
                drew_ghost = self._blit_effect(
                    "roll_afterimage", (gx, gy),
                    (max(26, ghost_r * 3), max(26, ghost_r * 3)),
                    angle=-math.degrees(self.engine.player.facing) - 90.0,
                    alpha=alpha, key_extra=("ghost", i),
                )
                if not drew_ghost:
                    pygame.draw.circle(self.screen, (95, 220, 255, alpha), (gx, gy), ghost_r, width=max(2, int(3 * self.scale)))
        landing_age = self.engine.timer.run_time - getattr(self.engine, "last_roll_finished_at", -99.0)
        if 0 <= landing_age <= 0.26 and self.engine.last_roll_finished_pos:
            lx, ly = self._world_to_screen(self.engine.last_roll_finished_pos)
            t = landing_age / 0.26
            rr = int((18 + 58 * t) * self.scale)
            alpha = int(180 * (1.0 - t))
            drew_landing = self._blit_effect(
                "roll_landing", (lx, ly), (rr * 2, rr * 2),
                alpha=alpha, key_extra=("landing",),
            )
            self._blit_effect(
                "roll_spark", (lx, ly), (max(24, rr), max(24, rr)),
                alpha=max(0, min(255, alpha + 45)), key_extra=("spark",),
            )
            if not drew_landing:
                pygame.draw.circle(self.screen, (*COL_HUD_BORDER, alpha), (lx, ly), rr, width=max(3, int(6 * self.scale)))
                pygame.draw.circle(self.screen, (120, 235, 255, alpha), (lx, ly), rr, width=max(2, int(3 * self.scale)))
        # 1. 底层辉光
        glow = make_glow(max(14, r * 3), COL_PLAYER, 78)
        self.screen.blit(glow, glow.get_rect(center=(x, y)))
        # 2. 角色贴图（元气骑士风骑士，带朝向旋转）
        sprite_size = int(T.SPRITE_BASE_PX * self.scale)
        prev = getattr(self, "_last_player_draw_pos", self.engine.player.position)
        moved = math.hypot(self.engine.player.position[0] - prev[0], self.engine.player.position[1] - prev[1]) > 0.1
        self._last_player_draw_pos = self.engine.player.position
        anim_rate = 14.0 if moved else 5.5
        frame_index = int(self.engine.timer.run_time * anim_rate) % 4
        if attacking:
            frame_index = int(attack_age / (0.24 if self.engine.last_player_attack_is_melee else 0.13) * 4)
        sprite = self._player_sprite(sprite_size, frame_index, attacking=attacking)
        if sprite is not None:
            # 朝向：玩家 facing 字段（弧度，0=+x）；pygame 的 rotate 是逆时针°，需要 -90 偏置
            deg = -math.degrees(self.engine.player.facing) - 90.0
            bob = int(math.sin(self.engine.timer.run_time * anim_rate) * (3 if moved else 1.5) * self.scale)
            sway = math.sin(self.engine.timer.run_time * anim_rate * 0.5) * (3.0 if moved else 0.8)
            deg += sway
            if attacking and self.engine.last_player_attack_is_melee:
                progress = min(1.0, attack_age / 0.24)
                deg += 28.0 - 56.0 * progress
            recoil = 0
            if attacking and not self.engine.last_player_attack_is_melee:
                recoil = int((1.0 - attack_age / 0.13) * 9 * self.scale)
            rotated = pygame.transform.rotate(sprite, deg)
            stage = self.engine.context.stage_index
            if stage == 2:
                rotated.fill((28, 8, 0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            elif stage >= 3:
                rotated.fill((18, 0, 32, 0), special_flags=pygame.BLEND_RGBA_ADD)
            rect = rotated.get_rect(center=(x, y + bob))
            if recoil:
                rect.x -= int(math.cos(self.engine.last_player_attack_angle) * recoil)
                rect.y -= int(math.sin(self.engine.last_player_attack_angle) * recoil)
            self.screen.blit(rotated, rect)
        else:
            # fallback：圆 + 核（保留旧几何，黑色描边版）
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), r + 2)
            pygame.draw.circle(self.screen, COL_PLAYER_TRIM, (x, y), r)
            pygame.draw.circle(self.screen, COL_PLAYER, (x, y), r - 3)
            pygame.draw.circle(self.screen, COL_PLAYER_CORE, (x, y), max(3, int(r * 0.42)))
        # 熔核无人机：使用真实武器图标作为场上伴随单位，而不是只在 HUD 槽位显示。
        if self.engine.weapon_sys.active and self.engine.weapon_sys.active.weapon_id == "w_ember_drone":
            orbit_r = int(82 * self.scale)
            orbit_a = self.engine.timer.run_time * 2.8
            dx = x + int(math.cos(orbit_a) * orbit_r)
            dy = y + int(math.sin(orbit_a) * orbit_r)
            pygame.draw.line(self.screen, (*T.ACCENT_3, 72), (x, y), (dx, dy), max(1, int(2 * self.scale)))
            drone = self._scaled_art(self.weapon_icon_sources.get("w_ember_drone"), ("weapon", "w_ember_drone", "field"), (max(24, int(42 * self.scale)), max(24, int(42 * self.scale))))
            if drone is not None:
                self.screen.blit(drone, drone.get_rect(center=(dx, dy)))
            else:
                pygame.draw.circle(self.screen, COL_HUD_BORDER, (dx, dy), max(9, int(15 * self.scale)))
                pygame.draw.circle(self.screen, T.ACCENT_3, (dx, dy), max(7, int(12 * self.scale)))
        # 3. 护盾圈 / 无敌圈
        if self.engine.player.current_shield > 0:
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), r + 6, width=2)
            pygame.draw.circle(self.screen, COL_SHIELD, (x, y), r + 5, width=2)
        if self.engine.player.invuln_left > 0:
            pulse = 0.5 + 0.5 * math.sin(self.engine.timer.run_time * 22)
            pygame.draw.circle(self.screen, (*COL_PLAYER_CORE, int(160 + 80 * pulse)), (x, y), r + 8, width=2)
        if attacking:
            a = self.engine.last_player_attack_angle
            if self.engine.last_player_attack_is_melee:
                heavy_cleaver = self.engine.last_player_attack_weapon == "w_great_cleaver"
                blade_len = int(min(165 if heavy_cleaver else 95, self.engine.last_player_attack_range * 0.72) * self.scale)
                swing = math.radians(32 - 64 * min(1.0, attack_age / 0.24))
                a += swing
                tip = (x + int(math.cos(a) * blade_len), y + int(math.sin(a) * blade_len))
                outer = 18 if heavy_cleaver else 9
                inner = 11 if heavy_cleaver else 5
                pygame.draw.line(self.screen, COL_HUD_BORDER, (x, y), tip, max(5, int(outer * self.scale)))
                pygame.draw.line(self.screen, T.ACCENT_3 if heavy_cleaver else T.TEXT_PRIMARY, (x, y), tip, max(3, int(inner * self.scale)))
            else:
                muzzle = (x + int(math.cos(a) * 36 * self.scale), y + int(math.sin(a) * 36 * self.scale))
                pygame.draw.circle(self.screen, T.TEXT_PRIMARY, muzzle, max(3, int(7 * self.scale)))
                pygame.draw.circle(self.screen, T.ACCENT, muzzle, max(2, int(4 * self.scale)))
        # 4. HP 条（统一放到头顶）
        self._draw_hp_bar(x, y - r - 14, w=int(96 * self.scale), h=int(10 * self.scale))

    def _draw_hp_bar(self, x, y, *, w=120, h=8):
        eff = self.engine.player
        maxhp = self.engine.player.base_max_hp * (1.0 + self.engine.player.extra_max_hp_pct + self.engine.player.growth.max_hp_pct_bonus)
        ratio = eff.current_hp / max(1.0, maxhp)
        ratio = max(0.0, min(1.0, ratio))
        back = pygame.Rect(x - w // 2, y, w, h)
        # 元气骑士风 HP 条：3px 黑色描边 + 高饱和红色
        pygame.draw.rect(self.screen, COL_HUD_BORDER, back.inflate(4, 2), border_radius=5)
        pygame.draw.rect(self.screen, COL_HP_BACK, back, border_radius=4)
        pygame.draw.rect(self.screen, COL_HP, (back.x, back.y, int(w * ratio), h), border_radius=4)
        # 护盾条
        if eff.current_shield > 0 or eff.growth.max_shield_extra > 0 or eff.max_shield > 0:
            maxshield = eff.max_shield + eff.growth.max_shield_extra
            if maxshield > 0:
                sr = eff.current_shield / maxshield
                shield_rect = pygame.Rect(back.x, y - 4, w, 4)
                pygame.draw.rect(self.screen, COL_HUD_BORDER, shield_rect.inflate(4, 0), border_radius=3)
                pygame.draw.rect(self.screen, T.SHIELD_FILL, (back.x, y - 4, int(w * sr), 4), border_radius=2)

    def _draw_enemy(self, e) -> None:
        x, y = self._world_to_screen(e.position)
        r = int(e.collision_radius * self.scale)
        if e.is_super:
            color = COL_ENEMY_SUPER
            wr = r + 14
        elif e.is_elite:
            color = COL_ENEMY_ELITE
            wr = r + 2
        else:
            color = COL_ENEMY
            wr = r
        # 1. 底层辉光
        glow = make_glow(max(10, wr * 2), color, 58 if not e.is_super else 100)
        self.screen.blit(glow, glow.get_rect(center=(x, y)))
        if e.is_super:
            se = self.engine.super_director.active
            if se is not None and se.enemy is e and se.enraged:
                aura = self._scaled_art(self.effect_sources.get("boss_enrage"), ("boss_enrage",), (wr * 5, wr * 5))
                if aura is not None:
                    self.screen.blit(aura, aura.get_rect(center=(x, y)))
        # 2. 决定贴图
        sprite = None
        if e.is_super:
            # BOSS 要在第一眼就与普通怪拉开体量差，视觉尺寸远大于碰撞体。
            se = self.engine.super_director.active
            boss_frame = int(self.engine.timer.run_time * 6) % 4
            sprite = self._super_sprite(
                int(max(280 * self.scale, wr * 5.8)), boss_frame,
                enraged=bool(se is not None and se.enemy is e and se.enraged),
            )
        else:
            # 兵种使用不同显示体量，保留各自轮廓，不再缩成近似的小圆点。
            base_size = {
                "wingblade_sprinter": 66, "spinner_chaser": 72,
                "lantern_shooter": 82, "multinode_spreader": 88,
                "shellguard_heavy": 96, "minelayer_bomber": 86,
                "crystal_sniper": 104, "mine_leech": 78, "rail_turret": 112,
            }.get(e.config_id, 74)
            enemy_frame = int(self.engine.timer.run_time * (11 if e.state.value == "seeking" else 7)) % 4
            if e.state.value in ("windup", "attacking"):
                enemy_frame += 4
            sprite = self._enemy_sprite(e.config_id, int(max(base_size * self.scale, wr * 2.9)),
                                       enemy_frame, time_form=e.time_form,
                                       damage_level=2 if (e.max_hp > 0 and e.current_hp / e.max_hp < 0.2) else 1 if (e.max_hp > 0 and e.current_hp / e.max_hp < 0.5) else 0)
        # 3. 绘制贴图（旋转朝向）
        if sprite is not None:
            # 敌人的 facing 本来就是角度；旧代码再次 degrees() 导致旋转乱跳。
            deg = -e.facing - 90.0
            rotated = pygame.transform.rotate(sprite, deg)
            if e.state.value == "dying":
                rotated.set_alpha(max(0, min(255, int(255 * e.state_left / 0.24))))
            rect = rotated.get_rect(center=(x, y))
            self.screen.blit(rotated, rect)
            if e.is_super:
                pygame.draw.circle(
                    self.screen, (*COL_ENEMY_SUPER, 115), (x, y),
                    int(wr * 1.55), width=max(2, int(4 * self.scale)),
                )
        elif e.is_super:
            # 8 角星 fallback
            points = []
            for i in range(8):
                a = math.pi / 4 * i + self.engine.timer.run_time * 0.65
                rr = wr if i % 2 == 0 else max(6, int(wr * 0.62))
                points.append((x + int(math.cos(a) * rr), y + int(math.sin(a) * rr)))
            pygame.draw.polygon(self.screen, COL_HUD_BORDER, points)
            pygame.draw.polygon(self.screen, color, [p for p in points])
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), max(4, wr // 3) + 2)
            pygame.draw.circle(self.screen, color, (x, y), max(4, wr // 3))
        elif e.is_elite:
            # 菱形 fallback
            points = [(x, y - wr), (x + wr, y), (x, y + wr), (x - wr, y)]
            pygame.draw.polygon(self.screen, COL_HUD_BORDER, points)
            pygame.draw.polygon(self.screen, color, points)
        else:
            # 圆 fallback
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), wr + 2)
            pygame.draw.circle(self.screen, color, (x, y), wr)
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), max(3, wr // 3) + 1)
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), max(3, wr // 3))
        # 4. 命中闪白
        if self._enemy_hit_flash.get(e.entity_id, 0) > 0:
            white = pygame.Surface((wr * 4 + 4, wr * 4 + 4), pygame.SRCALPHA)
            pygame.draw.circle(white, (*T.TEXT_PRIMARY, 110), (wr * 2 + 2, wr * 2 + 2), wr + 4)
            self.screen.blit(white, white.get_rect(center=(x, y)))
        # 5. 出生提示环
        if e.state.value == "spawning":
            pulse = 0.5 + 0.5 * math.sin(self.engine.timer.run_time * 14)
            pygame.draw.circle(self.screen, (*T.ENEMY_SPAWN_RING, int(140 + pulse * 90)), (x, y), wr + int(10 * self.scale), width=2)
        if e.state.value == "windup" and e.projectile_speed > 0:
            facing = math.radians(e.facing)
            length = int(min(260, e.attack_range * 0.45) * self.scale)
            ray_angles = (-24, -8, 8, 24) if e.config_id == "multinode_spreader" else (0,)
            warning_color = T.ACCENT_2 if e.config_id == "crystal_sniper" else T.PROJ_ENEMY
            for offset in ray_angles:
                a = facing + math.radians(offset)
                tip = (x + int(math.cos(a) * length), y + int(math.sin(a) * length))
                pygame.draw.line(self.screen, COL_HUD_BORDER, (x, y), tip, max(4, int(6 * self.scale)))
                pygame.draw.line(self.screen, warning_color, (x, y), tip, max(2, int(3 * self.scale)))
            charge_r = max(7, int((12 + 4 * math.sin(self.engine.timer.run_time * 22)) * self.scale))
            pygame.draw.circle(self.screen, warning_color, (x, y), charge_r, width=max(2, int(3 * self.scale)))

        # 小兵出手反馈：枪口爆闪、狙击残光、散射火花、重兵震地或近战挥砍。
        attack_age = self.engine.timer.run_time - e.last_attack_time
        if 0 <= attack_age <= 0.24:
            facing = math.radians(e.facing)
            fade = max(0.0, 1.0 - attack_age / 0.24)
            fx_color = {
                "lantern_shooter": (255, 220, 80),
                "multinode_spreader": (255, 70, 210),
                "crystal_sniper": (80, 245, 255),
                "shellguard_heavy": (255, 155, 65),
            }.get(e.config_id, T.DANGER)
            if e.projectile_speed > 0:
                muzzle_dist = int(wr + 18 * self.scale)
                muzzle = (x + int(math.cos(facing) * muzzle_dist), y + int(math.sin(facing) * muzzle_dist))
                flash_r = max(5, int((16 + 15 * fade) * self.scale))
                pygame.draw.circle(self.screen, fx_color, muzzle, flash_r, width=max(2, int(5 * self.scale)))
                if e.config_id == "crystal_sniper":
                    beam_len = int(210 * self.scale * fade)
                    tip = (muzzle[0] + int(math.cos(facing) * beam_len), muzzle[1] + int(math.sin(facing) * beam_len))
                    pygame.draw.line(self.screen, fx_color, muzzle, tip, max(2, int(5 * self.scale)))
                elif e.config_id == "multinode_spreader":
                    for off in (-28, -10, 10, 28):
                        a = facing + math.radians(off)
                        tip = (muzzle[0] + int(math.cos(a) * 42 * self.scale), muzzle[1] + int(math.sin(a) * 42 * self.scale))
                        pygame.draw.line(self.screen, fx_color, muzzle, tip, max(2, int(3 * self.scale)))
            elif e.config_id == "shellguard_heavy":
                pygame.draw.circle(self.screen, fx_color, (x, y), int(wr + 42 * (1 - fade)), width=max(2, int(5 * self.scale)))
            elif not e.drops_bomb:
                arc_r = max(wr + 8, int(72 * self.scale))
                rect = pygame.Rect(x - arc_r, y - arc_r, arc_r * 2, arc_r * 2)
                pygame.draw.arc(self.screen, fx_color, rect, -facing - 0.8, -facing + 0.8, max(3, int(7 * self.scale)))
        if e.is_super and self.engine.super_director.active is not None:
            se = self.engine.super_director.active
            if se.enemy is e and se.current_skill is not None and se.skill_windup_left > 0:
                pulse = 0.45 + 0.55 * math.sin(self.engine.timer.run_time * 18) ** 2
                telegraph = int((95 + 45 * pulse) * self.scale)
                warning = self._scaled_art(self.boss_ui_sources.get("warning_circle"), ("boss_ui", "warning_circle"), (telegraph * 2, telegraph * 2))
                if warning is not None:
                    warning.set_alpha(190)
                    self.screen.blit(warning, warning.get_rect(center=(x, y)))
                else:
                    pygame.draw.circle(self.screen, (*T.DANGER, 190), (x, y), telegraph, width=max(3, int(6 * self.scale)))
                edge_warning = self._scaled_art(self.boss_ui_sources.get("edge_warning"), ("boss_ui", "edge_warning"), self.world_rect.size)
                if edge_warning is not None:
                    edge_warning.set_alpha(90)
                    self.screen.blit(edge_warning, self.world_rect.topleft)
                if se.current_skill == SuperSkill.LOCKED_DASH:
                    px, py = self._world_to_screen(self.engine.player.position)
                    pygame.draw.line(self.screen, COL_HUD_BORDER, (x, y), (px, py), max(8, int(13 * self.scale)))
                    pygame.draw.line(self.screen, T.DANGER, (x, y), (px, py), max(4, int(7 * self.scale)))
            elif se.enemy is e and se.current_skill == SuperSkill.LOCKED_DASH and se.skill_active_left > 0:
                dash = self._scaled_art(self.effect_sources.get("boss_dash"), ("boss_dash",), (wr * 6, wr * 3))
                if dash is not None:
                    angle = -math.degrees(math.atan2(se.dash_direction[1], se.dash_direction[0]))
                    dash = pygame.transform.rotate(dash, angle)
                    self.screen.blit(dash, dash.get_rect(center=(x, y)))
        # 6. T1–T3 视觉档（在贴图外侧加环）
        if e.time_form == "T1":
            pygame.draw.circle(self.screen, color, (x, y), wr + 4, width=1)
        elif e.time_form == "T2":
            pygame.draw.circle(self.screen, color, (x, y), wr + 4, width=1)
            pygame.draw.circle(self.screen, color, (x, y), wr + 8, width=1)
        elif e.time_form == "T3":
            pygame.draw.circle(self.screen, color, (x, y), wr + 4, width=2)
            pygame.draw.circle(self.screen, color, (x, y), wr + 10, width=2)
            pygame.draw.circle(self.screen, color, (x, y), wr + 16, width=1)
        if getattr(e, "elite_affixes", ()):
            for i, affix in enumerate(list(e.elite_affixes)[:3]):
                cfg = ENEMY_AFFIXES.get(affix, {"name": affix, "color": "#ffffff"})
                # 子报告 P0-4：原坐标 y - wr - 38 与 HP 条 y - wr - 14 紧贴，icon fallback 还会盖到 HP。
                # 把 chip 整体上移 12px，HP 条保留原位。
                chip = pygame.Rect(x - 34 + i * 30, y - wr - 50, 28, 24)
                col = pygame.Color(cfg.get("color", "#ffffff"))
                pygame.draw.rect(self.screen, COL_HUD_BORDER, chip, border_radius=6)
                pygame.draw.rect(self.screen, col, chip.inflate(-3, -3), border_radius=4)
                icon = self._scaled_art(self.affix_icon_sources.get(affix), ("affix", affix), (20, 20))
                if icon is not None:
                    self.screen.blit(icon, icon.get_rect(center=chip.center))
                else:
                    draw_text_center(self.screen, cfg.get("name", "?")[:1], chip, color=T.TEXT_DARK, font=self.font_small, outline=1)
        if e.is_super and self.engine.super_director.active is not None and self.engine.super_director.active.enemy is e:
            se = self.engine.super_director.active
            draw_text_center(self.screen, f"阶段 {se.phase}", pygame.Rect(x - 44, y - wr - 64, 88, 22), color=T.DANGER if se.phase >= 3 else T.CARD_GOLD, font=self.font_small, outline=2)
            gauge_w = max(80, int(wr * 2.2))
            gauge = pygame.Rect(x - gauge_w // 2, y + wr + 14, gauge_w, 7)
            gauge_art = self._scaled_art(self.boss_ui_sources.get("break_gauge"), ("boss_ui", "break_gauge"), (gauge_w + 8, 15))
            if gauge_art is not None:
                self.screen.blit(gauge_art, gauge_art.get_rect(center=gauge.center))
            else:
                pygame.draw.rect(self.screen, COL_HUD_BORDER, gauge.inflate(4, 2), border_radius=4)
                pygame.draw.rect(self.screen, T.BG_PANEL_ALT, gauge, border_radius=3)
            ratio = 1.0 if se.broken_left > 0 else max(0.0, min(1.0, se.break_gauge / max(1.0, se.break_gauge_max)))
            pygame.draw.rect(self.screen, T.ACCENT_3 if se.broken_left > 0 else T.ACCENT, (gauge.x, gauge.y, int(gauge.w * ratio), gauge.h), border_radius=3)
            weak_x = x + int(math.cos(se.weakpoint_angle) * (wr + 18))
            weak_y = y + int(math.sin(se.weakpoint_angle) * (wr + 18))
            weakpoint = self._scaled_art(self.boss_ui_sources.get("weakpoint"), ("boss_ui", "weakpoint"), (max(18, int(28 * self.scale)), max(18, int(28 * self.scale))))
            if weakpoint is not None:
                self.screen.blit(weakpoint, weakpoint.get_rect(center=(weak_x, weak_y)))
            else:
                pygame.draw.circle(self.screen, COL_HUD_BORDER, (weak_x, weak_y), max(7, int(11 * self.scale)))
                pygame.draw.circle(self.screen, T.CARD_GOLD, (weak_x, weak_y), max(5, int(8 * self.scale)))
        # 7. 血条（仅受伤时显示）
        if e.current_hp < e.max_hp - 0.5 or e.is_elite or e.is_super:
            self._draw_enemy_hp(e, x - wr, y - wr - 14, width=max(wr * 2, int(40 * self.scale)), height=int(6 * self.scale))

    def _draw_enemy_hp(self, e, x, y, width, height):
        ratio = e.current_hp / max(1.0, e.max_hp)
        c = COL_ENEMY_SUPER if e.is_super else (COL_ENEMY_ELITE if e.is_elite else COL_ENEMY)
        # 血条：黑色描边 + 高饱和填充（元气骑士风）
        rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, rect.inflate(4, 2), border_radius=4)
        pygame.draw.rect(self.screen, COL_HP_BACK, rect, border_radius=3)
        pygame.draw.rect(self.screen, c, (x, y, int(width * max(0.0, min(1.0, ratio))), height), border_radius=3)
        # 不在怪物头顶显示名字或类型；精英/BOSS 由颜色、尺寸和外圈区分。

    def _draw_projectile(self, p) -> None:
        x, y = self._world_to_screen(p.position)
        r = max(2, int(p.radius * self.scale))
        color = ((80, 245, 255) if p.visual_kind == "ricochet" else T.PROJ_PLAYER) if p.faction == "player" else {
            "enemy_arcane": (255, 215, 70),
            "enemy_shard": (255, 70, 215),
            "enemy_rail": (75, 245, 255),
            "boss_orb": (255, 125, 45),
        }.get(p.visual_kind, T.PROJ_ENEMY)
        speed = math.hypot(p.velocity[0], p.velocity[1])
        glow = make_glow(max(8, r * 5), color, 88)
        self.screen.blit(glow, glow.get_rect(center=(x, y)))
        if speed >= 1:
            effect_id = {
                "ricochet": "ricochet", "enemy_arcane": "enemy_arcane",
                "enemy_shard": "enemy_shard", "enemy_rail": "enemy_rail",
                "boss_orb": "boss_orb", "laser": "laser",
            }.get(p.visual_kind)
            if effect_id is not None:
                if effect_id == "laser":
                    art_size = (max(36, r * 9), max(12, r * 3))
                elif effect_id == "enemy_rail":
                    art_size = (max(24, r * 7), max(12, r * 3))
                else:
                    art_size = (max(10, r * 4), max(10, r * 4))
                art = self._scaled_art(self.effect_sources.get(effect_id), (effect_id,), art_size)
                if art is not None:
                    angle = -math.degrees(math.atan2(p.velocity[1], p.velocity[0])) - 90.0
                    art = pygame.transform.rotate(art, angle)
                    self.screen.blit(art, art.get_rect(center=(x, y)))
        if p.is_melee or speed < 1:
            arc_r = max(18, int((p.splash_radius or p.radius * 4) * self.scale))
            if p.attack_arc_deg >= 359:
                pygame.draw.circle(self.screen, color, (x, y), arc_r, width=max(2, int(4 * self.scale)))
            else:
                draw_facing_arc(
                    self.screen, (x, y), angle=p.attack_angle, arc_deg=p.attack_arc_deg,
                    radius=arc_r, color=COL_HUD_BORDER, width=max(5, int(8 * self.scale)),
                )
                draw_facing_arc(
                    self.screen, (x, y), angle=p.attack_angle, arc_deg=p.attack_arc_deg,
                    radius=arc_r, color=color, width=max(3, int(5 * self.scale)),
                )
        else:
            ux, uy = p.velocity[0] / speed, p.velocity[1] / speed
            tail = max(14, int((26 + min(60, speed * 0.04)) * self.scale))
            # 弹尾（描黑）
            tail_end = (x - int(ux * tail), y - int(uy * tail))
            thickness = max(3, r + 1)
            if p.visual_kind == "laser":
                thickness = max(thickness, r * 2 + 3)
            elif p.visual_kind == "enemy_rail":
                thickness = max(thickness, r * 2 + 2)
            pygame.draw.line(self.screen, COL_HUD_BORDER, tail_end, (x, y), thickness + 2)
            pygame.draw.line(self.screen, color, tail_end, (x, y), thickness)
            # 弹头（黑描边圆 + 高光）
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), r + 1)
            pygame.draw.circle(self.screen, color, (x, y), r)
            pygame.draw.circle(self.screen, T.TEXT_PRIMARY, (x - r // 3, y - r // 3), max(1, r // 3))
            if p.visual_kind == "ricochet":
                pygame.draw.circle(self.screen, T.ACCENT_2, (x, y), r + 4, width=max(2, int(3 * self.scale)))
            if p.visual_kind == "enemy_shard":
                side = max(3, r)
                perp = (-uy, ux)
                points = [
                    (x + int(ux * side * 2), y + int(uy * side * 2)),
                    (x + int(perp[0] * side), y + int(perp[1] * side)),
                    (x - int(ux * side * 2), y - int(uy * side * 2)),
                    (x - int(perp[0] * side), y - int(perp[1] * side)),
                ]
                pygame.draw.polygon(self.screen, T.TEXT_PRIMARY, points, width=1)

    def _draw_pickup(self, p) -> None:
        x, y = self._world_to_screen(p.position)
        # 按 kind 选色 + 形状
        if p.kind.startswith("xp"):
            color = T.PICKUP_XP
            shape = "diamond"
        elif p.kind == "heal":
            color = T.PICKUP_HEAL
            shape = "cross"
        elif p.kind == "shield_restore":
            color = T.PICKUP_SHIELD
            shape = "shield"
        elif p.kind == "armor":
            color = T.ARMOR_FILL
            shape = "armor"
        elif p.kind == "coin":
            color = T.CARD_GOLD
            shape = "coin"
        else:
            color = T.PICKUP_BUFF
            shape = "star"
        size = max(6, int(11 * self.scale))
        glow = make_glow(size * 3, color, 65)
        self.screen.blit(glow, glow.get_rect(center=(x, y)))
        asset_key = "xp" if p.kind.startswith("xp") else p.kind
        icon = self._scaled_art(self.pickup_icon_sources.get(asset_key), ("pickup", asset_key), (size * 3, size * 3))
        if icon is not None:
            self.screen.blit(icon, icon.get_rect(center=(x, y)))
        else:
            # 黑色描边
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), size + 1)
            if shape == "diamond":
                pts = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
                pygame.draw.polygon(self.screen, color, pts)
            elif shape == "cross":
                w = int(size * 0.45)
                pts = [(x - w, y - size), (x + w, y - size), (x + w, y - w),
                       (x + size, y - w), (x + size, y + w), (x + w, y + w),
                       (x + w, y + size), (x - w, y + size), (x - w, y + w),
                       (x - size, y + w), (x - size, y - w), (x - w, y - w)]
                pygame.draw.polygon(self.screen, color, pts)
            elif shape == "shield":
                pts = [(x, y - size), (x + size, y - size // 2), (x + size, y + size // 2),
                       (x, y + size), (x - size, y + size // 2), (x - size, y - size // 2)]
                pygame.draw.polygon(self.screen, color, pts)
            elif shape == "armor":
                pts = [(x, y - size), (x + size, y - size // 3), (x + size // 2, y + size),
                       (x, y + size // 2), (x - size // 2, y + size), (x - size, y - size // 3)]
                pygame.draw.polygon(self.screen, color, pts)
                pygame.draw.circle(self.screen, T.TEXT_PRIMARY, (x, y), max(2, size // 4))
            elif shape == "coin":
                pygame.draw.circle(self.screen, color, (x, y), size)
                pygame.draw.circle(self.screen, T.TEXT_DARK, (x, y), max(2, size // 2), width=2)
            else:
                # star (5-point)
                pts = []
                for i in range(10):
                    a = math.pi / 2 + i * math.pi / 5
                    r = size if i % 2 == 0 else size * 0.5
                    pts.append((x + math.cos(a) * r, y - math.sin(a) * r))
                pygame.draw.polygon(self.screen, color, pts)
            # 中心高光
            pygame.draw.circle(self.screen, (*T.TEXT_PRIMARY, 140), (x, y - size // 3), max(1, size // 3))
        # 磁吸线（P1-4：合并 icon / fallback 两条重复路径）
        d = math.hypot(p.position[0] - self.engine.player.position[0], p.position[1] - self.engine.player.position[1])
        eff = self.engine.player.base_pickup_radius * (1.0 + self.engine.player.growth.pickup_radius_pct)
        if d <= eff:
            pygame.draw.line(self.screen, (*T.ACCENT, 120), self._world_to_screen(self.engine.player.position), (x, y), 1)

    def _draw_bomb(self, b: HazardBomb) -> None:
        if getattr(b, "faction", "enemy") == "player":
            self._draw_player_thunder_bomb(b)
            return
        x, y = self._world_to_screen(b.position)
        # 元气骑士风炸弹：粗黑描边 + 高对比
        r = int(b.radius * self.scale)
        armed = self.engine.timer.run_time >= b.armed_at
        col = T.DANGER if armed else T.PICKUP_BOMB
        # 底层红色光晕（armed 时呼吸）
        glow_r = r * 2 if armed else r
        alpha = int(40 + 20 * math.sin(self.engine.timer.run_time * 8)) if armed else 28
        warning = pygame.Surface((glow_r * 2 + 8, glow_r * 2 + 8), pygame.SRCALPHA)
        pygame.draw.circle(warning, (*col, alpha), (glow_r + 4, glow_r + 4), glow_r)
        self.screen.blit(warning, (x - glow_r - 4, y - glow_r - 4))
        if armed:
            warning_art = self._scaled_art(self.effect_sources.get("bomb_warning"), ("bomb_warning",), (r * 2, r * 2))
            if warning_art is not None:
                self.screen.blit(warning_art, warning_art.get_rect(center=(x, y)))
        # 炸弹本体：圆 + 黑描边
        body_r = max(8, int(r * 0.28))
        pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), body_r + 2)
        pygame.draw.circle(self.screen, (32, 18, 22), (x, y), body_r)
        # 高光
        pygame.draw.circle(self.screen, (*col, 200), (x - body_r // 3, y - body_r // 3), max(2, body_r // 3))
        # 引线
        pygame.draw.line(self.screen, COL_HUD_BORDER, (x + body_r - 2, y - body_r + 2), (x + body_r + 6, y - body_r - 8), 2)
        if armed:
            # 火花
            sx, sy = x + body_r + 6, y - body_r - 8
            pulse = 0.5 + 0.5 * math.sin(self.engine.timer.run_time * 18)
            spark_r = max(3, int(5 * self.scale)) + int(pulse * 3)
            pygame.draw.circle(self.screen, T.WARN, (sx, sy), spark_r)
            pygame.draw.circle(self.screen, T.TEXT_PRIMARY, (sx, sy), spark_r // 2)
            # 倒计时环
            elapsed = max(0.0, self.engine.timer.run_time - b.armed_at)
            window = b.lifetime - b.arm_delay
            ratio = 1.0 - min(1.0, elapsed / max(0.0001, window))
            ring_rect = pygame.Rect(x - r, y - r, r * 2, r * 2)
            pygame.draw.arc(self.screen, col, ring_rect, 0, 6.28 * ratio, max(3, int(5 * self.scale)))
        # 在玩家范围内 → 高亮描边
        if armed:
            d = math.hypot(b.position[0] - self.engine.player.position[0], b.position[1] - self.engine.player.position[1])
            if d <= b.radius:
                pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), r, width=2)
                pygame.draw.circle(self.screen, col, (x, y), r, width=2)

    def _draw_player_thunder_bomb(self, b: HazardBomb) -> None:
        x, y = self._world_to_screen(b.position)
        now = self.engine.timer.run_time
        age = max(0.0, now - b.spawn_time)
        arm_t = min(1.0, age / max(0.001, b.arm_delay))
        armed = now >= b.armed_at
        trigger_at = b.armed_at + max(0.0, b.lifetime - b.arm_delay - 0.0001)
        charge_t = min(1.0, max(0.0, (now - b.armed_at) / max(0.001, trigger_at - b.armed_at))) if armed else 0.0
        r = max(18, int(b.radius * self.scale))
        color = (95, 220, 255)
        violet = (158, 88, 255)
        pulse = 0.5 + 0.5 * math.sin(now * 24)

        drew_glyph = self._blit_effect(
            "thunder_glyph", (x, y), (r * 2 + 18, r * 2 + 18),
            angle=now * 22.0, alpha=int(105 + 100 * max(arm_t, charge_t) + 35 * pulse),
            key_extra=("glyph",),
        )
        column_h = int((190 + 110 * charge_t) * self.scale)
        column_w = max(42, int((70 + 42 * charge_t + pulse * 8) * self.scale))
        drew_column = self._blit_effect(
            "thunder_column", (x, y - column_h // 2),
            (column_w, column_h), alpha=int(170 + 70 * max(arm_t, charge_t)),
            key_extra=("column",),
        )
        if drew_glyph and drew_column:
            core_r = max(7, int((12 + 10 * charge_t + pulse * 4) * self.scale))
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), core_r + 3)
            pygame.draw.circle(self.screen, color, (x, y), core_r)
            pygame.draw.circle(self.screen, T.TEXT_PRIMARY, (x, y), max(3, core_r // 2))
            return

        glyph = pygame.Surface((r * 2 + 18, r * 2 + 18), pygame.SRCALPHA)
        cx = cy = r + 9
        alpha = int(70 + 90 * max(arm_t, charge_t) + 45 * pulse)
        pygame.draw.circle(glyph, (*color, alpha // 2), (cx, cy), r)
        pygame.draw.circle(glyph, (*COL_HUD_BORDER, 185), (cx, cy), r, width=max(2, int(5 * self.scale)))
        pygame.draw.circle(glyph, (*color, alpha), (cx, cy), r, width=max(2, int(3 * self.scale)))
        for i in range(4):
            a = math.pi * 0.25 + i * math.pi * 0.5 + now * 0.6
            p1 = (cx + int(math.cos(a) * r * 0.24), cy + int(math.sin(a) * r * 0.24))
            p2 = (cx + int(math.cos(a) * r * 0.86), cy + int(math.sin(a) * r * 0.86))
            pygame.draw.line(glyph, (*violet, alpha), p1, p2, max(2, int(4 * self.scale)))
        self.screen.blit(glyph, glyph.get_rect(center=(x, y)))

        bolt_h = int((160 + 90 * charge_t) * self.scale)
        bolt_w = max(5, int((8 + 10 * charge_t + pulse * 4) * self.scale))
        top = y - bolt_h
        pygame.draw.line(self.screen, (*COL_HUD_BORDER, 210), (x, top), (x, y), bolt_w + 4)
        pygame.draw.line(self.screen, (*T.TEXT_PRIMARY, 230), (x, top), (x, y), max(2, bolt_w // 2))
        pygame.draw.line(self.screen, (*color, 230), (x - bolt_w, top + bolt_h // 3), (x + bolt_w, y), bolt_w)
        for i in range(3):
            branch_y = top + int(bolt_h * (0.35 + i * 0.18))
            side = -1 if i % 2 == 0 else 1
            end = (x + side * int((28 + 20 * pulse) * self.scale), branch_y + int(26 * self.scale))
            pygame.draw.line(self.screen, (*violet, 205), (x, branch_y), end, max(1, int(3 * self.scale)))

        core_r = max(7, int((12 + 10 * charge_t + pulse * 4) * self.scale))
        pygame.draw.circle(self.screen, COL_HUD_BORDER, (x, y), core_r + 3)
        pygame.draw.circle(self.screen, color, (x, y), core_r)
        pygame.draw.circle(self.screen, T.TEXT_PRIMARY, (x, y), max(3, core_r // 2))

    def _render_damage_numbers(self) -> None:
        now = self.engine.timer.run_time
        items = list(getattr(self.engine, "last_damage_numbers", []))
        keep = []
        # P1：先按 age 过滤，再走 _layout_damage_numbers 算 offset / scale / alpha
        active = []
        for item in items:
            age = now - float(item.get("time", now))
            if age > 0.85:
                continue
            keep.append(item)
            active.append(item)
        layouts = self._layout_damage_numbers(active, now)
        for item, layout in zip(active, layouts):
            x, y = self._world_to_screen(tuple(item.get("position", (0, 0))))
            y -= int((18 + (now - float(item["time"])) * 38) * self.scale)
            amount = int(max(1, round(float(item.get("amount", 0)))))
            crit = bool(item.get("crit"))
            color = T.CARD_GOLD if crit else T.TEXT_PRIMARY
            label = f"{amount}!" if crit else str(amount)
            # 桶偏移 + 缩放
            x += layout["x_offset"]
            # 缩放：用 font 直接以 size * scale 渲染
            base_size = 18 if crit else 14
            draw_size = max(10, int(round(base_size * layout["scale"])))
            font = self.font if crit else self.font_small
            # 淡出 alpha 通过额外叠一层半透蒙版实现
            img = font.render(label, True, color)
            if layout["alpha"] < 255:
                img = img.copy()
                img.set_alpha(layout["alpha"])
            outline_img = font.render(label, True, T.TEXT_OUTLINE)
            if layout["alpha"] < 255:
                outline_img = outline_img.copy()
                outline_img.set_alpha(layout["alpha"])
            r = img.get_rect(center=(x, y))
            for ox in (-2, 2):
                for oy in (-2, 2):
                    self.screen.blit(outline_img, (r.x + ox, r.y + oy))
            self.screen.blit(img, r)
        self.engine.last_damage_numbers = keep[-32:]

    def _render_touch_controls(self) -> None:
        if not getattr(self, "_touch_controls_enabled", False):
            return
        jx, jy = self.touch.joy_center
        r = self.touch.joy_radius
        sx, sy = self._stick_screen_pos()
        joy_size = r * 2 + 12
        joy = pygame.Surface((joy_size, joy_size), pygame.SRCALPHA)
        # 黑色外描边
        pygame.draw.circle(joy, COL_HUD_BORDER, (joy_size // 2, joy_size // 2), r + 4)
        pygame.draw.circle(joy, T.BG_PANEL_ALT + (180,), (joy_size // 2, joy_size // 2), r)
        self.screen.blit(joy, (jx - joy_size // 2, jy - joy_size // 2))
        # 摇杆头
        pygame.draw.circle(self.screen, COL_HUD_BORDER, (sx, sy), max(22, r // 3) + 2)
        pygame.draw.circle(self.screen, T.ACCENT, (sx, sy), max(20, r // 3))
        pygame.draw.circle(self.screen, (*T.TEXT_PRIMARY, 100), (sx, sy), max(10, r // 5))
        # 切换按钮
        sr = self._switch_rect()
        draw_button(self.screen, sr, "切", font=self.font, active=False, accent=T.ACCENT_2)
        # 暂停按钮
        pr = self._pause_rect()
        draw_button(self.screen, pr, "II", font=self.font_mid, active=False, accent=T.ACCENT)

    # ---- P1：伤害数字聚拢算法 --------------------------------------------
    @staticmethod
    def _layout_damage_numbers(items: list, run_time: float) -> list:
        """返回每个伤害的 {x_offset, scale, alpha, ...}，同位置 bucket 横向错开 14px。"""
        if not items:
            return []
        buckets: dict[tuple[int, int], int] = {}
        result = []
        for item in items:
            pos = item.get("position", (0.0, 0.0))
            key = (int(pos[0] // 32), int(pos[1] // 32))
            bucket_index = buckets.get(key, 0)
            buckets[key] = bucket_index + 1
            age = max(0.0, run_time - float(item.get("time", run_time)))
            # 进入时 0.1s 缩放 1.3 -> 1.0；0.85s 后淡出
            if age < 0.1:
                scale = 1.3 - 0.3 * (age / 0.1)
            else:
                scale = 1.0
            if age > 0.7:
                alpha = int(255 * (1.0 - (age - 0.7) / 0.15))
            else:
                alpha = 255
            result.append({
                "x_offset": bucket_index * 14,
                "scale": scale,
                "alpha": max(0, min(255, alpha)),
            })
        return result

    # ---- P3：关卡过渡布局 ------------------------------------------------
    @staticmethod
    def _stage_clear_layout(width: int, height: int) -> dict:
        return {
            "veil_alpha": 240,
            "gold_bar_h": 8,
            "title_size": 96,
            "panel_w": 640,
            "panel_h": 440,
        }

    # ---- P4：武器切换延迟环算法 -------------------------------------------
    @staticmethod
    def _switch_ring_geometry(rect: pygame.Rect, equip_left: float, equip_delay: float = 0.25) -> dict:
        if equip_left <= 0:
            return {"show_ring": False, "start": 0.0, "end": 0.0, "alpha": 0}
        ratio = max(0.0, min(1.0, 1 - equip_left / equip_delay))
        return {
            "show_ring": True,
            "start": -1.57,
            "end": -1.57 + 6.28 * ratio,
            "alpha": 220,
        }

    # ---- P5：武器槽圆形化 + 外环等级 ------------------------------------
    @staticmethod
    def _weapon_slot_circle(weapon_id: str, level: int, max_level: int, center, radius: int) -> dict:
        rarity = "common"
        if weapon_id and weapon_id != "":
            first = weapon_id.split("_")[0]
            if first in {"rare", "epic", "legendary"}:
                rarity = first
        return {
            "center": center,
            "radius": radius,
            "ring_thickness": max(2, int(radius * 0.18 * (level / max(1, max_level)))),
            "rarity_color": {
                "common": (180, 196, 214),
                "rare": (90, 215, 255),
                "epic": (255, 130, 210),
                "legendary": (255, 200, 100),
            }.get(rarity, (180, 196, 214)),
        }

    # ---- P6：组合技屏幕特效几何 -----------------------------------------
    @staticmethod
    def _combo_fx(combo_id: str, age: float, max_age: float = 1.2) -> dict:
        colors = {
            "thunder_chain": (140, 220, 255),
            "steam_burst": (255, 255, 255),
            "corrupt_blood": (160, 255, 80),
            "focused_lattice": (90, 200, 255),
            "earth_shock": (255, 170, 60),
        }
        progress = max(0.0, min(1.0, age / max_age))
        return {
            "color": colors.get(combo_id, (255, 200, 100)),
            "alpha": int(220 * (1 - progress)),
            "hex_radius": int(60 + 140 * progress),
        }

    # ---- P7：成就徽章 -------------------------------------------------
    @staticmethod
    def _achievement_badge(achievements: list, unlocked: set, center, radius: int = 22) -> dict:
        total = len(achievements)
        unlocked_count = len(unlocked)
        return {
            "center": center,
            "radius": radius,
            "ring_thickness": max(2, int(radius * 0.18)),
            "unlocked_count": unlocked_count,
            "total": total,
            "ratio": unlocked_count / max(1, total),
            "next_locked": [a for a in achievements if a not in unlocked][:4],
        }

    # ---- P8：战斗音效空间化 -------------------------------------------
    @staticmethod
    def _battle_sound(event: str) -> dict:
        mapping = {
            "hit": {"name": "sfx_hit_normal", "volume": 0.20},
            "crit": {"name": "sfx_crit", "volume": 0.35},
            "pickup": {"name": "sfx_pickup", "volume": 0.40},
            "enemy_die": {"name": "sfx_enemy_die", "volume": 0.25},
        }
        return mapping.get(event, {"name": "", "volume": 0.0})

    # ---- P9：商店 tab + 搜索 -------------------------------------------
    @staticmethod
    def _shop_filter(items: list, tab: str, query: str = "") -> list:
        if tab != "all":
            items = [it for it in items if it[0].startswith(f"{tab}:")]
        if query:
            q = query.lower()
            items = [it for it in items if q in it[0].lower() or q in it[1].get("name", "").lower()]
        return items

    def _render_active_skill_effects(self) -> None:
        if self.engine.active_skill_id != "axe_orbit" or self.engine.active_skill_left <= 0:
            return
        px, py = self._world_to_screen(self.engine.player.position)
        radius = int(110 * self.scale)
        t = self.engine.timer.run_time * 4.6
        for i in range(3):
            a = t + math.tau * i / 3
            ax = px + int(math.cos(a) * radius)
            ay = py + int(math.sin(a) * radius)
            pygame.draw.circle(self.screen, COL_HUD_BORDER, (ax, ay), max(12, int(18 * self.scale)))
            pygame.draw.circle(self.screen, T.ENEMY_ELITE, (ax, ay), max(9, int(14 * self.scale)))
            pygame.draw.line(self.screen, T.ACCENT, (px, py), (ax, ay), max(1, int(2 * self.scale)))

    def _stick_screen_pos(self):
        jx, jy = self.touch.joy_center
        r = self.touch.joy_radius
        sx, sy = self.touch._stick_pos
        dx = sx - jx
        dy = sy - jy
        d = math.hypot(dx, dy)
        if d > r:
            sx, sy = jx + dx / d * r, jy + dy / d * r
        return (int(sx), int(sy))

    def _render_hud(self, st: str) -> None:
        # 左上 HP / 护盾 / 护甲（元气骑士风胶囊面板）
        px = self.world_rect.x + 24
        py = self.world_rect.y + 24
        panel_rect = pygame.Rect(px - 12, py - 12, 280, 100)
        draw_panel(self.screen, panel_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=220, radius=14, outline=3)
        maxhp = self.engine.player.base_max_hp * (1.0 + self.engine.player.extra_max_hp_pct + self.engine.player.growth.max_hp_pct_bonus)
        hp_text = f"生命 {int(self.engine.player.current_hp)}/{int(maxhp)}"
        draw_text(self.screen, hp_text, (px, py - 2), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        bar_rect = pygame.Rect(px, py + 20, 240, 12)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, bar_rect.inflate(4, 2), border_radius=6)
        pygame.draw.rect(self.screen, COL_HP_BACK, bar_rect, border_radius=5)
        hp_ratio = self.engine.player.current_hp / max(1.0, maxhp)
        pygame.draw.rect(self.screen, COL_HP, (bar_rect.x, bar_rect.y, int(bar_rect.w * max(0, min(1, hp_ratio))), bar_rect.h), border_radius=5)
        # 护盾 / 护甲文本
        shield = self.engine.player.current_shield
        smax = self.engine.player.max_shield + self.engine.player.growth.max_shield_extra
        if smax > 0:
            draw_text(self.screen, f"护盾 {int(shield)}/{int(smax)}", (px, py + 42), size=16, color=T.SHIELD_FILL, font=self.font_small, outline=1)
        arm = self.engine.player.base_armor
        if arm > 0:
            draw_text(self.screen, f"护甲 {int(arm)}", (px, py + 62), size=16, color=T.ARMOR_FILL, font=self.font_small, outline=1)
        # 顶部中央：阶段 + 时间
        cx = self.world_rect.centerx
        cy = self.world_rect.y + 24
        stage_rect = pygame.Rect(cx - 140, cy - 12, 280, 76)
        draw_panel(self.screen, stage_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=220, radius=14, outline=3)
        if self.engine.context.mode == "ENDLESS":
            stage_label = f"无尽·循环 {self.engine.context.endless_cycle}"
            cur_label = int(self.engine.context.stage_score)
            threshold_label = f"→ {(self.engine.context.endless_cycle + 1) * 5000}"
        else:
            stage_label = f"第 {self.engine.context.stage_index} 关"
            cur_label = int(self.engine.context.stage_score)
            threshold_label = "· 清场中" if self.engine.stage_lockdown else {1: "→1200", 2: "→2600", 3: "→4800", 4: "→6800", 5: "→9000"}[min(self.engine.context.stage_index, 5)]
        draw_text_center(self.screen, stage_label, pygame.Rect(cx - 130, cy - 4, 260, 30), color=T.TEXT_PRIMARY, font=self.font, outline=2)
        draw_text_center(self.screen, f"{fmt_time(self.engine.timer.stage_time)}", pygame.Rect(cx - 90, cy + 28, 180, 24), color=T.ACCENT, font=self.font_small, outline=1)
        # 右上：分数 / 抽卡 / 超级
        rx = self.world_rect.right - 296
        ry = self.world_rect.y + 24
        right_rect = pygame.Rect(rx - 16, ry - 12, 312, 124)
        draw_panel(self.screen, right_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=220, radius=14, outline=3)
        draw_text(self.screen, f"关卡分 {cur_label} {threshold_label}", (rx, ry - 2), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        card_next = 800 if self.engine.context.mode == "ENDLESS" else self.engine._next_card_cost()
        draw_text(self.screen, f"抽卡分 {self.engine.context.card_score}/{card_next}", (rx, ry + 22), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        sd = self.engine.super_director
        progress = sd.progress
        required = max(1, sd.required_kills)
        line = f"首领 {progress}/{required} {'（即将出现）' if sd.queued > 0 else ''}"
        if self.engine.context.mode != "ENDLESS":
            boss_need = {1: 900, 2: 2000, 3: 3600, 4: 5200, 5: 7200}[min(self.engine.context.stage_index, 5)]
            line = f"首领分 {min(self.engine.context.stage_score, boss_need)}/{boss_need} {'（即将出现）' if sd.queued > 0 else ''}"
        draw_text(self.screen, line, (rx, ry + 44), size=16, color=COL_SUPER_BAR if sd.queued > 0 else T.TEXT_DIM, font=self.font_small, outline=1)
        draw_text(self.screen, f"金币 {self.engine.gold()}  本局 +{self.engine.run_gold_earned}", (rx, ry + 78), size=16, color=T.CARD_GOLD, font=self.font_small, outline=1)
        # 进度条
        bar2 = pygame.Rect(rx, ry + 64, 260, 6)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, bar2.inflate(4, 2), border_radius=4)
        pygame.draw.rect(self.screen, T.BG_PANEL_ALT, bar2, border_radius=3)
        boss_ratio = progress / required
        if self.engine.context.mode != "ENDLESS":
            boss_ratio = min(1.0, self.engine.context.stage_score / max(1, boss_need))
        pygame.draw.rect(self.screen, T.ENEMY_SUPER, (bar2.x, bar2.y, int(bar2.w * boss_ratio), bar2.h), border_radius=3)
        # 左侧：抽卡共鸣 + 武器组合技 — T1 改造：只在有进度时显示
        summary = self._build_progress_summary(
            self.engine.card_combo_counts,
            self.engine.card_combo_unlocked,
            self.engine.weapon_synergy_status(),
        )
        if summary["visible"]:
            combo_rect = pygame.Rect(self.world_rect.x + 24, self.world_rect.y + 132, 280, 100)
            draw_panel(self.screen, combo_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=205, radius=12, outline=3)
            draw_text(self.screen, "集卡共鸣", (combo_rect.x + 16, combo_rect.y + 10), size=16, color=T.ACCENT_2, font=self.font_small, outline=1)
            # 只列有进度的行
            visible_card_rows = [r for r in summary["card_rows"] if r["count"] > 0 or r["done"]]
            for i, row in enumerate(visible_card_rows[:5]):
                cfg = CARD_COMBO_SETS.get(row["id"], {})
                name = cfg.get("name", row["id"])
                color = T.CARD_COLOR if row["done"] else T.TEXT_DIM
                line = f"已激活 {name}" if row["done"] else f"{name} {row['count']}/3"
                draw_text(self.screen, line[:16], (combo_rect.x + 16, combo_rect.y + 32 + i * 16), size=12, color=color, font=self.font_small, outline=1)
            # 武器组合技面板
            if summary["weapon_rows"]:
                weapon_combo_rect = pygame.Rect(self.world_rect.x + 24, combo_rect.bottom + 8, 280, 100)
                draw_panel(self.screen, weapon_combo_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=192, radius=12, outline=3)
                draw_text(self.screen, "武器组合技", (weapon_combo_rect.x + 16, weapon_combo_rect.y + 10), size=16, color=T.CARD_GOLD, font=self.font_small, outline=1)
                for i, row in enumerate(summary["weapon_rows"][:4]):
                    icon_box = pygame.Rect(weapon_combo_rect.x + 16, weapon_combo_rect.y + 32 + i * 18, 16, 16)
                    status_art = self._scaled_art(self.ui_art_sources.get("combo_active"), ("ui", "combo_state", True), icon_box.size)
                    if status_art is not None:
                        self.screen.blit(status_art, icon_box.topleft)
                    icon = self._scaled_art(self.combo_icon_sources.get(row["id"]), ("combo", row["id"]), (16, 16))
                    if icon is not None:
                        self.screen.blit(icon, icon.get_rect(center=icon_box.center))
                    draw_text(self.screen, f"{row['name']}", (weapon_combo_rect.x + 38, weapon_combo_rect.y + 34 + i * 18), size=12, color=T.CARD_GOLD, font=self.font_small, outline=1)
        notice = self.engine.last_weapon_synergy_notice
        if notice and self.engine.timer.run_time - float(notice.get("time", -99)) < 2.8:
            self._enqueue_notice("weapon_synergy", notice, ttl=2.8, time_attr="time")
        ev = self.engine.active_random_event
        if ev:
            self._enqueue_notice(
                "random_event",
                {
                    "id": ev.get("id", ""),
                    "name": ev.get("name", "事件"),
                    "desc": ev.get("desc", ""),
                    "left": float(ev.get("left", 0.0)),
                },
                ttl=max(0.4, float(ev.get("left", 0.0))),
            )
        # 子报告 P1-7：原 challenge_rect 跟 lv_rect 在 1280x720 互相侵入。
        # challenge 留在左下，lv 居中，竖向错开 36px；challenge 缩到 320 宽避免压到中间。
        challenge_rect = pygame.Rect(self.world_rect.x + 24, self.world_rect.bottom - 64, 320, 52)
        active_challenges = [c for c in self.engine.run_challenges if not c.get("completed") and not c.get("failed")]
        if active_challenges:
            draw_panel(self.screen, challenge_rect, border=T.ACCENT, fill=T.BG_PANEL, alpha=184, radius=12, outline=3)
            draw_text(self.screen, "局内挑战", (challenge_rect.x + 14, challenge_rect.y + 6), size=14, color=T.ACCENT, font=self.font_small, outline=1)
            for i, ch in enumerate(active_challenges[:2]):
                progress = ch.get("progress", 0)
                target = ch.get("target", "")
                # 缩窄文字以避免挤出血条
                name_short = (ch['name'] + '  ' + f"{int(progress)}/{target}")[:24]
                draw_text(self.screen, name_short, (challenge_rect.x + 14, challenge_rect.y + 24 + i * 14), size=12, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        if self.engine.last_challenge_notice and self.engine.timer.run_time - self.engine.last_challenge_notice.get("time", -99) < 2.8:
            self._enqueue_notice(
                "challenge",
                {"name": self.engine.last_challenge_notice.get("name", "挑战")},
                ttl=2.8,
                time_attr="time",
            )
        if self.engine.last_killstreak_notice and self.engine.timer.run_time - self.engine.last_killstreak_notice.get("time", -99) < 2.2:
            self._enqueue_notice(
                "killstreak",
                {"count": self.engine.last_killstreak_notice.get("count", 0)},
                ttl=2.2,
                time_attr="time",
            )
        self._draw_notice_stack(stage_rect.bottom)
        # 右下：武器栈 / 激活武器 — P5 圆形化 + 外环等级
        weapon_y = self.world_rect.bottom - 108
        weapon_x = self.world_rect.right - 344
        circle_r = 38
        gap = 12
        for i, w in enumerate(self.engine.weapon_sys.stack):
            is_active = i == self.engine.weapon_sys.active_index
            cx = weapon_x + i * (circle_r * 2 + gap) + circle_r
            cy = weapon_y + circle_r + 8
            center = (cx, cy)
            # 圆底 + 外环（按等级）
            geom = self._weapon_slot_circle(w.weapon_id, w.level, w.max_level, center, circle_r)
            # 黑色描边外层
            pygame.draw.circle(self.screen, COL_HUD_BORDER, center, circle_r + 3)
            bg_color = T.ACCENT_2 if is_active else T.BG_PANEL_ALT
            pygame.draw.circle(self.screen, bg_color, center, circle_r)
            # 稀有度外环
            ring_th = geom["ring_thickness"]
            if ring_th > 1:
                pygame.draw.circle(self.screen, geom["rarity_color"], center, circle_r - 2, width=max(1, ring_th))
            # 中心武器图标
            icon = self._scaled_art(self.weapon_icon_sources.get(w.weapon_id), ("weapon", w.weapon_id), (circle_r - 12, circle_r - 12))
            if icon is not None:
                self.screen.blit(icon, icon.get_rect(center=center))
            # 激活高亮描边
            if is_active:
                pygame.draw.circle(self.screen, T.ACCENT, center, circle_r + 2, width=2)
            # P4：装备延迟环
            if w.equip_left > 0:
                ring_rect = pygame.Rect(cx - circle_r, cy - circle_r, circle_r * 2, circle_r * 2)
                geom2 = self._switch_ring_geometry(ring_rect, w.equip_left)
                if geom2["show_ring"]:
                    pygame.draw.arc(self.screen, T.CARD_GOLD, ring_rect, geom2["start"], geom2["end"], 3)
                    s = pygame.Surface((circle_r * 2, circle_r * 2), pygame.SRCALPHA)
                    s.fill((255, 200, 80, 30))
                    self.screen.blit(s, (cx - circle_r, cy - circle_r))
            # 等级 / 名字（写在圆下方）
            draw_text_center(self.screen, f"Lv{w.level}", pygame.Rect(cx - 36, cy + circle_r - 4, 72, 18),
                             size=11, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        # 底部右侧：主动技能
        skill_cfg = ACTIVE_SKILLS.get(self.engine.active_skill_id, ACTIVE_SKILLS["bomb_trap"])
        skill_rect = pygame.Rect(weapon_x - 108, weapon_y, 92, 60)
        ready = self.engine.active_skill_cd_left <= 0
        draw_panel(self.screen, skill_rect, border=T.ACCENT if ready else COL_HUD_BORDER, fill=T.BG_PANEL_ALT, alpha=225, radius=10, outline=3)
        draw_text_center(self.screen, "技", pygame.Rect(skill_rect.x + 6, skill_rect.y + 8, 24, 24), color=T.ACCENT, font=self.font_small, outline=1)
        draw_text(self.screen, skill_cfg["name"], (skill_rect.x + 32, skill_rect.y + 8), size=14, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        cd_text = "就绪" if ready else f"冷却{self.engine.active_skill_cd_left:.1f}"
        draw_text(self.screen, cd_text, (skill_rect.x + 32, skill_rect.y + 32), size=14, color=T.ACCENT if ready else T.TEXT_DIM, font=self.font_small, outline=1)
        # 底部中央：等级 + 经验
        # 子报告 P1-7：原 challenge_rect 跟 lv_rect 在 1280x720 互相侵入 146x36。
        # challenge_rect 沿用原位；lv_rect 上移 56px、宽 200、水平居中。
        lv_x = self.world_rect.centerx - 100
        lv_y = self.world_rect.bottom - 48
        lv = self.engine.level_sys.level
        cur_xp = self.engine.level_sys.current_xp
        need = self.engine.level_sys.current_xp if self.engine.level_sys.is_at_cap() else (lambda: __import__('rgame.level.level_up', fromlist=['xp_to_next']).xp_to_next(lv))()
        ratio = 1.0 if self.engine.level_sys.is_at_cap() else max(0.0, min(1.0, cur_xp / max(1, need)))
        lv_rect = pygame.Rect(lv_x - 16, lv_y - 34, 232, 56)
        draw_panel(self.screen, lv_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=220, radius=12, outline=3)
        bar3 = pygame.Rect(lv_x, lv_y, 216, 10)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, bar3.inflate(4, 2), border_radius=5)
        pygame.draw.rect(self.screen, T.XP_BACK, bar3, border_radius=4)
        pygame.draw.rect(self.screen, T.XP_FILL, (bar3.x, bar3.y, int(bar3.w * ratio), bar3.h), border_radius=4)
        draw_text(self.screen, f"等级{lv}  经验 {cur_xp}/{need if not self.engine.level_sys.is_at_cap() else '满级'}", (lv_x, lv_y - 22), size=16, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)

    def _render_menu(self, st: str) -> None:
        cw, ch = self.screen_w, self.screen_h
        self._render_menu_backdrop()
        # 标题
        if st == "MAIN_MENU":
            title_rect = pygame.Rect(cw // 2 - 380, 88, 760, 200)
            draw_panel(self.screen, title_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=190, radius=20, outline=4)
            draw_text_center(self.screen, "火星攻击", pygame.Rect(cw // 2 - 240, 116, 480, 80), color=T.ACCENT, font=self.font_big, outline=3)
            draw_text_center(self.screen, "俯视角单屏肉鸽", pygame.Rect(cw // 2 - 240, 196, 480, 40), color=T.TEXT_PRIMARY, font=self.font_mid, outline=2)
            draw_text_center(self.screen, "战斗：移动键/方向键移动 · 技能键放技能 · 切换键换武器", pygame.Rect(cw // 2 - 360, 238, 720, 24), color=T.ACCENT, font=self.font_small, outline=1)
            draw_text_center(self.screen, "菜单：上下选择，左右切技能，确认键进入", pygame.Rect(cw // 2 - 330, 264, 660, 24), color=T.TEXT_DIM, font=self.font_small, outline=1)
            # 主菜单按钮（元气骑士风胶囊）
            account = getattr(self.engine.profile, "account_name", self.engine.profile.profile_id)
            draw_text_center(self.screen, f"账号：{account}   金币：{self.engine.gold()}", pygame.Rect(cw // 2 - 280, 292, 560, 28), color=T.CARD_GOLD, font=self.font_small, outline=1)
            for i, label in enumerate(["开始", "商店", "成就", "历史", "切换账号", "退出"]):
                btn = pygame.Rect(cw // 2 - 160, 324 + i * 62, 320, 54)
                accent = (T.ACCENT, T.CARD_GOLD, T.ACCENT_2, T.ACCENT_3, T.PICKUP_SHIELD, T.DANGER)[i]
                draw_button(self.screen, btn, label, font=self.font_mid, active=(i == self.selection_state["main"]), accent=accent)
            self._render_history_preview()
            # 应用版本
            ver = f"版本 {self.engine.context.app_version} · 配置 {self.engine.context.config_version}"
            draw_text(self.screen, ver, (12, ch - 24), size=14, color=T.TEXT_DIM, font=self.font_small)
        elif st == "MODE_SELECT":
            draw_text_center(self.screen, "选择模式", pygame.Rect(cw // 2 - 160, 70, 320, 64), color=T.ACCENT, font=self.font_big, outline=3)
            for i, label in enumerate(["常规关 1-5", "无尽模式（已解锁）" if self.engine.profile.campaign_cleared else "无尽模式（需通关常规关）", "返回"]):
                btn = pygame.Rect(cw // 2 - 220, 200 + i * 84, 440, 72)
                accent = (T.ACCENT, T.ACCENT_2, T.ACCENT_3)[i]
                draw_button(self.screen, btn, label, font=self.font_mid, active=(i == self.selection_state["mode"]), accent=accent)
        elif st == "PRESET_SELECT":
            draw_text_center(self.screen, "配置开局装备", pygame.Rect(cw // 2 - 240, 54, 480, 64), color=T.ACCENT, font=self.font_big, outline=3)
            selected = self.engine.selected_starting_weapon_ids
            selected_eq = self.engine.selected_equipment_ids
            slot_rows = [
                ("武器槽 1", zh_weapon_name(selected[0], selected[0]) if len(selected) > 0 else "未选择"),
                ("武器槽 2", zh_weapon_name(selected[1], selected[1]) if len(selected) > 1 else "未选择"),
                ("核心 1", EQUIPMENT_ITEMS.get(selected_eq[0], {}).get("name", selected_eq[0]) if len(selected_eq) > 0 else "未选择"),
                ("核心 2", EQUIPMENT_ITEMS.get(selected_eq[1], {}).get("name", selected_eq[1]) if len(selected_eq) > 1 else "未选择"),
            ]
            accents = [T.ACCENT, T.ACCENT_2, T.PICKUP_SHIELD, T.CARD_COLOR, T.CARD_GOLD]
            left_panel = pygame.Rect(cw // 2 - 585, 132, 350, 404)
            draw_panel(self.screen, left_panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=205, radius=14, outline=3)
            draw_text(self.screen, "开局槽位", (left_panel.x + 24, left_panel.y + 18), size=22, color=T.TEXT_PRIMARY, font=self.font, outline=2)
            for i, (slot_label, item_label) in enumerate(slot_rows):
                btn = pygame.Rect(left_panel.x + 20, left_panel.y + 58 + i * 66, 310, 54)
                active = (i == self.selection_state["preset"])
                draw_panel(self.screen, btn, border=accents[i] if active else COL_HUD_BORDER, fill=T.BG_PANEL_ALT, alpha=232 if active else 205, radius=10, outline=3)
                draw_text(self.screen, slot_label, (btn.x + 16, btn.y + 7), size=14, color=accents[i], font=self.font_small, outline=1)
                draw_text(self.screen, item_label[:12], (btn.x + 16, btn.y + 28), size=17, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            start_btn = pygame.Rect(left_panel.x + 20, left_panel.y + 58 + 4 * 66, 310, 54)
            draw_button(self.screen, start_btn, "开始游戏", font=self.font_mid, active=(self.selection_state["preset"] == 4), accent=T.CARD_GOLD)
            picker = pygame.Rect(cw // 2 - 205, 132, 790, 404)
            draw_panel(self.screen, picker, border=T.ACCENT_2, fill=T.BG_PANEL, alpha=210, radius=14, outline=3)
            active_slot = self.selection_state["preset"]
            is_equipment = active_slot in (2, 3)
            if active_slot == 4:
                draw_text_center(self.screen, "确认配置后开始游戏", pygame.Rect(picker.x + 40, picker.y + 78, picker.w - 80, 60), color=T.CARD_GOLD, font=self.font_mid, outline=2)
                draw_text_center(self.screen, "上方槽位会带入本局；主动技能在下方选择。", pygame.Rect(picker.x + 40, picker.y + 152, picker.w - 80, 32), color=T.TEXT_DIM, font=self.font_small, outline=1)
                current_pool = []
            elif is_equipment:
                current_pool = self.engine.account_equipment_pool()
                self.equipment_pool_index = max(0, min(self.equipment_pool_index, max(0, len(current_pool) - 1)))
                draw_text(self.screen, f"选择核心槽 {active_slot - 1}", (picker.x + 24, picker.y + 18), size=22, color=T.PICKUP_SHIELD, font=self.font, outline=2)
                draw_text(self.screen, f"{self.equipment_pool_index + 1}/{max(1, len(current_pool))}", (picker.right - 86, picker.y + 22), size=16, color=T.TEXT_DIM, font=self.font_small, outline=1)
            else:
                current_pool = self.engine.account_weapon_pool()
                self.weapon_pool_index = max(0, min(self.weapon_pool_index, max(0, len(current_pool) - 1)))
                draw_text(self.screen, f"选择武器槽 {active_slot + 1}", (picker.x + 24, picker.y + 18), size=22, color=T.ACCENT, font=self.font, outline=2)
                draw_text(self.screen, f"{self.weapon_pool_index + 1}/{max(1, len(current_pool))}", (picker.right - 86, picker.y + 22), size=16, color=T.TEXT_DIM, font=self.font_small, outline=1)
            if active_slot != 4:
                visible_count = 5
                focus = self.equipment_pool_index if is_equipment else self.weapon_pool_index
                first = self._pool_page_start(len(current_pool), focus, visible_count)
                visible = current_pool[first:first + visible_count]
                list_rect = pygame.Rect(picker.x + 24, picker.y + 58, picker.w - 48, 302)
                pygame.draw.rect(self.screen, COL_HUD_BORDER, list_rect, border_radius=12)
                pygame.draw.rect(self.screen, T.BG_PANEL_ALT, list_rect.inflate(-4, -4), border_radius=10)
                for offset, item_id in enumerate(visible):
                    i = first + offset
                    row = pygame.Rect(list_rect.x + 12, list_rect.y + 8 + offset * 58, list_rect.w - 24, 52)
                    focused = i == focus
                    chosen = item_id in (selected_eq if is_equipment else selected)
                    border = T.ACCENT if focused else (T.CARD_GOLD if chosen else COL_HUD_BORDER)
                    fill = T.ACCENT_2 if focused else T.BG_PANEL_ALT
                    draw_panel(self.screen, row, border=border, fill=fill, alpha=230 if focused else 198, radius=8, outline=2)
                    icon_box = pygame.Rect(row.x + 10, row.y + 8, 36, 36)
                    pygame.draw.rect(self.screen, COL_HUD_BORDER, icon_box, border_radius=8)
                    pygame.draw.rect(self.screen, T.BG_PANEL, icon_box.inflate(-4, -4), border_radius=6)
                    if is_equipment:
                        icon = self._scaled_art(self.equipment_icon_sources.get(item_id), ("config_equipment_list", item_id), (28, 28))
                        name = EQUIPMENT_ITEMS.get(item_id, {}).get("name", item_id)
                        desc = EQUIPMENT_ITEMS.get(item_id, {}).get("desc", "")
                    else:
                        icon = self._scaled_art(self.weapon_icon_sources.get(item_id), ("config_weapon_list", item_id), (28, 28))
                        name = zh_weapon_name(item_id, item_id)
                        cfg = self.engine.bundle.weapons.get(item_id, {})
                        desc = f"伤害 {cfg.get('base_damage', '-')} · 间隔 {cfg.get('attack_interval', '-')}"
                    if icon is not None:
                        self.screen.blit(icon, icon.get_rect(center=icon_box.center))
                    draw_text(self.screen, name[:18], (row.x + 60, row.y + 8), size=15, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
                    draw_text(self.screen, desc[:40], (row.x + 60, row.y + 30), size=13, color=T.TEXT_DIM, font=self.font_small, outline=1)
                    status = "当前光标" if focused else ("已装入" if chosen else "")
                    if status:
                        draw_text(self.screen, status, (row.right - 92, row.y + 17), size=13, color=T.ACCENT if focused else T.CARD_GOLD, font=self.font_small, outline=1)
                if len(current_pool) > visible_count:
                    draw_text_center(self.screen, "A/D 切换列表项目，确认装入当前槽位", pygame.Rect(picker.x + 40, picker.bottom - 40, picker.w - 80, 24), color=T.TEXT_DIM, font=self.font_small, outline=1)
            # T3 改造：技能 chip 显示冷却 + 难度；下方显示选中技能的描述。
            selected_skill = self.skill_ids[self.skill_select_index]
            selected_preview = self._skill_preview(selected_skill)
            chip_y = 560
            chip_h = 56
            for i, sid in enumerate(self.skill_ids):
                p = self._skill_preview(sid)
                chip = pygame.Rect(cw // 2 - 330 + i * 220, chip_y, 200, chip_h)
                accent = (T.ACCENT, T.ACCENT_2, T.ENEMY_ELITE)[i]
                draw_button(self.screen, chip, p["name"], font=self.font_mid, active=(i == self.skill_select_index), accent=accent)
                # 副标题：冷却 / 难度
                sub = f"冷却{int(p['cooldown'])}秒 · {p['difficulty']}"
                draw_text_center(self.screen, sub, pygame.Rect(chip.x, chip.bottom - 18, chip.w, 18),
                                 color=T.TEXT_DIM, font=self.font_small, outline=1, size=12)
            # 选中技能描述
            desc_rect = pygame.Rect(cw // 2 - 480, chip_y + chip_h + 8, 960, 28)
            draw_text_center(self.screen, selected_preview["desc"], desc_rect, color=T.ACCENT, font=self.font_small, outline=1, size=13)
            # 操作提示也补充左右键切技能
            draw_text_center(self.screen, "W/S选槽位或开始 · A/D选当前池项目 · Q/E/A/D选技能 · 确认装入",
                             pygame.Rect(cw // 2 - 480, 620, 960, 24),
                             color=T.TEXT_DIM, font=self.font_small, outline=1, size=13)
        elif st == "RESULT":
            self._render_result()
        elif st == "BOOT":
            draw_text(self.screen, "载入中……", (cw // 2 - 80, ch // 2 - 20), size=36, color=T.TEXT_PRIMARY, font=self.font_big, outline=2)

    def _render_menu_backdrop(self) -> None:
        if self.bg_source is not None:
            bg = pygame.transform.smoothscale(self.bg_source, (self.screen_w, self.screen_h))
            self.screen.blit(bg, (0, 0))
        else:
            pygame.draw.rect(self.screen, T.BG_DARK, (0, 0, self.screen_w, self.screen_h))
        # 元气骑士风：暖色暗角 + 中心 cyan 辉光
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        # 顶/底渐变暗角
        for y in range(0, self.screen_h, 4):
            t = abs(y - self.screen_h // 2) / (self.screen_h / 2)
            a = int(80 * t)
            pygame.draw.line(overlay, (4, 8, 16, a), (0, y), (self.screen_w, y), 4)
        self.screen.blit(overlay, (0, 0))
        cx, cy = self.screen_w // 2, int(self.screen_h * 0.38)
        glow = make_glow(max(180, min(self.screen_w, self.screen_h) // 3), T.ACCENT, 70)
        self.screen.blit(glow, glow.get_rect(center=(cx, cy)))
        # 装饰：左上角小六边形 logo 块
        deco_rect = pygame.Rect(28, 28, 84, 84)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, deco_rect, border_radius=18)
        pygame.draw.rect(self.screen, T.ACCENT, deco_rect.inflate(-6, -6), border_radius=14)
        draw_text_center(self.screen, "肉", deco_rect, color=T.TEXT_DARK, font=self.font_mid, outline=1)

    def _render_result(self) -> None:
        cw, ch = self.screen_w, self.screen_h
        # 标题横幅
        title = pygame.Rect(cw // 2 - 160, 50, 320, 80)
        draw_panel(self.screen, title, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=230, radius=16, outline=4)
        draw_text_center(self.screen, "结算", title, color=T.ACCENT_3, font=self.font_big, outline=3)
        e = self.engine
        run_score = e.context.run_score
        stage = e.context.stage_index
        kills = e.context.kills_run
        cards = e.context.cards_run
        achieved = len([1 for v in e.ach_sys.unlocked.values()])
        rows = [
            ("总分", f"{run_score}", T.ACCENT_3),
            ("本局击杀", f"{kills}", T.ENEMY_ELITE),
            ("本局卡数", f"{cards}", T.CARD_SILVER),
            ("已解锁成就", f"{achieved}/24", T.ENEMY_SUPER),
            ("随机种子", f"{e.seed}", T.TEXT_DIM),
            ("版本配置", f"{e.context.app_version} · {e.context.config_version}", T.TEXT_DIM),
        ]
        # 数字面板
        panel = pygame.Rect(cw // 2 - 260, 160, 520, 36 * len(rows) + 24)
        draw_panel(self.screen, panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=200, radius=14, outline=3)
        for i, (k, v, col) in enumerate(rows):
            draw_text(self.screen, f"{k}:", (panel.x + 24, panel.y + 14 + i * 36), size=22, color=T.TEXT_PRIMARY, font=self.font, outline=1)
            draw_text(self.screen, v, (panel.x + 240, panel.y + 14 + i * 36), size=22, color=col, font=self.font, outline=1)
        # 按钮
        accents = [T.ACCENT, T.ACCENT_2, T.ACCENT_3]
        for i, label in enumerate(["使用同预设重开", "选择预设", "返回主菜单"]):
            btn = pygame.Rect(cw // 2 - 200, ch - 360 + i * 80, 400, 68)
            draw_button(self.screen, btn, label, font=self.font_mid, active=(i == self.selection_state["result"]), accent=accents[i])

    def _render_pause_overlay(self) -> None:
        sw, sh = self.screen_w, self.screen_h
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        self.screen.blit(overlay, (0, 0))
        layout = self._build_pause_layout(sw, sh)
        draw_panel(self.screen, layout["panel"], border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=235, radius=20, outline=4)
        draw_text_center(self.screen, "已暂停", layout["title"], color=T.ACCENT, font=self.font_big, outline=3)
        # 操作提示
        draw_text_center(
            self.screen, "↑/↓ 切换 · Enter 确认 · Esc 继续",
            pygame.Rect(layout["panel"].x, layout["title"].bottom + 4, layout["panel"].w, 24),
            color=T.TEXT_DIM, font=self.font_small, outline=1,
        )
        labels = ["继续", "重开当前", "返回主菜单"]
        accents = [T.ACCENT, T.CARD_GOLD, T.DANGER]
        for i, btn in enumerate(layout["buttons"]):
            draw_button(self.screen, btn, labels[i], font=self.font_mid,
                        active=(i == self.selection_state.get("pause", 0)),
                        accent=accents[i])
        # 额外状态：死亡 0.65s 期间显示"返回主菜单/继续" 同样动作

    def _handle_pause_key(self, key: int) -> bool:
        """暂停状态下的键盘：↑/↓ 切、Enter 确认、Esc 继续。"""
        if not hasattr(self, "_pause_option_count"):
            self._pause_option_count = 3
        idx = self.selection_state.get("pause", 0)
        if key in (pygame.K_w, pygame.K_UP):
            self.selection_state["pause"] = (idx - 1) % self._pause_option_count
            return True
        if key in (pygame.K_s, pygame.K_DOWN):
            self.selection_state["pause"] = (idx + 1) % self._pause_option_count
            return True
        if key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self._execute_pause_option(self.selection_state.get("pause", 0))
            return True
        if key == pygame.K_ESCAPE:
            self._execute_pause_option(0)  # Esc 视作"继续"
            return True
        return False

    def _execute_pause_option(self, idx: int) -> None:
        """执行暂停选项。0=继续；1=重开当前；2=返回主菜单。"""
        if idx == 0:
            self.keyboard.request_resume() if hasattr(self.keyboard, "request_resume") else None
            # 简单做法：让 pause 倒计时归零、状态切回 RUNNING
            self.engine._pause_left = 0.0
            self.engine.state_machine.request("RUNNING")
        elif idx == 1:
            # 重开当前局：调用 _start_run 重新开始
            try:
                if hasattr(self.engine, "_start_run"):
                    self.engine._start_run()
                elif hasattr(self.engine, "start_run"):
                    self.engine.start_run()
            except Exception:
                pass
            self.selection_state["pause"] = 0
        elif idx == 2:
            # 返回主菜单：状态切回 MAIN_MENU；保留账号与金币
            self.selection_state["pause"] = 0
            self.selection_state["main"] = 0
            try:
                if hasattr(self.engine, "submit_state_change_to_main_menu"):
                    self.engine.submit_state_change_to_main_menu()
            except Exception:
                pass

    def _render_card_select(self) -> None:
        offer = self.engine._card_offer_now
        if offer is None:
            return
        sw, sh = self.screen_w, self.screen_h
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((*T.BG_WORLD_VEIL, 200))
        self.screen.blit(overlay, (0, 0))
        # 顶部标题（描黑大字）
        title_rect = pygame.Rect(sw // 2 - 280, 50, 560, 80)
        draw_panel(self.screen, title_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=220, radius=18, outline=4)
        draw_text_center(self.screen, "选择一张卡", title_rect, color=T.ACCENT, font=self.font_big, outline=3)
        draw_text_center(self.screen, "按 1 / 2 / 3 选择，R 刷新一次", pygame.Rect(sw // 2 - 240, 138, 480, 30), color=T.TEXT_DIM, font=self.font_small, outline=1)
        for i, card in enumerate(offer.cards):
            rect = pygame.Rect(sw // 2 - 380 + i * 260, sh - 360, 240, 320)
            color = rarity_color(card.rarity_zh)
            if i == self.selection_state["card"]:
                color = T.ACCENT
            # 底层辉光
            glow = make_glow(96, color, 55)
            self.screen.blit(glow, glow.get_rect(center=rect.center))
            # 卡牌本体：元气骑士风（粗黑描边 + 高饱和）
            draw_panel(self.screen, rect, border=color, fill=T.BG_PANEL, alpha=235, radius=18, outline=4)
            frame = self._scaled_art(self.card_frame_sources.get(card.rarity_zh), ("card", card.rarity_zh), (rect.w, rect.h))
            if frame is not None:
                self.screen.blit(frame, rect)
            # 内部高光
            pygame.draw.rect(self.screen, (*color, 64), rect.inflate(-18, -18), border_radius=12, width=2)
            # 顶部稀有度条
            tier_band = pygame.Rect(rect.x + 6, rect.y + 6, rect.w - 12, 28)
            pygame.draw.rect(self.screen, COL_HUD_BORDER, tier_band, border_radius=8)
            pygame.draw.rect(self.screen, color, tier_band.inflate(-4, -4), border_radius=6)
            draw_text_center(self.screen, card.rarity_zh, tier_band, color=T.TEXT_DARK, font=self.font_small, outline=1)
            # 圆形图标槽
            icon_center = (rect.centerx, rect.y + 110)
            pygame.draw.circle(self.screen, COL_HUD_BORDER, icon_center, 42)
            pygame.draw.circle(self.screen, color, icon_center, 38, width=3)
            pygame.draw.circle(self.screen, (*color, 80), icon_center, 30)
            draw_text_center(self.screen, str(i + 1), pygame.Rect(icon_center[0] - 22, icon_center[1] - 22, 44, 44), color=T.TEXT_PRIMARY, font=self.font_mid, outline=2)
            # 标题（描黑）
            draw_text(self.screen, card.name_zh, (rect.x + 14, rect.y + 48), size=22, color=T.TEXT_PRIMARY, font=self.font, outline=2)
            # 描述
            desc_text = self._describe_card(card)
            self._draw_wrapped_text(desc_text, rect.x + 18, rect.y + 168, rect.w - 36, font=self.font_small, line_h=24)
        # 刷新按钮（元气骑士风）
        refresh = pygame.Rect(sw - 296, sh - 200, 256, 64)
        draw_button(self.screen, refresh, "刷新 0/1" if offer.refreshed else "刷新 1/1", font=self.font, active=not offer.refreshed, accent=T.ACCENT_2)
        draw_text_center(self.screen, "左右选择 · 确认获取 · 刷新键重抽", pygame.Rect(sw // 2 - 260, sh - 34, 520, 24), color=T.TEXT_DIM, font=self.font_small, outline=1)

    def _render_level_up(self) -> None:
        sw, sh = self.screen_w, self.screen_h
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((*T.BG_WORLD_VEIL, 200))
        self.screen.blit(overlay, (0, 0))
        # 元气骑士风升级横幅
        title_rect = pygame.Rect(sw // 2 - 200, 50, 400, 80)
        draw_panel(self.screen, title_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=230, radius=18, outline=4)
        draw_text_center(self.screen, "升级！", title_rect, color=T.XP_FILL, font=self.font_big, outline=3)
        draw_text_center(self.screen, "选择一项成长", pygame.Rect(sw // 2 - 200, 140, 400, 28), color=T.TEXT_DIM, font=self.font_small, outline=1)
        offers = self.engine._level_offer_now or []
        for i, e in enumerate(offers):
            rect = pygame.Rect(sw // 2 - 380 + i * 260, sh - 360, 240, 320)
            draw_panel(self.screen, rect, border=T.ACCENT if i == self.selection_state["level"] else T.XP_FILL, fill=T.BG_PANEL, alpha=235, radius=18, outline=4)
            # 内部高光
            pygame.draw.rect(self.screen, (*T.XP_FILL, 50), rect.inflate(-16, -16), border_radius=12, width=2)
            # 圆形图标
            icon_center = (rect.centerx, rect.y + 110)
            pygame.draw.circle(self.screen, COL_HUD_BORDER, icon_center, 42)
            pygame.draw.circle(self.screen, T.XP_FILL, icon_center, 38, width=3)
            pygame.draw.circle(self.screen, (*T.XP_FILL, 80), icon_center, 30)
            draw_text_center(self.screen, str(i + 1), pygame.Rect(icon_center[0] - 22, icon_center[1] - 22, 44, 44), color=T.TEXT_PRIMARY, font=self.font_mid, outline=2)
            draw_text_center(self.screen, e["name_zh"], pygame.Rect(rect.x + 14, rect.y + 168, rect.w - 28, 70), color=T.TEXT_PRIMARY, font=self.font, outline=1)

    def _render_super_warning(self) -> None:
        sw, sh = self.screen_w, self.screen_h
        # 红边 + 顶部红色横幅（元气骑士风：粗黑描边）
        pygame.draw.rect(self.screen, COL_HUD_BORDER, self.world_rect, width=8)
        pygame.draw.rect(self.screen, T.DANGER, self.world_rect, width=4)
        # 顶部警告条
        warn = pygame.Rect(self.world_rect.centerx - 280, self.world_rect.y + 60, 560, 100)
        draw_panel(self.screen, warn, border=COL_HUD_BORDER, fill=T.DANGER_BG, alpha=230, radius=20, outline=5)
        draw_text_center(self.screen, "超级首领来袭！", warn, color=T.TEXT_PRIMARY, font=self.font_big, outline=3)
        # 副标题
        se = self.engine.super_director.active
        if se is None and self.engine.super_director.warning_left > 0:
            sub_rect = pygame.Rect(self.world_rect.centerx - 220, self.world_rect.y + 180, 440, 56)
            draw_panel(self.screen, sub_rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=220, radius=12, outline=3)
            draw_text_center(self.screen, "准备应对 5 种技能...", sub_rect, color=T.DANGER, font=self.font_mid, outline=2)

    def _render_stage_clear(self) -> None:
        sw, sh = self.screen_w, self.screen_h
        layout = self._stage_clear_layout(sw, sh)
        # P3：黑底几乎全屏（alpha=240）
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, layout["veil_alpha"]))
        self.screen.blit(overlay, (0, 0))
        # 顶部金色横条（8px 高，提示关卡节点）
        gold_bar = pygame.Rect(0, 0, sw, layout["gold_bar_h"])
        pygame.draw.rect(self.screen, T.CARD_GOLD, gold_bar)
        # 元气骑士风：金边大横幅
        rect = pygame.Rect(sw // 2 - layout["panel_w"] // 2, sh // 2 - layout["panel_h"] // 2,
                            layout["panel_w"], layout["panel_h"])
        draw_panel(self.screen, rect, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=235, radius=20, outline=5)
        # 中央大标题（96px，比原来 48 大一倍）
        title_size = layout["title_size"]
        title_rect = pygame.Rect(rect.x, rect.y + 16, rect.w, title_size + 20)
        # 动态创建大字体（font_big 是 48；用 font.SysFont 重新申请）
        big_font = pygame.font.SysFont("microsoftyaheiui", title_size, bold=False)
        draw_text_center(self.screen, f"第 {self.engine.context.stage_index} 关 通关！", title_rect,
                         color=T.CARD_GOLD, font=big_font, outline=4)
        rows = [
            ("用时", fmt_time(self.engine.timer.stage_time)),
            ("关卡分", f"{self.engine.context.stage_score}"),
            ("总分", f"{self.engine.context.run_score}"),
            ("恢复生命", "+35%"),
        ]
        for i, (k, v) in enumerate(rows):
            draw_text(self.screen, f"{k}: {v}", (rect.x + 60, rect.y + 140 + i * 42), size=24, color=T.TEXT_PRIMARY, font=self.font, outline=1)
        # 按钮
        btn = pygame.Rect(sw // 2 - 150, sh - 200, 300, 64)
        draw_button(self.screen, btn, "进入下一关", font=self.font_mid, active=True, accent=T.ACCENT)

    def _render_achievement_notice(self) -> None:
        if not self.engine.ach_sys.notifications:
            return
        n = self.engine.ach_sys.notifications[0]
        sw = self.screen_w
        rect = pygame.Rect(sw // 2 - 260, self.world_rect.y + 120, 520, 64)
        # P7：徽章环（进度环）
        badge = self._achievement_badge(
            list(self.engine.ach_sys.achievements.keys()),
            self.engine.ach_sys.unlocked,
            (rect.x - 40, rect.y + 32), 22,
        )
        if badge["total"] > 0:
            pygame.draw.circle(self.screen, COL_HUD_BORDER, badge["center"], badge["radius"] + 2)
            pygame.draw.circle(self.screen, T.CARD_GOLD, badge["center"], badge["radius"], width=badge["ring_thickness"])
            draw_text_center(self.screen, str(badge["unlocked_count"]),
                             pygame.Rect(badge["center"][0] - 16, badge["center"][1] - 16, 32, 32),
                             size=14, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        # 元气骑士风：金色 + 黑色描边
        pygame.draw.rect(self.screen, COL_HUD_BORDER, rect, border_radius=12)
        pygame.draw.rect(self.screen, T.CARD_GOLD, rect.inflate(-4, -4), border_radius=10)
        # 高光
        pygame.draw.rect(self.screen, (*T.TEXT_PRIMARY, 64), rect.inflate(-14, -14), border_radius=8, width=2)
        cfg = self.engine.bundle.achievements.get(n["achievement_id"], {})
        text = f"成就解锁: {cfg.get('name_zh', n['achievement_id'])}"
        self.last_ach_text = text
        draw_text(self.screen, text, (rect.x + 18, rect.y + 18), size=20, color=T.TEXT_DARK, font=self.font, outline=1)

    def _render_login_overlay(self) -> None:
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 190))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(self.screen_w // 2 - 330, self.screen_h // 2 - 230, 660, 460)
        draw_panel(self.screen, panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=242, radius=18, outline=4)
        draw_text_center(self.screen, "账号登录", pygame.Rect(panel.x, panel.y + 24, panel.w, 56), color=T.ACCENT, font=self.font_big, outline=3)
        draw_text_center(self.screen, "上下选择账号 · 确认进入 · 选择新建后输入名称", pygame.Rect(panel.x, panel.y + 90, panel.w, 26), color=T.TEXT_DIM, font=self.font_small, outline=1)
        box = pygame.Rect(panel.x + 90, panel.y + 142, panel.w - 180, 58)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, box, border_radius=10)
        pygame.draw.rect(self.screen, T.BG_PANEL_ALT, box.inflate(-4, -4), border_radius=8)
        input_color = T.TEXT_PRIMARY if self.login_typing_new else T.TEXT_DIM
        input_text = self.account_input or ("输入新账号名" if self.login_typing_new else "default")
        draw_text(self.screen, input_text, (box.x + 18, box.y + 16), size=24, color=input_color, font=self.font, outline=1)
        if self.login_typing_new:
            cursor_x = box.x + 22 + self.font.size(self.account_input)[0]
            if int(time.time() * 2) % 2 == 0:
                pygame.draw.line(self.screen, T.ACCENT, (cursor_x, box.y + 14), (cursor_x, box.bottom - 14), 2)
        draw_text(self.screen, "账号选择", (panel.x + 90, panel.y + 204), size=16, color=T.TEXT_DIM, font=self.font_small, outline=1)
        options = self._login_options()
        self.login_selected_index = max(0, min(self.login_selected_index, len(options) - 1))
        for i, (kind, label) in enumerate(options):
            row = pygame.Rect(panel.x + 90, panel.y + 226 + i * 40, panel.w - 180, 36)
            active = i == self.login_selected_index
            accent = T.CARD_GOLD if kind == "new" else T.ACCENT_2
            draw_button(self.screen, row, label[:18], font=self.font_small, active=active, accent=accent)
        btn = pygame.Rect(self.screen_w // 2 - 150, panel.bottom - 66, 300, 52)
        btn_label = "创建并进入" if self.login_typing_new and options[self.login_selected_index][0] == "new" else "进入游戏"
        draw_button(self.screen, btn, btn_label, font=self.font_mid, active=True, accent=T.ACCENT)

    def _achievement_color(self, grade: int) -> tuple[int, int, int]:
        return {1: T.CARD_SILVER, 2: T.CARD_GOLD, 3: T.CARD_COLOR}.get(grade, T.CARD_SILVER)

    def _render_achievements_overlay(self) -> None:
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(self.screen_w // 2 - 560, 70, 1120, min(640, self.screen_h - 120))
        draw_panel(self.screen, panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=240, radius=18, outline=4)
        draw_text_center(self.screen, "成就墙", pygame.Rect(panel.x, panel.y + 18, panel.w, 48), color=T.ACCENT_2, font=self.font_big, outline=3)
        close = pygame.Rect(panel.right - 60, panel.y + 18, 42, 42)
        draw_button(self.screen, close, "关", font=self.font, active=True, accent=T.DANGER)
        achievements = list(self.engine.bundle.achievements.items())
        unlocked = self.engine.ach_sys.unlocked
        self.achievement_selected_index = max(0, min(self.achievement_selected_index, max(0, len(achievements) - 1)))
        draw_text(self.screen, f"已完成 {len(unlocked)}/{len(achievements)}", (panel.x + 34, panel.y + 76), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        draw_text(self.screen, "W/A/S/D选择 · Esc关闭", (panel.right - 230, panel.y + 78), size=15, color=T.TEXT_DIM, font=self.font_small, outline=1)
        for i, (aid, cfg) in enumerate(achievements[:24]):
            col = i % 3
            row = i // 3
            rect = pygame.Rect(panel.x + 34 + col * 350, panel.y + 108 + row * 58, 326, 48)
            done = aid in unlocked
            color = self._achievement_color(int(cfg.get("grade", 1)))
            focused = i == self.achievement_selected_index
            draw_panel(self.screen, rect, border=T.ACCENT if focused else (color if done else COL_HUD_BORDER), fill=T.BG_PANEL_ALT, alpha=225 if done else 145, radius=10, outline=2)
            draw_text(self.screen, "✓" if done else "·", (rect.x + 12, rect.y + 12), size=18, color=color, font=self.font_small, outline=1)
            draw_text(self.screen, cfg.get("name_zh", aid), (rect.x + 42, rect.y + 7), size=16, color=T.TEXT_PRIMARY if done else T.TEXT_DIM, font=self.font_small, outline=1)
            draw_text(self.screen, cfg.get("tier_zh", ""), (rect.right - 54, rect.y + 7), size=14, color=color, font=self.font_small, outline=1)
            threshold = cfg.get("value", cfg.get("threshold", ""))
            draw_text(self.screen, f"目标 {threshold}", (rect.x + 42, rect.y + 27), size=13, color=T.TEXT_DIM, font=self.font_small, outline=1)
        if achievements:
            aid, cfg = achievements[self.achievement_selected_index]
            detail = pygame.Rect(panel.x + 34, panel.bottom - 74, panel.w - 68, 50)
            done = aid in unlocked
            draw_panel(self.screen, detail, border=T.ACCENT if done else COL_HUD_BORDER, fill=T.BG_PANEL_ALT, alpha=220, radius=10, outline=2)
            status = "已完成" if done else "未完成"
            threshold = cfg.get("value", cfg.get("threshold", ""))
            draw_text(self.screen, f"{cfg.get('name_zh', aid)} · {status}", (detail.x + 16, detail.y + 8), size=17, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            draw_text(self.screen, f"{cfg.get('description_zh', '')}  目标：{threshold}", (detail.x + 16, detail.y + 30), size=14, color=T.TEXT_DIM, font=self.font_small, outline=1)

    def _shop_item_owned(self, item_id: str, item: dict) -> bool:
        if "weapon_id" in item:
            return item["weapon_id"] in self.engine.unlocked_weapon_ids()
        if "equipment_id" in item:
            return item["equipment_id"] in self.engine.account_equipment_pool()
        if "upgrade" in item:
            return self.engine.permanent_upgrade_level(item["upgrade"]) >= int(item.get("max_level", 1))
        return False

    def _render_shop_overlay(self) -> None:
        overlay = pygame.Surface((self.screen_w, self.screen_h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(self.screen_w // 2 - 560, 70, 1120, min(640, self.screen_h - 120))
        draw_panel(self.screen, panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=242, radius=18, outline=4)
        close = pygame.Rect(panel.right - 60, panel.y + 18, 42, 42)
        draw_button(self.screen, close, "关", font=self.font, active=True, accent=T.DANGER)
        draw_text_center(self.screen, "账号商店", pygame.Rect(panel.x, panel.y + 18, panel.w, 48), color=T.CARD_GOLD, font=self.font_big, outline=3)
        draw_text(self.screen, f"账号金币：{self.engine.gold()}", (panel.x + 34, panel.y + 76), size=20, color=T.CARD_GOLD, font=self.font, outline=1)
        draw_text(self.screen, "A/D分类 · W/S选择 · Enter购买 · Esc关闭", (panel.x + 250, panel.y + 80), size=15, color=T.TEXT_DIM, font=self.font_small, outline=1)
        categories = self._shop_categories()
        tab_y = panel.y + 108
        for i, (_key, label) in enumerate(categories):
            tab = pygame.Rect(panel.x + 34 + i * 116, tab_y, 104, 38)
            draw_button(
                self.screen, tab, label, font=self.font_small,
                active=i == self.shop_category_index % len(categories),
                accent=(T.CARD_GOLD if i == 1 else T.ACCENT_2 if i == 2 else T.ACCENT),
            )
        entries = self._shop_entries()
        self.shop_selected_index = max(0, min(self.shop_selected_index, max(0, len(entries) - 1)))
        # P9：搜索框
        search_box = pygame.Rect(panel.x + 34 + 4 * 116, panel.y + 108, 200, 38)
        search_text = getattr(self, "_shop_search_input", "")
        pygame.draw.rect(self.screen, T.BG_PANEL_ALT, search_box, border_radius=8)
        pygame.draw.rect(self.screen, COL_HUD_BORDER, search_box, width=2, border_radius=8)
        if search_text:
            draw_text(self.screen, f"🔍 {search_text}", (search_box.x + 8, search_box.y + 6), size=14,
                      color=T.ACCENT, font=self.font_small, outline=1)
        else:
            draw_text(self.screen, "🔍 搜索...", (search_box.x + 8, search_box.y + 6), size=14,
                      color=T.TEXT_DIM, font=self.font_small, outline=1)
        first = self._shop_page_start(len(entries), visible_count=5)
        visible = entries[first:first + 5]
        draw_text(self.screen, f"{self.shop_selected_index + 1}/{len(entries)}", (panel.right - 330, panel.y + 80), size=15, color=T.TEXT_DIM, font=self.font_small, outline=1)
        list_panel = pygame.Rect(panel.x + 30, panel.y + 158, 540, 382)
        draw_panel(self.screen, list_panel, border=COL_HUD_BORDER, fill=T.BG_PANEL_ALT, alpha=178, radius=12, outline=3)
        for offset, (item_id, item) in enumerate(visible):
            i = first + offset
            y = list_panel.y + 16 + offset * 70
            row = pygame.Rect(list_panel.x + 14, y, list_panel.w - 28, 60)
            owned = self._shop_item_owned(item_id, item)
            active = i == self.shop_selected_index
            draw_panel(self.screen, row, border=T.ACCENT if active else COL_HUD_BORDER, fill=T.BG_PANEL_ALT, alpha=220, radius=10, outline=2)
            icon_rect = pygame.Rect(row.x + 12, row.y + 8, 44, 44)
            pygame.draw.rect(self.screen, COL_HUD_BORDER, icon_rect, border_radius=8)
            pygame.draw.rect(self.screen, T.BG_PANEL, icon_rect.inflate(-4, -4), border_radius=6)
            if "weapon_id" in item:
                icon = self._scaled_art(self.weapon_icon_sources.get(item["weapon_id"]), ("shop_weapon", item["weapon_id"]), (38, 38))
                if icon is not None:
                    self.screen.blit(icon, icon.get_rect(center=icon_rect.center))
                else:
                    draw_text_center(self.screen, "武", icon_rect, color=T.CARD_GOLD, font=self.font_small, outline=1)
            elif "equipment_id" in item:
                icon = self._scaled_art(self.equipment_icon_sources.get(item["equipment_id"]), ("shop_equipment", item["equipment_id"]), (38, 38))
                if icon is not None:
                    self.screen.blit(icon, icon.get_rect(center=icon_rect.center))
                else:
                    draw_text_center(self.screen, "装", icon_rect, color=T.ACCENT_2, font=self.font_small, outline=1)
            else:
                draw_text_center(self.screen, "强", icon_rect, color=T.ACCENT, font=self.font_small, outline=1)
            draw_text(self.screen, item["name"], (row.x + 68, row.y + 9), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            if "upgrade" in item:
                lvl = self.engine.permanent_upgrade_level(item["upgrade"])
                detail = f"等级 {lvl}/{item.get('max_level', 1)}"
            elif "equipment_id" in item:
                detail = EQUIPMENT_ITEMS.get(item["equipment_id"], {}).get("desc", "永久装备")
            else:
                cfg = self.engine.bundle.weapons.get(item["weapon_id"], {})
                detail = f"伤害 {cfg.get('base_damage', '-')} · 间隔 {cfg.get('attack_interval', '-')}"
            draw_text(self.screen, detail, (row.x + 68, row.y + 34), size=14, color=T.TEXT_DIM, font=self.font_small, outline=1)
            tag = pygame.Rect(row.right - 98, row.y + 13, 82, 34)
            label = "已拥有" if owned else f"{item['cost']} 金"
            affordable = self.engine.gold() >= int(item["cost"]) and not owned
            draw_button(self.screen, tag, label, font=self.font_small, active=affordable, accent=T.CARD_GOLD if affordable else T.TEXT_DIM)
        detail_panel = pygame.Rect(panel.x + 590, panel.y + 158, panel.w - 620, 260)
        draw_panel(self.screen, detail_panel, border=T.ACCENT_2, fill=T.BG_PANEL_ALT, alpha=222, radius=12, outline=3)
        if entries:
            item_id, item = entries[self.shop_selected_index]
            owned = self._shop_item_owned(item_id, item)
            affordable = self.engine.gold() >= int(item["cost"]) and not owned
            title_color = T.CARD_GOLD if "weapon_id" in item else T.ACCENT_2 if "equipment_id" in item else T.ACCENT
            draw_text(self.screen, item["name"], (detail_panel.x + 22, detail_panel.y + 18), size=24, color=title_color, font=self.font, outline=2)
            if "weapon_id" in item:
                wid = item["weapon_id"]
                cfg = self.engine.bundle.weapons.get(wid, {})
                icon = self._scaled_art(self.weapon_icon_sources.get(wid), ("shop_detail_weapon", wid), (92, 92))
                icon_box = pygame.Rect(detail_panel.x + 24, detail_panel.y + 66, 104, 104)
                pygame.draw.rect(self.screen, COL_HUD_BORDER, icon_box, border_radius=12)
                pygame.draw.rect(self.screen, T.BG_PANEL, icon_box.inflate(-5, -5), border_radius=10)
                if icon is not None:
                    self.screen.blit(icon, icon.get_rect(center=icon_box.center))
                else:
                    draw_text_center(self.screen, "武器", icon_box, color=T.CARD_GOLD, font=self.font, outline=2)
                rows = [
                    f"类型：{cfg.get('archetype', '-')}",
                    f"伤害：{cfg.get('base_damage', '-')}    攻速间隔：{cfg.get('attack_interval', '-')}",
                    f"射程：{cfg.get('attack_range', '-')}    穿透：{cfg.get('penetration', '-')}",
                    f"暴击：{int(float(cfg.get('crit_chance', 0))*100)}% / x{cfg.get('crit_multiplier', '-')}",
                ]
                for i, text in enumerate(rows):
                    draw_text(self.screen, text, (detail_panel.x + 150, detail_panel.y + 72 + i * 28), size=16, color=T.TEXT_PRIMARY if i == 0 else T.TEXT_DIM, font=self.font_small, outline=1)
                desc = self._weapon_shop_desc(wid)
            elif "equipment_id" in item:
                eid = item["equipment_id"]
                cfg = EQUIPMENT_ITEMS.get(eid, {})
                desc = cfg.get("desc", "永久装备")
                draw_text(self.screen, desc, (detail_panel.x + 24, detail_panel.y + 74), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            else:
                lvl = self.engine.permanent_upgrade_level(item["upgrade"])
                desc = f"当前等级 {lvl}/{item.get('max_level', 1)}，购买后永久提高账号基础能力。"
                draw_text(self.screen, desc, (detail_panel.x + 24, detail_panel.y + 74), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            self._draw_wrapped_text(desc, detail_panel.x + 24, detail_panel.y + 184, detail_panel.w - 48, font=self.font_small, line_h=22)
            buy = pygame.Rect(detail_panel.right - 188, detail_panel.bottom - 58, 160, 44)
            label = "已拥有" if owned else ("金币不足" if not affordable else f"购买 {item['cost']}")
            draw_button(self.screen, buy, label, font=self.font_small, active=affordable, accent=T.CARD_GOLD if affordable else T.TEXT_DIM)
        owned_panel = pygame.Rect(panel.x + 590, panel.y + 434, panel.w - 620, 106)
        draw_panel(self.screen, owned_panel, border=T.ACCENT, fill=T.BG_PANEL_ALT, alpha=205, radius=12, outline=3)
        draw_text(self.screen, "已拥有", (owned_panel.x + 18, owned_panel.y + 12), size=20, color=T.ACCENT, font=self.font, outline=2)
        weapon_ids = self.engine.unlocked_weapon_ids()
        equipment_ids = self.engine.unlocked_equipment_ids()
        if not weapon_ids and not equipment_ids:
            draw_text(self.screen, "购买后会进入开局配置池。", (owned_panel.x + 18, owned_panel.y + 52), size=16, color=T.TEXT_DIM, font=self.font_small, outline=1)
        owned_names = [f"武器:{zh_weapon_name(wid, wid)}" for wid in weapon_ids[:6]]
        owned_names += [f"装备:{EQUIPMENT_ITEMS.get(eid, {}).get('name', eid)}" for eid in equipment_ids[:4]]
        for i, text in enumerate(owned_names[:10]):
            x = owned_panel.x + 18 + (i % 2) * 235
            y = owned_panel.y + 44 + (i // 2) * 23
            draw_text(self.screen, text, (x, y), size=14, color=T.TEXT_PRIMARY if text.startswith("武器") else T.CARD_GOLD, font=self.font_small, outline=1)

    def _weapon_shop_desc(self, weapon_id: str) -> str:
        return {
            "w_thunder_daggers": "高攻速近战武器，适合贴身连续切入，暴击频率高。",
            "w_frost_lance": "长距离近战武器，攻击面窄但距离很安全。",
            "w_flame_handcannon": "慢速高伤炮击，单发爆发强，适合点杀精英。",
            "w_starfall_bow": "三连发远程武器，覆盖稳定，适合清理中距离敌群。",
            "w_venom_knife": "短距离快节奏匕首，暴击高，适合灵活走位。",
            "w_magnetic_ringblade": "回旋弹体会多段穿透和反弹，适合复杂场面。",
            "w_holy_scepter": "中等伤害的穿透光束，手感稳定，容错较高。",
            "w_blood_scythe": "大范围镰刀，节奏较慢但单次清场能力强。",
            "w_void_pistols": "极快双枪，低单发高频率，适合叠加攻击特效。",
            "w_rockfall_hammer": "重型圆形震荡近战，慢但范围和打断感都强。",
            "w_wind_tachi": "均衡近战太刀，范围、攻速和暴击都偏灵活。",
            "w_thunder_array": "四发雷系阵盘弹，能反弹，适合和四雷技能走同一套视觉流派。",
        }.get(weapon_id, "永久解锁后可以在开局配置里选择。")

    def _render_history_overlay(self) -> None:
        sw, sh = self.screen_w, self.screen_h
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 165))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(sw // 2 - 520, 92, 1040, min(600, sh - 140))
        draw_panel(self.screen, panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=238, radius=18, outline=4)
        draw_text_center(self.screen, "游戏日志", pygame.Rect(panel.x, panel.y + 18, panel.w, 48), color=T.ACCENT, font=self.font_big, outline=3)
        close = pygame.Rect(panel.right - 60, panel.y + 18, 42, 42)
        draw_button(self.screen, close, "关", font=self.font, active=True, accent=T.DANGER)
        runs = list(getattr(self.engine.profile, "recent_runs_summary", []) or [])
        if not runs:
            draw_text_center(self.screen, "还没有记录，打一局后这里会保存结果。", pygame.Rect(panel.x + 40, panel.y + 170, panel.w - 80, 40), color=T.TEXT_DIM, font=self.font, outline=1)
            return
        self.history_selected_index = max(0, min(self.history_selected_index, len(runs[:30]) - 1))
        first = self._history_page_start(runs)
        visible = runs[first:first + 6]
        draw_text(self.screen, f"最近 30 局  {self.history_selected_index + 1}/{min(30, len(runs))}", (panel.x + 34, panel.y + 76), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        for offset, run in enumerate(visible):
            i = first + offset
            y = panel.y + 96 + offset * 78
            row = pygame.Rect(panel.x + 28, y, 420, 66)
            draw_panel(self.screen, row, border=T.ACCENT if i == self.history_selected_index else COL_HUD_BORDER, fill=T.BG_PANEL_ALT, alpha=210, radius=10, outline=2)
            result = "胜利" if run.get("result") == "victory" else "阵亡"
            title = f"{i + 1}. {result} · {run.get('preset', '-')} · {run.get('skill', '-')}"
            draw_text(self.screen, title, (row.x + 14, row.y + 8), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            detail = (
                f"击杀 {run.get('kills', 0)}  分数 {run.get('score', 0)}  "
                f"时间 {fmt_time(float(run.get('duration', 0)))}"
            )
            draw_text(self.screen, detail, (row.x + 14, row.y + 34), size=16, color=T.TEXT_DIM, font=self.font_small, outline=1)
        self._render_history_detail(panel, runs[self.history_selected_index])

    def _history_page_start(self, runs: list[dict]) -> int:
        count = min(30, len(runs))
        if count <= 6:
            return 0
        return max(0, min(self.history_selected_index - 2, count - 6))

    def _render_history_preview(self) -> None:
        runs = list(getattr(self.engine.profile, "recent_runs_summary", []) or [])
        sw, sh = self.screen_w, self.screen_h
        panel = pygame.Rect(sw - 360, 340, 320, 232)
        draw_panel(self.screen, panel, border=COL_HUD_BORDER, fill=T.BG_PANEL, alpha=205, radius=14, outline=3)
        draw_text(self.screen, "游戏日志", (panel.x + 18, panel.y + 14), size=20, color=T.ACCENT, font=self.font, outline=2)
        draw_text(self.screen, "按 L 或选择历史记录查看", (panel.x + 18, panel.y + 42), size=14, color=T.TEXT_DIM, font=self.font_small, outline=1)
        if not runs:
            draw_text(self.screen, "暂无记录", (panel.x + 18, panel.y + 90), size=16, color=T.TEXT_DIM, font=self.font_small, outline=1)
            return
        for i, run in enumerate(runs[:3]):
            y = panel.y + 76 + i * 46
            result = "胜利" if run.get("result") == "victory" else "阵亡"
            draw_text(self.screen, f"{i + 1}. {result}  {run.get('score', 0)}分", (panel.x + 18, y), size=15, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
            draw_text(self.screen, f"击杀 {run.get('kills', 0)}  {fmt_time(float(run.get('duration', 0)))}", (panel.x + 18, y + 20), size=13, color=T.TEXT_DIM, font=self.font_small, outline=1)

    def _render_history_detail(self, panel: pygame.Rect, run: dict) -> None:
        detail = pygame.Rect(panel.x + 478, panel.y + 96, panel.w - 506, panel.h - 126)
        draw_panel(self.screen, detail, border=T.ACCENT_2, fill=T.BG_PANEL_ALT, alpha=218, radius=12, outline=3)
        result = "胜利" if run.get("result") == "victory" else "阵亡"
        draw_text(self.screen, result, (detail.x + 24, detail.y + 18), size=28, color=T.ACCENT_3 if result == "胜利" else T.DANGER, font=self.font_mid, outline=2)
        rows = [
            ("开局武器", run.get("preset", "-")),
            ("技能", run.get("skill", "-")),
            ("装备", ", ".join(EQUIPMENT_ITEMS.get(e, {}).get("name", e) for e in run.get("equipment", []) or []) or "-"),
            ("击杀小怪", run.get("kills", 0)),
            ("获得分数", run.get("score", 0)),
            ("坚持时间", fmt_time(float(run.get("duration", 0)))),
            ("抽卡次数", run.get("cards", 0)),
            ("击杀首领", run.get("super_kills", 0)),
            ("技能释放", run.get("skill_uses", 0)),
        ]
        for i, (k, v) in enumerate(rows):
            y = detail.y + 70 + i * 34
            draw_text(self.screen, f"{k}", (detail.x + 24, y), size=18, color=T.TEXT_DIM, font=self.font_small, outline=1)
            draw_text(self.screen, str(v), (detail.x + 160, y), size=18, color=T.TEXT_PRIMARY, font=self.font_small, outline=1)
        ach = run.get("achievements") or []
        ach_text = ", ".join(map(str, ach[-5:])) if ach else "暂无"
        draw_text(self.screen, "成就", (detail.x + 24, detail.bottom - 56), size=18, color=T.CARD_GOLD, font=self.font_small, outline=1)
        self._draw_wrapped_text(ach_text, detail.x + 82, detail.bottom - 56, detail.w - 110, font=self.font_small, line_h=22)

    # ------------------------------------------------------------------
    def _describe_card(self, card) -> str:
        if isinstance(card, dict):
            return card.get("name_zh", "")
        cfg = self.engine.bundle.cards.get(card.card_id, {})
        if cfg.get("description_zh"):
            return cfg["description_zh"]
        # 简化：用 effect 类型描述
        effs = cfg.get("effects", [])
        lines = []
        for eff in effs:
            t = eff.get("type", "")
            v = eff.get("value", 0)
            mapping = {
                "dmg_pct": f"伤害 +{int(v*100)}%",
                "aspd_pct": f"攻速 +{int(v*100)}%",
                "range_pct": f"射程 +{int(v*100)}%",
                "arc_deg": f"弧度 +{int(v)}°",
                "tol_deg": f"容差 +{int(v)}°",
                "max_hp_flat": f"最大生命 +{int(v)}",
                "current_hp_flat": f"立即恢复 {int(v)} 生命",
                "shield_flat": f"护盾 +{int(v)}",
                "pickup_radius_pct": f"拾取范围 +{int(v*100)}%",
                "armor_flat": f"护甲 +{int(v)}",
                "move_speed_pct": f"移速 +{int(v*100)}%",
                "penetration": f"穿透 +{int(v)}",
                "xp_gain_pct": f"经验 +{int(v*100)}%",
                "max_shield_flat": f"护盾上限 +{int(v)}",
                "shield_regen_unlocked": "8 秒未受伤后每秒恢复护盾",
                "low_hp_atk_pct": "低生命时伤害 / 移速加成",
                "low_hp_move_pct": "低生命时伤害 / 移速加成",
                "extra_projectile": "当前武器 +1 投射物",
                "active_weapon_level_up": "激活武器等级 +1",
                "gain_random_weapon": "随机获得一把新武器",
                "gain_weapon": f"获得武器：{zh_weapon_name(eff.get('weapon_id'), '高阶武器')}",
                "prism_flare": "所有投射武器产生额外侧弹",
                "turn_speed_pct": f"转向 +{int(v*100)}%",
                "break_invuln": "破盾获得 1 秒无敌",
                "max_hp_pct": f"最大生命 +{int(v*100)}%",
            }
            lines.append(mapping.get(t, f"({t})"))
        return "\n".join(lines) if lines else card.name_zh

    def _draw_wrapped_text(self, text, x, y, w, *, font=None, line_h=22):
        if font is None:
            font = self.font_small
        words = text.replace("\n", "\n ").split(" ")
        line = ""
        for word in words:
            if word == "\n":
                draw_text(self.screen, line, (x, y), size=16, color=T.TEXT_PRIMARY, font=font, outline=1)
                y += line_h
                line = ""
                continue
            test = (line + " " + word).strip()
            if font.size(test)[0] <= w:
                line = test
            else:
                if line:
                    draw_text(self.screen, line, (x, y), size=16, color=T.TEXT_PRIMARY, font=font, outline=1)
                    y += line_h
                line = word
        if line:
            draw_text(self.screen, line, (x, y), size=16, color=T.TEXT_PRIMARY, font=font, outline=1)
