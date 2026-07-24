"""单局上下文。

按《游戏总体流程》§3：

- 持有 :class:`RunContext`；
- 创建时记录 ``run_seed``、模式、预设与配置版本；
- 重开必须从零重建，禁止复用上一局的实体、计时器、事件订阅或随机流。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .event_bus import EventBus
from .rng import NameRng, make_rng_streams
from .state_machine import StateMachine
from .time_keeper import TimeKeeper


class RunMode:
    CAMPAIGN = "campaign"  # 常规关模式
    ENDLESS = "endless"    # 无尽模式


class RunStatus:
    """运行状态枚举（与状态机的 State 不同，更专注于本局生命期）。"""

    SETUP = "setup"
    RUNNING = "running"
    PAUSED = "paused"
    ENDED = "ended"


@dataclass
class RunContext:
    """一局的全部可变状态。

    创建时自动建立事件总线、状态机、计时器与命名随机流集合。
    """

    run_id: str
    run_seed: int
    mode: str
    preset_id: str
    config_version: str
    app_version: str
    character_template: str = "balanced"
    # ==== 表现 / 输入 ============================================================
    visual_difficulty_tier: str = "V0"
    platform: str = "win"
    quality_grade: str = "high"
    input_device: str = "keyboard"  # keyboard / touch / gamepad

    # ==== 状态机与计时器 ========================================================
    state_machine: StateMachine = field(default_factory=StateMachine)
    bus: EventBus = field(default_factory=EventBus)
    timer: TimeKeeper = field(default_factory=TimeKeeper)
    rng: NameRng = field(init=False)

    # ==== 关卡 / 分数 ==========================================================
    stage_index: int = 1                     # 常规关序号
    endless_cycle: int = 0
    kill_score_to_award: int = 0             # 一次性事件值（最近一次击杀分）
    stage_score: int = 0
    run_score: int = 0
    card_score: int = 0
    pending_cards: int = 0                   # 待抽次数
    card_history: list[tuple[int, str]] = field(default_factory=list)

    # ==== 百杀 / 超级怪兽 =====================================================
    super_progress: int = 0                  # 0–100
    super_queued: int = 0                    # 阈值达到时 +1
    super_spawned_in_run: int = 0
    super_warning_cooldown: float = 0.0      # 两次警告至少 8 秒

    # ==== 玩家 ===============================================================
    player_id: str = "player"
    # （玩家的实体状态由 PlayerSystem 维护，这里只是元数据。）

    # ==== 玩家被动成长（按整局时间）===========================================
    last_passive_minute: int = 0             # 上一次结算被动成长的整分钟

    # ==== 成就 / 统计 ========================================================
    no_damage_time: float = 0.0              # 仅在 RUNNING 中累计
    bomb_dodges_run: int = 0
    no_damage_max_run: float = 0.0
    kills_run: int = 0
    super_kills_run: int = 0
    cards_run: int = 0
    score_run_record: int = 0

    # ==== 状态标志 ==========================================================
    status: str = RunStatus.SETUP

    # ==== 初始化 ============================================================
    def __post_init__(self) -> None:
        self.rng = make_rng_streams(self.run_seed)
        # 初始化一些派生默认值
        if self.platform == "android" or self.platform == "ios":
            self.input_device = "touch"
        else:
            self.input_device = "keyboard"

    # ---- 关卡切换 --------------------------------------------------------

    def enter_stage(self, idx: int) -> None:
        self.stage_index = idx
        self.timer.reset_stage()
        self.last_passive_minute = 0
        # 第 1 关从 V0 起，每关推进一档（基础 1→2→3，无尽循环时由循环决定）。
        self.visual_difficulty_tier = {1: "V0", 2: "V1", 3: "V2"}.get(idx, "V3")

    # ---- 工具 ------------------------------------------------------------

    def tag(self, label: str) -> str:
        return f"{self.run_id}-{label}"
