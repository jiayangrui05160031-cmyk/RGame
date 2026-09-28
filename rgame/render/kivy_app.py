"""Kivy 跨平台渲染与跨设备输入适配。

按《跨平台与手游适配》：

- 1920×1080 逻辑画布，按等比缩放；
- 触屏默认开启；桌面按需通过键盘；
- 引擎逻辑与 pygame 入口完全相同。
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Optional

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.window import Window
from kivy.graphics import Color, Ellipse, Rectangle, Line, PushMatrix, PopMatrix, Rotate
from kivy.input.providers.mouse import MouseMotionEvent
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image as KivyImage
from kivy.uix.label import Label
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.widget import Widget

from ..core.state_machine import (
    BOOT, MAIN_MENU, MODE_SELECT, PRESET_SELECT, RUNNING, PAUSED,
    SUPER_WARNING, LEVEL_UP, CARD_SELECT, STAGE_CLEAR, ENDING, RESULT, ERROR,
)
from ..engine import Engine
from ..player.input_provider import (
    KeyboardInputProvider, TouchInputProvider, CompositeInputProvider,
)
from ..player.movement import PlayableBounds
from ..drops.drops import HazardBomb
from ..enemies.enemies import EnemyState
from ..enemies.super_enemy import SuperSkill


SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080


# ---- 颜色（与 pygame 端保持语义和深空色板一致） ----
COL_BG = (6 / 255, 12 / 255, 26 / 255, 1)
COL_TEXT = (229 / 255, 241 / 255, 255 / 255, 1)
COL_TEXT_DIM = (140 / 255, 163 / 255, 190 / 255, 1)
COL_PLAYER = (55 / 255, 220 / 255, 255 / 255, 1)
COL_PLAYER_CORE = (232 / 255, 251 / 255, 255 / 255, 1)
COL_ENEMY = (246 / 255, 94 / 255, 129 / 255, 1)
COL_ENEMY_ELITE = (255 / 255, 190 / 255, 92 / 255, 1)
COL_ENEMY_SUPER = (195 / 255, 110 / 255, 255 / 255, 1)
COL_PROJECTILE_PLAYER = (85 / 255, 232 / 255, 255 / 255, 1)
COL_PROJECTILE_ENEMY = (255 / 255, 151 / 255, 100 / 255, 1)
COL_PICKUP_XP = (116 / 255, 243 / 255, 202 / 255, 1)
COL_BOMB = (255 / 255, 104 / 255, 135 / 255, 1)
COL_BOMB_DANGER = (255 / 255, 73 / 255, 117 / 255, 1)
COL_HP = (255 / 255, 79 / 255, 115 / 255, 1)
COL_HP_BACK = (68 / 255, 24 / 255, 46 / 255, 1)
COL_SHIELD = (61 / 255, 203 / 255, 255 / 255, 1)
COL_SUPER_BAR = (197 / 255, 132 / 255, 255 / 255, 1)
COL_HUD_BG = (11 / 255, 22 / 255, 40 / 255, 0.88)
COL_HUD_BORDER = (57 / 255, 221 / 255, 255 / 255, 1)
COL_BTN_INACTIVE = (18 / 255, 36 / 255, 58 / 255, 1)
COL_BTN_ACTIVE = (57 / 255, 221 / 255, 255 / 255, 1)
COL_CARD_SILVER = (151 / 255, 207 / 255, 240 / 255, 1)
COL_CARD_GOLD = (255 / 255, 201 / 255, 103 / 255, 1)
COL_CARD_COLOR = (216 / 255, 125 / 255, 255 / 255, 1)


def rarity_color(rarity: str):
    return {
        "银": COL_CARD_SILVER,
        "金": COL_CARD_GOLD,
        "彩": COL_CARD_COLOR,
    }.get(rarity, COL_CARD_SILVER)


# =============================================================================
# 战斗世界画布
# =============================================================================
class WorldCanvas(Widget):
    """承载 1920×1080 战斗画布；将世界坐标按比例缩放并绘制。"""

    def __init__(self, engine: Engine, **kwargs):
        super().__init__(**kwargs)
        self.engine = engine
        self._sprite_textures = {}
        self._sprite_images = []
        self._last_enemy_hp = {}
        self._last_enemy_pos = {}
        self._last_player_hp = engine.player.current_hp
        self._feedback_bursts = []
        self._load_v3_assets()
        self.bind(pos=self.redraw, size=self.redraw)
        self.last_redraw = 0.0

    def _load_v3_assets(self) -> None:
        asset_root = Path(__file__).resolve().parents[1] / "assets" / "v3"
        v4_asset_root = Path(__file__).resolve().parents[1] / "assets" / "v4"
        v5_asset_root = Path(__file__).resolve().parents[1] / "assets" / "v5"

        def load_sheet(relative_path, columns, rows, names, *, root=asset_root):
            path = root / relative_path
            if not path.exists():
                return
            try:
                image = CoreImage(str(path))
                self._sprite_images.append(image)
                texture = image.texture
                cell_w, cell_h = texture.width // columns, texture.height // rows
                for index, name in enumerate(names):
                    row, col = divmod(index, columns)
                    y = texture.height - (row + 1) * cell_h
                    self._sprite_textures[name] = texture.get_region(col * cell_w, y, cell_w, cell_h)
            except Exception:
                return

        def load_single(relative_path, name, *, root=asset_root):
            path = root / relative_path
            if not path.exists():
                return
            try:
                image = CoreImage(str(path))
                self._sprite_images.append(image)
                self._sprite_textures[name] = image.texture
            except Exception:
                return

        load_single("player/player_space_marine.png", "player")
        load_single("boss/boss_void_warden.png", "boss")
        load_sheet("enemies/enemy_roster_sheet.png", 3, 3, (
            "spinner_chaser", "wingblade_sprinter", "shellguard_heavy",
            "lantern_shooter", "crystal_sniper", "multinode_spreader",
            "minelayer_bomber", "mine_leech", "rail_turret",
        ))
        load_sheet("enemies/enemy_specialists_sheet.png", 2, 2, (
            "void_mender", "rift_dancer", "phase_stalker", "prism_artillery",
        ))
        load_sheet("pickups/pickup_roster_sheet.png", 2, 2, (
            "pickup_xp", "pickup_heal", "pickup_shield_restore", "pickup_armor",
        ))
        load_sheet("effects/combat_effect_roster_sheet.png", 2, 2, (
            "impact_spark", "plasma_burst", "plasma_bolt", "energy_slash",
        ))
        load_single("illustrations/main_menu_mars_keyart.png", "menu_illustration", root=v4_asset_root)
        load_sheet("player/player_skin_roster_sheet.png", 2, 2, (
            "player_skin_vanguard", "player_skin_comet", "player_skin_verdant", "player_skin_eclipse",
        ), root=v4_asset_root)
        load_sheet("weapons/weapon_icon_roster_sheet.png", 3, 3, (
            "weapon_w_melee_blade", "weapon_w_rifle_precise", "weapon_w_shotgun_spread",
            "weapon_w_orbiter_omni", "weapon_w_laser_charge", "weapon_w_arcane_orb",
            "weapon_w_frost_lance", "weapon_w_starfall_bow", "weapon_w_void_pistols",
        ), root=v4_asset_root)
        load_sheet("pickups/pickup_roster_sheet.png", 2, 2, (
            "pickup_xp", "pickup_heal", "pickup_shield_restore", "pickup_armor",
        ), root=v4_asset_root)
        load_sheet("pickups/tactical_pickup_roster_sheet.png", 2, 2, (
            "pickup_skill_charge", "pickup_coin", "pickup_temp_buff", "pickup_hazard_bomb",
        ), root=v5_asset_root)
        load_sheet("effects/combat_vfx_roster_sheet.png", 2, 2, (
            "impact_spark", "energy_slash", "plasma_burst", "thunder_explosion",
        ), root=v4_asset_root)

    def redraw(self, *_a) -> None:
        self.canvas.clear()
        with self.canvas:
            Color(*COL_BG)
            Rectangle(pos=self.pos, size=self.size)
            # 边框
            Color(*COL_HUD_BORDER)
            Line(rectangle=(self.x, self.y, self.width, self.height), width=2)
            # 内部世界：使用 engine 的世界坐标按比例缩放
            self._draw_world()

    def _scale(self, x, y):
        """世界坐标 → 屏幕坐标"""
        # 把 1920×1080 适配到 self.width×self.height 内
        sx = self.width / SCREEN_WIDTH
        sy = self.height / SCREEN_HEIGHT
        s = min(sx, sy)
        ox = self.x + (self.width - SCREEN_WIDTH * s) / 2
        oy = self.y + (self.height - SCREEN_HEIGHT * s) / 2
        return (ox + x * s, oy + y * s), s

    def _draw_world(self) -> None:
        e = self.engine
        if e.state() == "MAIN_MENU" and self._sprite_textures.get("menu_illustration") is not None:
            Color(1, 1, 1, 1)
            Rectangle(texture=self._sprite_textures["menu_illustration"], pos=self.pos, size=self.size)
            Color(2 / 255, 8 / 255, 18 / 255, 0.28)
            Rectangle(pos=self.pos, size=self.size)
            return
        if e.state() == "RUNNING" and e.timer.stage_time < 2.0:
            # 出生安全区
            (cx, cy), s = self._scale(960, 540)
            Color(57 / 255, 221 / 255, 255 / 255, 0.65)
            Line(circle=(cx, cy, 220 * s), width=1)
        # 危险炸弹
        for b in e.drop_sys.bombs:
            self._draw_bomb(b)
        # 玩家
        self._draw_player()
        # 敌人
        active_enemy_ids = set()
        for en in e.spawn_director.enemies:
            active_enemy_ids.add(en.entity_id)
            old_hp = self._last_enemy_hp.get(en.entity_id, en.current_hp)
            if en.current_hp < old_hp - 0.01:
                kind = "defeat" if en.current_hp <= 0 else "hit"
                self._feedback_bursts.append({"pos": en.position, "kind": kind, "born": time.monotonic()})
            self._last_enemy_hp[en.entity_id] = en.current_hp
            self._last_enemy_pos[en.entity_id] = en.position
            self._draw_enemy(en)
        for entity_id in list(self._last_enemy_hp):
            if entity_id not in active_enemy_ids:
                if self._last_enemy_hp[entity_id] > 0:
                    self._feedback_bursts.append({"pos": self._last_enemy_pos.get(entity_id, (0, 0)), "kind": "defeat", "born": time.monotonic()})
                self._last_enemy_hp.pop(entity_id, None)
                self._last_enemy_pos.pop(entity_id, None)
        # 投射物
        for p in e.projectile_sys.projectiles:
            self._draw_projectile(p)
        # 掉落
        for p in e.drop_sys.pickups:
            self._draw_pickup(p)
        if e.player.current_hp < self._last_player_hp - 0.01:
            self._feedback_bursts.append({"pos": e.player.position, "kind": "player", "born": time.monotonic()})
        self._last_player_hp = e.player.current_hp
        self._draw_feedback()
        # 超级怪兽警告覆盖
        if e.state() == "SUPER_WARNING":
            Color(255 / 255, 73 / 255, 117 / 255, 1)
            Line(rectangle=(self.x, self.y, self.width, self.height), width=6)
            # 顶部红色警告条
            Color(102 / 255, 25 / 255, 63 / 255, 0.66)
            Rectangle(pos=(self.x, self.y + self.height - 80), size=(self.width, 80))

    def _draw_feedback(self) -> None:
        now = time.monotonic()
        keep = []
        textures = {"hit": "impact_spark", "defeat": "plasma_burst", "player": "energy_slash"}
        lifetimes = {"hit": 0.26, "defeat": 0.42, "player": 0.34}
        for burst in self._feedback_bursts:
            age = now - burst["born"]
            kind = burst["kind"]
            ttl = lifetimes[kind]
            if age >= ttl:
                continue
            keep.append(burst)
            (x, y), s = self._scale(*burst["pos"])
            ratio = age / ttl
            alpha = max(0.0, 1.0 - ratio)
            radius = (22 + 48 * ratio) * s
            texture = self._sprite_textures.get(textures[kind])
            if texture is not None:
                PushMatrix()
                Rotate(angle=(90 if kind == "player" else ratio * 24), origin=(x, y))
                Color(1, 1, 1, alpha)
                Rectangle(texture=texture, pos=(x - radius, y - radius), size=(radius * 2, radius * 2))
                PopMatrix()
            else:
                Color(0.36, 0.88, 1.0, alpha)
                Line(circle=(x, y, radius), width=max(1, 3 * s))
        self._feedback_bursts = keep

    def _draw_player(self) -> None:
        e = self.engine
        (x, y), s = self._scale(*e.player.position)
        r = 22 * s
        skin_id = getattr(e, "player_skin_id", "vanguard")
        texture = self._sprite_textures.get(f"player_skin_{skin_id}") or self._sprite_textures.get("player")
        if texture is not None:
            Color(1, 1, 1, 1)
            Rectangle(texture=texture, pos=(x - r * 1.9, y - r * 1.9), size=(r * 3.8, r * 3.8))
        else:
            Color(*COL_PLAYER)
            Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))
            Color(*COL_PLAYER_CORE)
            cr = max(2, r * 0.4)
            Ellipse(pos=(x - cr, y - cr), size=(cr * 2, cr * 2))
        if e.player.current_shield > 0 or e.player.growth.max_shield_extra > 0:
            Color(*COL_SHIELD)
            Line(circle=(x, y, r + 4), width=1)
        if e.player.invuln_left > 0:
            Color(*COL_PLAYER_CORE)
            Line(circle=(x, y, r + 6), width=1)
        # HP 条
        eff = e.player
        maxhp = eff.base_max_hp * (1.0 + eff.extra_max_hp_pct + eff.growth.max_hp_pct_bonus)
        ratio = max(0.0, min(1.0, eff.current_hp / max(1.0, maxhp)))
        w = 80 * s
        h = 8 * s
        Color(*COL_HP_BACK)
        Rectangle(pos=(x - w / 2, y - r - 12 * s), size=(w, h))
        Color(*COL_HP)
        Rectangle(pos=(x - w / 2, y - r - 12 * s), size=(w * ratio, h))

    def _draw_enemy(self, en) -> None:
        (x, y), s = self._scale(*en.position)
        r = en.collision_radius * s
        if en.is_super:
            color = COL_ENEMY_SUPER
            wr = r + 6
        elif en.is_elite:
            color = COL_ENEMY_ELITE
            wr = r
        else:
            color = COL_ENEMY
            wr = r
        texture = self._sprite_textures.get("boss" if en.is_super else en.config_id)
        if texture is not None:
            sprite_r = max(wr * 1.55, (142 if en.is_super else 74) * s / 2)
            Color(1, 1, 1, 1)
            Rectangle(texture=texture, pos=(x - sprite_r, y - sprite_r), size=(sprite_r * 2, sprite_r * 2))
        else:
            Color(*color)
            Ellipse(pos=(x - wr, y - wr), size=(wr * 2, wr * 2))
        if en.config_id == "void_mender" and en.support_pulse_left > 0:
            Color(0.30, 0.98, 0.88, min(0.9, en.support_pulse_left / 0.68))
            for ally_id in en.support_target_ids:
                ally = next((candidate for candidate in self.engine.spawn_director.enemies if candidate.entity_id == ally_id), None)
                if ally is None or ally.state in (EnemyState.DYING, EnemyState.DEAD):
                    continue
                (ax, ay), _ = self._scale(*ally.position)
                Line(points=[x, y, ax, ay], width=max(1, 3 * s))
                Line(circle=(ax, ay, ally.collision_radius * s + 7 * s), width=max(1, 2 * s))
        if en.phase_flash_left > 0:
            Color(0.48, 0.76, 1.0, min(0.9, en.phase_flash_left / 0.5))
            Line(circle=(x, y, wr + (0.5 - en.phase_flash_left) * 68 * s), width=max(1, 3 * s))
        if en.state == EnemyState.WINDUP and en.attack_target_position is not None and en.config_id in ("crystal_sniper", "rail_turret", "prism_artillery"):
            (tx, ty), _ = self._scale(*en.attack_target_position)
            Color(0.35, 0.92, 1.0, 0.85)
            Line(points=[x, y, tx, ty], width=max(1, 2 * s))
            Line(circle=(tx, ty, max(10, 23 * s)), width=max(1, 2 * s))
        if en.state == EnemyState.WINDUP and en.config_id == "prism_artillery":
            facing = math.radians(en.facing)
            Color(0.62, 0.82, 1, 0.82)
            for offset in (-7, 0, 7):
                angle = facing + math.radians(offset)
                Line(points=[x, y, x + math.cos(angle) * en.attack_range * 0.45 * s,
                             y + math.sin(angle) * en.attack_range * 0.45 * s], width=max(1, 2 * s))
        if en.is_super:
            super_enemy = self.engine.super_director.active
            if super_enemy is not None and super_enemy.enemy is en and super_enemy.current_skill == SuperSkill.VOID_TIDAL:
                if super_enemy.skill_windup_left > 0 or super_enemy.skill_active_left > 0:
                    Color(0.16, 0.82, 1.0, 0.58 if super_enemy.skill_windup_left > 0 else 0.32)
                    ring_r = 118 * s
                    Line(circle=(x, y, ring_r), width=max(1, 2 * s))
                    gap_center = super_enemy.skill_aim_angle + math.radians(max(0, super_enemy.skill_wave_index - 1) * (18 if super_enemy.enraged else 24))
                    gap_half = math.radians(24 if super_enemy.enraged else 29)
                    for i in range(32):
                        angle = math.tau * i / 32
                        diff = (angle - gap_center + math.pi) % math.tau - math.pi
                        if abs(diff) <= gap_half:
                            continue
                        Line(points=[x + math.cos(angle) * ring_r, y + math.sin(angle) * ring_r,
                                     x + math.cos(angle) * (ring_r + 10 * s),
                                     y + math.sin(angle) * (ring_r + 10 * s)], width=max(1, 2 * s))
        # 血条
        if en.current_hp < en.max_hp:
            ratio = en.current_hp / max(1.0, en.max_hp)
            w = wr * 2
            h = max(2, 4 * s)
            Color(40 / 255, 20 / 255, 20 / 255, 1)
            Rectangle(pos=(x - wr, y - wr - 8 * s), size=(w, h))
            Color(*color)
            Rectangle(pos=(x - wr, y - wr - 8 * s), size=(w * ratio, h))

    def _draw_projectile(self, p) -> None:
        (x, y), s = self._scale(*p.position)
        r = max(2, p.radius * s)
        color = COL_PROJECTILE_PLAYER if p.faction == "player" else {
            "enemy_phase": (0.46, 0.82, 1, 1),
            "enemy_support": (0.34, 1, 0.82, 1),
            "enemy_prism": (0.62, 0.70, 1, 1),
            "boss_tidal": (0.35, 0.82, 1, 1),
            "boss_lattice": (0.54, 0.9, 1, 1),
        }.get(p.visual_kind, COL_PROJECTILE_ENEMY)
        speed = math.hypot(p.velocity[0], p.velocity[1])
        texture = self._sprite_textures.get("plasma_bolt") if speed >= 1 else None
        if texture is not None:
            angle = math.degrees(math.atan2(p.velocity[1], p.velocity[0]))
            length, thickness = max(32 * s, r * 8), max(10 * s, r * 2.5)
            PushMatrix()
            Rotate(angle=angle, origin=(x, y))
            Color(1, 1, 1, 0.95)
            Rectangle(texture=texture, pos=(x - length / 2, y - thickness / 2), size=(length, thickness))
            PopMatrix()
        else:
            Color(*color)
            if speed >= 1:
                ux, uy = p.velocity[0] / speed, p.velocity[1] / speed
                Line(points=[x - ux * (24 * s), y - uy * (24 * s), x, y], width=max(2, r * 1.5))
            Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))
        Color(color[0], color[1], color[2], 0.22)
        Ellipse(pos=(x - r * 2.8, y - r * 2.8), size=(r * 5.6, r * 5.6))

    def _draw_pickup(self, p) -> None:
        (x, y), s = self._scale(*p.position)
        kind = "xp" if p.kind.startswith("xp") else p.kind
        color = {
            "xp": COL_PICKUP_XP,
            "heal": (1, 0.32, 0.72, 1),
            "shield_restore": (0.30, 0.82, 1, 1),
            "armor": (1, 0.68, 0.20, 1),
            "skill_charge": (0.25, 0.9, 1, 1),
            "coin": (1, 0.78, 0.26, 1),
            "temp_buff": (0.7, 0.45, 1, 1),
        }.get(kind, COL_PICKUP_XP)
        texture = self._sprite_textures.get(f"pickup_{kind}")
        Color(*color)
        r = max(2, 8 * s)
        if texture is not None:
            Color(1, 1, 1, 1)
            Rectangle(texture=texture, pos=(x - r * 1.9, y - r * 1.9), size=(r * 3.8, r * 3.8))
        else:
            Ellipse(pos=(x - r, y - r), size=(r * 2, r * 2))
        orbit = time.monotonic() * 2.5 + x * 0.01 + y * 0.01
        Color(0.9, 0.98, 1, 0.9)
        Ellipse(pos=(x + math.cos(orbit) * r * 1.6 - 2 * s, y + math.sin(orbit) * r * 1.6 - 2 * s), size=(4 * s, 4 * s))

    def _draw_bomb(self, b: HazardBomb) -> None:
        e = self.engine
        (x, y), s = self._scale(*b.position)
        r = b.radius * s
        armed = e.timer.run_time >= b.armed_at
        col = COL_BOMB_DANGER if armed else COL_BOMB
        Color(*col)
        Line(circle=(x, y, r), width=2)
        mine = self._sprite_textures.get("pickup_hazard_bomb") if getattr(b, "faction", "enemy") == "enemy" else None
        if mine is not None:
            body = max(13, 24 * s)
            Color(1, 1, 1, 1)
            Rectangle(texture=mine, pos=(x - body, y - body), size=(body * 2, body * 2))


# =============================================================================
# HUD / 菜单
# =============================================================================
class HUDLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("color", COL_TEXT)
        kwargs.setdefault("font_size", 18)
        kwargs.setdefault("size_hint", (None, None))
        super().__init__(**kwargs)


# =============================================================================
# 主 App
# =============================================================================
class RGameKivyApp(App):
    """Kivy 入口：同时支持桌面（鼠标 + 键盘）和移动端（触屏 + 摇杆）。

    与 pygame 入口的关键区别是事件驱动：使用 ``Clock.schedule_interval`` 推动
    engine tick。
    """

    def __init__(
        self,
        *,
        seed: int | None = None,
        platform: str = "android",
        save_path: str = "rgame_profile.json",
        log_path: str | None = None,
        enable_disk_log: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._seed = seed
        self._platform = platform
        self._save_path = save_path
        self._log_path = log_path
        self._enable_disk_log = enable_disk_log

    def build(self) -> Widget:
        # 初始化键盘 + 触屏输入
        self.keyboard = KeyboardInputProvider()
        self.touch = TouchInputProvider(
            joystick_center=(150, 100),
            joystick_radius=100,
            switch_button_rect=(0, 0, 0, 0),
            pause_button_rect=(0, 0, 0, 0),
        )
        self.input = CompositeInputProvider(self.keyboard, self.touch)
        self.engine = Engine(
            platform=self._platform,
            input_provider=self.input,
            save_path=self._save_path,
            log_path=self._log_path,
            enable_disk_log=self._enable_disk_log,
            seed=self._seed,
        )
        # 窗口默认竖屏 → 强制横屏（移动端）
        if self._platform in ("android", "ios"):
            Window.orientation = "landscape"
        # 顶层布局
        self.root_layout = FloatLayout()
        # 战斗画布
        self.world = WorldCanvas(self.engine, size_hint=(1, 1), pos_hint={"x": 0, "y": 0})
        self.root_layout.add_widget(self.world)
        # HUD
        self.hud_labels: dict[str, Label] = {}
        self._build_hud()
        # 菜单/卡牌/警告/暂停覆盖层
        self.overlay = FloatLayout(size_hint=(1, 1))
        self.root_layout.add_widget(self.overlay)
        # 绑定键盘（Kivy window key down）
        Window.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        Window.bind(on_touch_down=self._on_touch_down, on_touch_move=self._on_touch_move, on_touch_up=self._on_touch_up)
        # 启动时钟：30/60 FPS
        Clock.schedule_interval(self._tick, 1 / 60)
        return self.root_layout

    def _build_hud(self) -> None:
        # 左上：生命/护盾/护甲
        self.hud_labels["hp"] = HUDLabel(text="HP 0/0", pos=(20, Window.height - 60))
        self.hud_labels["shield"] = HUDLabel(text="", pos=(20, Window.height - 90), font_size=14, color=COL_SHIELD)
        self.hud_labels["armor"] = HUDLabel(text="", pos=(20, Window.height - 120), font_size=14)
        # 顶部中央：阶段/时间
        self.hud_labels["stage"] = HUDLabel(text="", pos=(Window.width / 2 - 100, Window.height - 60), font_size=20)
        self.hud_labels["stage_time"] = HUDLabel(text="", pos=(Window.width / 2 - 50, Window.height - 90), font_size=14, color=COL_TEXT_DIM)
        # 右上：分数/抽卡/百杀
        self.hud_labels["score"] = HUDLabel(text="", pos=(Window.width - 320, Window.height - 60), font_size=16)
        self.hud_labels["card"] = HUDLabel(text="", pos=(Window.width - 320, Window.height - 90), font_size=16)
        self.hud_labels["super"] = HUDLabel(text="", pos=(Window.width - 320, Window.height - 120), font_size=14, color=COL_TEXT_DIM)
        # 底部：武器 + 等级
        self.hud_labels["level"] = HUDLabel(text="Lv.1", pos=(Window.width / 2 - 100, 20), font_size=16)
        self.hud_labels["weapon0"] = HUDLabel(text="", pos=(Window.width - 320, 30), font_size=12)
        self.hud_labels["weapon1"] = HUDLabel(text="", pos=(Window.width - 240, 30), font_size=12)
        self.hud_labels["weapon2"] = HUDLabel(text="", pos=(Window.width - 160, 30), font_size=12)
        self.hud_labels["skill"] = HUDLabel(text="", pos=(Window.width - 320, 106), font_size=13, color=COL_PLAYER)
        self.hud_labels["buffs"] = HUDLabel(text="", pos=(Window.width - 320, 132), font_size=12, color=COL_TEXT_DIM)
        for lbl in self.hud_labels.values():
            self.root_layout.add_widget(lbl)
        self.weapon_icon_widgets = []
        for _ in range(3):
            icon = KivyImage(size_hint=(None, None), size=(30, 30), opacity=0)
            self.root_layout.add_widget(icon)
            self.weapon_icon_widgets.append(icon)

    def _refresh_hud(self) -> None:
        e = self.engine
        eff = e.player
        maxhp = e.player.base_max_hp * (1.0 + e.player.extra_max_hp_pct + e.player.growth.max_hp_pct_bonus)
        self.hud_labels["hp"].text = f"HP {int(eff.current_hp)}/{int(maxhp)}"
        smax = eff.max_shield + eff.growth.max_shield_extra
        if smax > 0:
            self.hud_labels["shield"].text = f"SHIELD {int(eff.current_shield)}/{int(smax)}"
        if eff.base_armor > 0:
            self.hud_labels["armor"].text = f"ARMOR {int(eff.base_armor)}"
        if e.context.mode == "ENDLESS":
            stage_lbl = f"无尽·循环 {e.context.endless_cycle}"
        else:
            stage_lbl = f"第 {e.context.stage_index} 关"
        self.hud_labels["stage"].text = stage_lbl
        self.hud_labels["stage_time"].text = _fmt_time(e.timer.stage_time)
        if e.context.mode == "ENDLESS":
            threshold_lbl = f"→ {(e.context.endless_cycle + 1) * 5000}"
        else:
            threshold_lbl = {1: "→1200", 2: "→2600", 3: "→4800", 4: "→6800", 5: "→9000"}[min(e.context.stage_index, 5)]
        self.hud_labels["score"].text = f"分 {int(e.context.stage_score)} {threshold_lbl}"
        card_next = 500 if e.context.mode == "ENDLESS" else e._next_card_cost()
        self.hud_labels["card"].text = f"抽卡分 {int(e.context.card_score)}/{card_next}"
        sd = e.super_director
        if sd.queued > 0:
            self.hud_labels["super"].text = f"超级 {sd.progress}/100 (×{sd.queued})"
            self.hud_labels["super"].color = COL_SUPER_BAR
        else:
            self.hud_labels["super"].text = f"超级 {sd.progress}/100"
            self.hud_labels["super"].color = COL_TEXT_DIM
        self.hud_labels["level"].text = f"Lv.{e.level_sys.level}"
        self.hud_labels["skill"].text = (
            "技能就绪" if e.active_skill_cd_left <= 0 else f"技能冷却 {e.active_skill_cd_left:.1f}s"
        )
        active_buffs = []
        for buff_id, label in (("speed+15%", "疾行"), ("aspd+15%", "超频")):
            remaining = e.temp_buff_until.get(buff_id, 0.0) - e.timer.run_time
            if remaining > 0:
                active_buffs.append(f"{label} {remaining:.0f}s")
        self.hud_labels["buffs"].text = " · ".join(active_buffs)
        # 武器栏
        for i, lbl_key in enumerate(("weapon0", "weapon1", "weapon2")):
            icon = self.weapon_icon_widgets[i]
            icon.pos = (Window.width - 354 + i * 80, 56)
            icon.size = (30, 30)
            if i < len(e.weapon_sys.stack):
                w = e.weapon_sys.stack[i]
                active = "★" if i == e.weapon_sys.active_index else " "
                self.hud_labels[lbl_key].text = f"{active}{w.config.get('display_name', w.weapon_id)[:6]}"
                self.hud_labels[lbl_key].color = COL_BTN_ACTIVE if i == e.weapon_sys.active_index else COL_TEXT
                icon.texture = self.world._sprite_textures.get(f"weapon_{w.weapon_id}")
                icon.opacity = 1 if icon.texture is not None else 0
            else:
                self.hud_labels[lbl_key].text = ""
                icon.opacity = 0
        # 暂停/警告/选关
        if e.state() == "PAUSED":
            self.hud_labels["stage"].text = "已暂停"

    # ---- 输入事件 -------------------------------------------------------

    def _on_key_down(self, _w, key, _scancode, _text, _modifiers):
        if key == ord("w"):
            self.keyboard.update_key("w", True)
        elif key == ord("a"):
            self.keyboard.update_key("a", True)
        elif key == ord("s"):
            self.keyboard.update_key("s", True)
        elif key == ord("d"):
            self.keyboard.update_key("d", True)
        elif key == ord("q"):
            self.keyboard.request_switch()
        elif key == 27:  # Esc
            self.keyboard.request_pause()
        elif key == ord("r"):
            self.keyboard.request_refresh()
        elif key in (49, 50, 51):  # 1/2/3
            self.keyboard._select_index_requested = key - 49
        elif key in (13, 271):  # Enter
            self.keyboard._select_index_requested = 0

    def _on_key_up(self, _w, key, _scancode):
        if key == ord("w"):
            self.keyboard.update_key("w", False)
        elif key == ord("a"):
            self.keyboard.update_key("a", False)
        elif key == ord("s"):
            self.keyboard.update_key("s", False)
        elif key == ord("d"):
            self.keyboard.update_key("d", False)

    def _on_touch_down(self, _w, touch):
        return self.touch.on_touch(getattr(touch, "id", 0), (touch.x, touch.y), "down") if False else self._handle_touch(touch, "down")

    def _on_touch_move(self, _w, touch):
        return self._handle_touch(touch, "motion")

    def _on_touch_up(self, _w, touch):
        return self._handle_touch(touch, "up")

    def _handle_touch(self, touch, phase: str) -> bool:
        # 摇杆：左下区域
        x, y = touch.x, touch.y
        if phase in ("down", "motion") and self._in_joystick_region(x, y):
            self.touch.on_touch(getattr(touch, "id", 0), (x, y), phase)
            return True
        if phase == "up":
            self.touch.on_touch_release(getattr(touch, "id", 0))
            return False
        # 按钮：右下切换
        if phase == "down" and self._in_switch_button(x, y):
            self.touch.on_touch(getattr(touch, "id", 0), (x, y), "down")
            self.keyboard.request_switch()
            return True
        # 暂停按钮：右上
        if phase == "down" and self._in_pause_button(x, y):
            self.touch.on_touch(getattr(touch, "id", 0), (x, y), "down")
            self.keyboard.request_pause()
            return True
        # 菜单/抽卡/警告/结算：把点击当作引擎的 select_index
        if phase == "down" and self.engine.state() in ("MAIN_MENU", "MODE_SELECT", "PRESET_SELECT", "CARD_SELECT", "LEVEL_UP", "RESULT", "STAGE_CLEAR"):
            self._handle_ui_tap(x, y)
            return True
        return False

    def _in_joystick_region(self, x, y) -> bool:
        cx, cy = self.touch.joy_center
        r = self.touch.joy_radius
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    def _in_switch_button(self, x, y) -> bool:
        x0, y0, w, h = self.touch.switch_rect
        return (x0 <= x <= x0 + w) and (y0 <= y <= y0 + h)

    def _in_pause_button(self, x, y) -> bool:
        x0, y0, w, h = self.touch.pause_rect
        return (x0 <= x <= x0 + w) and (y0 <= y <= y0 + h)

    def _handle_ui_tap(self, x, y) -> None:
        st = self.engine.state()
        if st == "MAIN_MENU":
            # 3 按钮从中心 200 像素起，每 80px 一个
            cw, ch = Window.width, Window.height
            for i in range(3):
                btn = (cw / 2 - 150, 360 + i * 80, 300, 64)
                if btn[0] <= x <= btn[0] + btn[2] and btn[1] <= y <= btn[1] + btn[3]:
                    self.keyboard.request_select(i)
                    return
        elif st == "MODE_SELECT":
            cw, ch = Window.width, Window.height
            for i in range(3):
                btn = (cw / 2 - 200, 200 + i * 80, 400, 64)
                if btn[0] <= x <= btn[0] + btn[2] and btn[1] <= y <= btn[1] + btn[3]:
                    self.keyboard.request_select(i)
                    return
        elif st == "PRESET_SELECT":
            cw, ch = Window.width, Window.height
            for i in range(3):
                btn = (cw / 2 - 200, 200 + i * 80, 400, 64)
                if btn[0] <= x <= btn[0] + btn[2] and btn[1] <= y <= btn[1] + btn[3]:
                    self.keyboard.request_select(i)
                    return
        elif st in ("CARD_SELECT", "LEVEL_UP"):
            for i in range(3):
                btn = (Window.width / 2 - 380 + i * 260, Window.height - 360, 240, 320)
                if btn[0] <= x <= btn[0] + btn[2] and btn[1] <= y <= btn[1] + btn[3]:
                    self.keyboard.request_select(i)
                    return
            if st == "CARD_SELECT":
                refresh = (Window.width - 280, Window.height - 200, 240, 60)
                if refresh[0] <= x <= refresh[0] + refresh[2] and refresh[1] <= y <= refresh[1] + refresh[3]:
                    self.keyboard.request_refresh()
                    return
        elif st == "RESULT":
            for i in range(3):
                btn = (Window.width / 2 - 180, 280 + i * 70, 360, 56)
                if btn[0] <= x <= btn[0] + btn[2] and btn[1] <= y <= btn[1] + btn[3]:
                    self.keyboard.request_select(i)
                    return
        elif st == "STAGE_CLEAR":
            btn = (Window.width / 2 - 150, Window.height - 200, 300, 60)
            if btn[0] <= x <= btn[0] + btn[2] and btn[1] <= y <= btn[1] + btn[3]:
                self.keyboard.request_select(0)
                return

    # ---- 主循环 ---------------------------------------------------------

    def _tick(self, _dt) -> None:
        # Kivy 给出的 dt 来自上一次 Clock 触发，单位秒
        # 引擎节拍统一使用 1/60（按 §3.1 基准 60 FPS）
        self.engine.tick(1 / 60)
        self._refresh_hud()
        # 触发重绘
        self.world.redraw()


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"
