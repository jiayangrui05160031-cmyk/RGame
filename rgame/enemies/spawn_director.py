"""生成导演：八扇区、阶段预算、场上硬上限。"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from ..core.run_context import RunContext
from .enemies import Enemy, spawn_enemy
from .time_scaling import time_visual_tier


# 只限制“同时在场”，不限制整局总生成量；死亡回收后会继续无限补充。
ENEMY_HARD_CAP = 20


class Sector:
    """八扇区方向定义（度），与 [环境背景系统] §5 一致。"""
    E = 0
    NE = 45
    N = 90
    NW = 135
    W = 180
    SW = 225
    S = 270
    SE = 315


# 主边 4 个，斜向各占 0.5 权重。
SECTOR_POOL = (
    (Sector.E, 1.0), (Sector.NE, 0.5), (Sector.N, 1.0), (Sector.NW, 0.5),
    (Sector.W, 1.0), (Sector.SW, 0.5), (Sector.S, 1.0), (Sector.SE, 0.5),
)


@dataclass
class SpawnConfig:
    """关卡/阶段的生成配置。"""
    enemy_pool: list[str]
    enemy_weights: list[float]
    spawn_budget_base: float = 1.0
    elite_base_chance: float = 0.02
    max_elite_chance: float = 0.25
    min_player_distance: float = 480.0
    spawn_min_interval: float = 0.55
    spawn_max_interval: float = 1.40
    super_min_distance: float = 650.0


@dataclass
class SpawnDirector:
    """敌人生成导演。"""

    bounds: tuple[float, float, float, float]  # min_x, min_y, max_x, max_y
    enemies: list[Enemy] = field(default_factory=list)
    spawn_cooldown: float = 0.0
    last_sectors: deque[str] = field(default_factory=lambda: deque(maxlen=8))
    last_main_direction: deque[str] = field(default_factory=lambda: deque(maxlen=8))

    def reset(self) -> None:
        self.enemies.clear()
        self.spawn_cooldown = 0.0
        self.last_sectors.clear()
        self.last_main_direction.clear()

    # --- 阶段参数 --------------------------------------------------------

    def elapsed_minutes(self, run_context: RunContext) -> int:
        return int(run_context.timer.stage_time // 60)

    def stage_cfg(self, run_context: RunContext, stages: dict) -> tuple[dict, bool]:
        """返回 (关卡配置, 是否无尽)。"""
        if run_context.mode == "endless":
            return stages["endless"], True
        idx = run_context.stage_index
        return stages.get(f"stage_{idx}", stages["stage_1"]), False

    def current_budget(self, run_context: RunContext, stage_cfg: dict) -> float:
        m = self.elapsed_minutes(run_context)
        ec = run_context.endless_cycle
        base = float(stage_cfg.get("spawn_budget_multiplier", 1.0))
        return base * (1.08 ** m) * (1.08 ** ec)

    def elite_chance(self, run_context: RunContext, stage_cfg: dict) -> float:
        m = self.elapsed_minutes(run_context)
        base = float(stage_cfg.get("elite_base_chance", 0.02))
        add = 0.02 * (m // 2)  # 每 120 秒 +2 个百分点
        return min(float(stage_cfg.get("max_elite_chance", 0.25)), base + add)

    # --- 辅助 ------------------------------------------------------------

    def _main_direction(self, sector_deg: float) -> str:
        if 67.5 <= sector_deg < 112.5:
            return "N"
        if 112.5 <= sector_deg < 157.5:
            return "NW"
        if 157.5 <= sector_deg < 202.5:
            return "W"
        if 202.5 <= sector_deg < 247.5:
            return "SW"
        if 247.5 <= sector_deg < 292.5:
            return "S"
        if 292.5 <= sector_deg < 337.5:
            return "SE"
        if 337.5 <= sector_deg or sector_deg < 22.5:
            return "E"
        if 22.5 <= sector_deg < 67.5:
            return "NE"
        return "?"

    def _pick_sector(self, run_context: RunContext, is_super: bool = False) -> float:
        weights = [w for _, w in SECTOR_POOL]
        sectors = [s for s, _ in SECTOR_POOL]
        # 同一主方向不可连续 3 次
        for _ in range(8):
            idx = run_context.rng.get("enemy_spawn_rng").range(len(sectors))
            sector_deg = sectors[idx]
            md = self._main_direction(sector_deg)
            if len(self.last_main_direction) < 3:
                break
            if all(md != x for x in list(self.last_main_direction)[-3:]):
                break
        return sector_deg

    def _spawn_position(
        self,
        sector_deg: float,
        bounds: tuple[float, float, float, float],
        player_pos: tuple[float, float],
        min_dist: float,
        rng,
    ) -> tuple[float, float] | None:
        # 从扇区方向把射线投到竞技场边缘。旧算法先固定走约 420–520
        # 像素再裁边，玩家靠近边缘时大多数结果不足最小距离，导致生成
        # 冷却照常消耗却没有怪物出现。
        min_x, min_y, max_x, max_y = bounds
        inset = 30.0
        candidates: list[tuple[float, tuple[float, float]]] = []
        for _ in range(10):
            angle = sector_deg + rng.uniform(-24.0, 24.0)
            rad = math.radians(angle)
            ux, uy = math.cos(rad), math.sin(rad)
            tx = math.inf
            ty = math.inf
            if ux > 1e-6:
                tx = (max_x - inset - player_pos[0]) / ux
            elif ux < -1e-6:
                tx = (min_x + inset - player_pos[0]) / ux
            if uy > 1e-6:
                ty = (max_y - inset - player_pos[1]) / uy
            elif uy < -1e-6:
                ty = (min_y + inset - player_pos[1]) / uy
            positive = [t for t in (tx, ty) if t > 0]
            if not positive:
                continue
            distance = min(positive)
            pos = (player_pos[0] + ux * distance, player_pos[1] + uy * distance)
            candidates.append((distance, pos))
            if distance >= min_dist:
                return pos

        # 当前扇区空间不足时，从四角中选离玩家最远处，保证生成循环不会
        # 因玩家贴边而永久停摆。
        corners = [
            (min_x + inset, min_y + inset), (max_x - inset, min_y + inset),
            (min_x + inset, max_y - inset), (max_x - inset, max_y - inset),
        ]
        fallback = max(corners, key=lambda p: math.hypot(p[0] - player_pos[0], p[1] - player_pos[1]))
        return fallback

    # --- 主流程 ----------------------------------------------------------

    def step(
        self,
        *,
        run_context: RunContext,
        stage_cfg: dict,
        spawn_cfg: SpawnConfig,
        player_pos: tuple[float, float],
        player_alive: bool,
        bombs_active_count: int,
        on_enemy_spawn,
    ) -> None:
        """按阶段预算推进生成节奏。"""
        if not player_alive:
            return
        # 场上上限
        if len(self.enemies) >= ENEMY_HARD_CAP:
            return
        # 出生安全区限制：开局 2 秒禁止敌人生成于中心 220 半径
        if run_context.timer.stage_time < 2.0:
            return
        if self.spawn_cooldown > 0:
            self.spawn_cooldown -= run_context.timer.delta
            return
        # 节奏
        midpoint = spawn_cfg.spawn_min_interval + (spawn_cfg.spawn_max_interval - spawn_cfg.spawn_min_interval) * 0.5
        budget = max(0.65, min(2.2, self.current_budget(run_context, stage_cfg)))
        self.spawn_cooldown = midpoint / budget
        # 选择敌人原型
        pool = spawn_cfg.enemy_pool
        weights = spawn_cfg.enemy_weights
        chosen = run_context.rng.get("enemy_spawn_rng").weighted(pool, weights)
        if chosen is None:
            return
        sector_deg = self._pick_sector(run_context)
        pos = self._spawn_position(sector_deg, self.bounds, player_pos, spawn_cfg.min_player_distance, run_context.rng.get("enemy_spawn_rng"))
        if pos is None:
            return
        # 精英？
        ec = self.elite_chance(run_context, stage_cfg)
        is_elite = run_context.rng.get("enemy_spawn_rng").chance(ec)
        # 形态 T0–T3
        m = self.elapsed_minutes(run_context)
        if m < 2:
            tf = "T0"
        elif m < 5:
            tf = "T1"
        elif m < 9:
            tf = "T2"
        else:
            tf = "T3"
        # 拉取 config（由 on_enemy_spawn 决定）
        on_enemy_spawn(chosen, pos, is_elite, tf, sector_deg, run_context)
        self.last_sectors.append(str(int(sector_deg)))
        self.last_main_direction.append(self._main_direction(sector_deg))


def time_visual_tier_for(stage_index: int, endless_cycle: int) -> str:
    """便捷。"""
    if endless_cycle > 0:
        return "VX"
    return ["V0", "V0", "V1", "V2"][min(stage_index, 3)]
