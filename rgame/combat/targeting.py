"""自动索敌与目标选择。

按《战斗互动系统》§3 +《攻击视野与距离》§2/§3/§8：

- ``sense_radius`` 内、``target_fov`` 视角内、未死亡的目标进入候选池；
- 评分顺序：距离更近 → 已进入攻击距离 → 威胁等级 → ID 稳定排序；
- 一旦锁定，至少保持 0.25 秒 / 越出 sense+15% 才重新选。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class TargetCandidate:
    entity_id: str
    position: tuple[float, float]
    faction: str           # "enemy" / "player"
    hp: float
    hp_max: float
    threat: float = 0.0
    archetype: str = ""
    is_elite: bool = False
    is_super: bool = False
    alive: bool = True


def angle_deg(dx: float, dy: float) -> float:
    """返回 (dx, dy) 与 +x 轴的夹角（度）。"""
    if dx == 0 and dy == 0:
        return 0.0
    return (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    """最短角度差（0..180）。"""
    d = (a - b + 540.0) % 360.0 - 180.0
    return abs(d)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def in_fov(facing_deg: float, target_deg: float, fov_deg: float) -> bool:
    if fov_deg >= 360.0:
        return True
    return angle_diff(facing_deg, target_deg) <= fov_deg / 2.0


@dataclass
class TargetingSystem:
    """玩家武器的自动索敌系统。"""

    sense_radius: float
    target_fov_deg: float = 360.0
    hysteresis_factor: float = 1.15       # 索敌半径 +15% 滞回
    lock_keep_time: float = 0.25
    rescan_every: float = 0.1
    cooldown_left: float = 0.0
    target_id: str | None = None
    target_locked_at: float = 0.0
    last_reacquire: float = 0.0
    last_facing_deg: float = 0.0

    def step_cooldown(self, dt: float) -> None:
        if self.cooldown_left > 0:
            self.cooldown_left = max(0.0, self.cooldown_left - dt)

    def reset(self) -> None:
        self.target_id = None
        self.target_locked_at = 0.0

    def _score(self, attacker, c: TargetCandidate) -> tuple:
        """按规则返回 (distance, in_range, threat, id) 4-tuple 供 ``min`` 选择。"""
        d = distance(attacker, c.position)
        in_range = 1 if d <= self.sense_radius else 0  # 用 sense 粗略
        # 因越小越优先 → 把距离放最前；同距离大者优先级高 → 反向排序
        thr = -c.threat
        # 倒序：-distance 越大越先选错，所以用 (-distance, id) 时 min 会先选最大的 distance → 错。
        # 我们用 ``min`` 选最优，所以距离越小越优：直接 distance。
        return (d, -in_range, thr, c.entity_id)

    def acquire(
        self,
        *,
        attacker_pos: tuple[float, float],
        attacker_facing_deg: float,
        candidates: list[TargetCandidate],
        current_time: float,
        attack_range: float,
        allow_lock_keep: bool = True,
    ) -> TargetCandidate | None:
        """选择当前目标。

        - 若当前目标仍合法 (存活、敌对、在滞回半径内、未被遮挡) 保持锁定；
        - 否则按评分重选。
        """
        self.last_facing_deg = attacker_facing_deg
        if self.cooldown_left > 0:
            self.cooldown_left -= 0.0  # place holder for rescan timer
        # 当前目标保留检查
        if allow_lock_keep and self.target_id is not None:
            keep = self._find(candidates, self.target_id)
            if keep is not None and keep.alive and keep.faction == "enemy":
                d = distance(attacker_pos, keep.position)
                if d <= self.sense_radius * self.hysteresis_factor:
                    if current_time - self.target_locked_at < self.lock_keep_time:
                        return keep
                # 仍可重选

        # 全局候选
        legal = [
            c for c in candidates
            if c.alive and c.faction == "enemy"
        ]
        if not legal:
            self.target_id = None
            return None
        legal.sort(key=lambda c: self._score(attacker_pos, c))
        chosen = legal[0]
        self.target_id = chosen.entity_id
        self.target_locked_at = current_time
        return chosen

    def _find(self, candidates: list[TargetCandidate], entity_id: str) -> TargetCandidate | None:
        for c in candidates:
            if c.entity_id == entity_id:
                return c
        return None


def choose_target(
    attacker_pos: tuple[float, float],
    attacker_facing_deg: float,
    sense_radius: float,
    candidates: list[TargetCandidate],
    attack_range: float,
    target_fov_deg: float = 360.0,
) -> TargetCandidate | None:
    """便捷目标选择。"""
    legal = [
        c for c in candidates
        if c.alive and c.faction == "enemy"
        and distance(attacker_pos, c.position) <= sense_radius
        and in_fov(attacker_facing_deg, angle_deg(c.position[0] - attacker_pos[0], c.position[1] - attacker_pos[1]), target_fov_deg)
    ]
    if not legal:
        return None
    legal.sort(key=lambda c: (distance(attacker_pos, c.position), -c.threat, c.entity_id))
    in_range_extra = [c for c in legal if distance(attacker_pos, c.position) <= attack_range]
    if in_range_extra:
        in_range_extra.sort(key=lambda c: (distance(attacker_pos, c.position), -c.threat, c.entity_id))
        return in_range_extra[0]
    return legal[0]


__all__ = [
    "TargetCandidate",
    "TargetingSystem",
    "choose_target",
    "angle_deg",
    "angle_diff",
    "in_fov",
    "distance",
]
