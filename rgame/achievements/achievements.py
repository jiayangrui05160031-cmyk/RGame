"""成就系统。

按《成就系统》：

- 8 组 × 3 级共 24 个；
- 高级触发时低级同步解锁；
- 事件去重（防止回滚 / 重复死亡事件增加进度）；
- 提示队列 2.5s，``SUPER_WARNING`` 期间隐藏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..core.event_bus import Event, EventBus


# ===== [新增] 成就图标路径映射 =====
ACHIEVEMENT_ICON_MAP: dict[str, str] = {
    "ACH-RUNSCORE": "ach_runscore",
    "ACH-TOTALSCORE": "ach_totalscore",
    "ACH-RUNKILL": "ach_runkill",
    "ACH-SUPER": "ach_super",
    "ACH-STAGE": "ach_stage",
    "ACH-NOHIT": "ach_nohit",
    "ACH-BOMB": "ach_bomb",
    "ACH-CARD": "ach_card",
}


@dataclass
class AchievementEntry:
    achievement_id: str
    series: str
    grade: int
    threshold: float
    metric: str
    value: Optional[float] = None


@dataclass
class AchievementSystem:
    bus: EventBus
    achievements: dict[str, dict]
    unlocked: dict[str, dict] = field(default_factory=dict)   # aid -> {unlock_time, value, ...}
    stats_run: dict[str, float] = field(default_factory=dict)
    stats_lifetime: dict[str, float] = field(default_factory=dict)
    notifications: list[dict] = field(default_factory=list)
    notification_left: float = 0.0
    notification_max: int = 1
    pending_queue: list[dict] = field(default_factory=list)

    def reset(self) -> None:
        """每次开新局：仅清空 run 统计，lifetime 保留。"""
        self.stats_run.clear()
        self.pending_queue.clear()
        self.notification_left = 0.0
        self.notifications.clear()

    def submit_event(self, *, event_type: str, payload: dict, super_warning_active: bool = False) -> None:
        """由外部把 ``score_awarded`` 等事件转换为成就统计。

        :param super_warning_active: ``True`` 时不发送提示（按文档）。
        """
        if event_type == "score_awarded":
            self.stats_run["run_score"] = self.stats_run.get("run_score", 0.0)
            self.stats_run["run_score"] = max(self.stats_run["run_score"], payload.get("run_score", 0))
            self.stats_lifetime["lifetime_score"] = self.stats_lifetime.get("lifetime_score", 0.0) + payload.get("final", 0)
            self._evaluate("run_score", self.stats_run["run_score"])
            self._evaluate("lifetime_score", self.stats_lifetime["lifetime_score"])
        elif event_type == "enemy_defeated":
            self.stats_run["kills_run"] = self.stats_run.get("kills_run", 0) + 1
            self.stats_lifetime["lifetime_kills"] = self.stats_lifetime.get("lifetime_kills", 0) + 1
            self._evaluate("kills_run", self.stats_run["kills_run"])
        elif event_type == "super_enemy_defeated":
            self.stats_lifetime["super_kills_lifetime"] = self.stats_lifetime.get("super_kills_lifetime", 0) + 1
            self._evaluate("super_kills_lifetime", self.stats_lifetime["super_kills_lifetime"])
        elif event_type == "stage_cleared":
            stage = payload.get("stage", 0)
            self.stats_run["stage_reached"] = max(self.stats_run.get("stage_reached", 0), stage)
            self._evaluate("stage_reached", stage)
            if stage >= 5:
                self.stats_lifetime["campaign_cleared"] = self.stats_lifetime.get("campaign_cleared", 0) + 1
                self._evaluate("campaign_cleared", 1.0)
        elif event_type == "endless_cycle_completed":
            cycle = payload.get("cycle", 0)
            self.stats_run["endless_cycles"] = max(self.stats_run.get("endless_cycles", 0), cycle)
            self._evaluate("endless_cycles", cycle)
        elif event_type == "damage_applied":
            # payload 中 ``to_player=True`` 时清零无伤计时
            if payload.get("to_player"):
                self.stats_run["no_damage_time"] = 0.0
        elif event_type == "no_damage_time":
            seconds = float(payload.get("seconds", 0.0) or 0.0)
            self.stats_run["no_damage_max_run"] = max(self.stats_run.get("no_damage_max_run", 0.0), seconds)
            self._evaluate("no_damage_max_run", self.stats_run["no_damage_max_run"])
        elif event_type == "hazard_drop_dodged":
            self.stats_lifetime["bomb_dodges_lifetime"] = self.stats_lifetime.get("bomb_dodges_lifetime", 0) + 1
            self._evaluate("bomb_dodges_lifetime", self.stats_lifetime["bomb_dodges_lifetime"])
        elif event_type == "card_resolved":
            self.stats_run["cards_run"] = self.stats_run.get("cards_run", 0) + 1
            self._evaluate("cards_run", self.stats_run["cards_run"])

    def _evaluate(self, metric: str, value: float) -> None:
        for aid, cfg in self.achievements.items():
            if aid in self.unlocked:
                continue
            if cfg.get("metric") != metric:
                continue
            threshold = float(cfg.get("threshold", 0))
            if cfg.get("value") is not None:
                # 阈值等于 value（stage_reached 是这种）
                if value >= cfg.get("value", 0) and metric == "stage_reached":
                    self._unlock(aid, value)
                continue
            if value >= threshold:
                self._unlock(aid, value)
        # 同步低级（高 grade 解锁后低 grade 也解锁）
        series_grades: dict[str, list[tuple[int, str]]] = {}
        for aid, cfg in self.achievements.items():
            series_grades.setdefault(cfg["series"], []).append((cfg["grade"], aid))
        for s, items in series_grades.items():
            items.sort(key=lambda t: t[0])
            max_unlocked_grade = max(
                (cfg["grade"] for aid_, cfg in self.achievements.items()
                 if aid_ in self.unlocked and cfg["series"] == s),
                default=0,
            )
            for grade, aid in items:
                if aid not in self.unlocked and grade <= max_unlocked_grade:
                    self._unlock(aid, self.stats_run.get(self.achievements[aid]["metric"], 0))

    def _unlock(self, achievement_id: str, value: float) -> None:
        if achievement_id in self.unlocked:
            return
        cfg = self.achievements[achievement_id]
        self.unlocked[achievement_id] = {
            "unlock_time": 0.0,
            "value": value,
            "grade": cfg["grade"],
            "series": cfg["series"],
        }
        # 排序解锁通知（Ⅰ→Ⅱ→Ⅲ + ID 稳定排序）
        entry = {
            "achievement_id": achievement_id,
            "grade": cfg["grade"],
            "value": value,
            "metric": cfg.get("metric"),
            "threshold": cfg.get("threshold"),
        }
        self.pending_queue.append(entry)
        self.pending_queue.sort(key=lambda e: (e["grade"], e["achievement_id"]))

    def notify_tick(self, dt: float, *, super_warning_active: bool) -> None:
        """每帧推进提示队列。"""
        if self.notification_left > 0:
            self.notification_left -= dt
            if self.notification_left <= 0:
                self.notifications.clear()
        # 当无提示且有 pending 且不在超级警告期间 → 显示下一条
        if not self.notifications and self.pending_queue and not super_warning_active:
            nxt = self.pending_queue.pop(0)
            self.notifications = [nxt]
            self.notification_left = 2.5
            self.bus.publish(Event(
                id=f"ach-{nxt['achievement_id']}",
                type="achievement_unlocked",
                payload=nxt,
            ))


def create_achievement_system(bus: EventBus, achievements_cfg: dict) -> AchievementSystem:
    return AchievementSystem(bus=bus, achievements=achievements_cfg)
