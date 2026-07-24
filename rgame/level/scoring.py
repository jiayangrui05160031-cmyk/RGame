"""关卡与计分。

按《关卡与计分系统》：

- 三个计数器：``stage_score`` / ``run_score`` / ``card_score``；
- 一次击杀同步增加；
- 抽卡只扣 ``card_score``；
- 三关阈值：1200 / 2600 / 4800；
- 无尽模式 5000 分一个循环；
- 同步事件：``score_awarded`` / ``stage_cleared`` / ``endless_cycle_completed``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from ..cards.cards import endless_card_cost
from ..core.event_bus import Event, EventBus
from ..core.run_context import RunContext


@dataclass
class ScoringSystem:
    """计分系统。"""

    bus: EventBus

    def award_kill(
        self,
        run_context: RunContext,
        *,
        base_kill_score: int,
        elite_factor: int = 1,
        special_risk_factor: int = 1,
        no_score: bool = False,
    ) -> int:
        """对一次合法击杀计分，同步更新三个计数器。

        返回最终得分（不是溢出分数）。
        """
        if no_score:
            # 例如调试单位、召唤物、分裂物
            self.bus.publish(Event(
                id=f"score-{run_context.timer.run_time}-{base_kill_score}",
                type="score_awarded",
                payload={"enemy_id": None, "base": base_kill_score, "final": 0, "no_score": True,
                          "stage_score": run_context.stage_score, "run_score": run_context.run_score,
                          "card_score": run_context.card_score},
                timestamp=run_context.timer.run_time,
            ))
            return 0
        final = round(base_kill_score * elite_factor * special_risk_factor)
        run_context.stage_score += final
        run_context.run_score += final
        run_context.card_score += final
        run_context.kill_score_to_award = final
        run_context.kills_run += 1
        run_context.score_run_record = max(run_context.score_run_record, run_context.run_score)
        self.bus.publish(Event(
            id=f"score-{run_context.timer.run_time}-{final}",
            type="score_awarded",
            payload={
                "enemy_id": None, "base": base_kill_score, "final": final,
                "stage_score": run_context.stage_score,
                "run_score": run_context.run_score,
                "card_score": run_context.card_score,
                "elite_factor": elite_factor,
                "special_risk_factor": special_risk_factor,
            },
            timestamp=run_context.timer.run_time,
        ))
        return final

    def spend_card_score(self, run_context: RunContext, *, mode: str, n: int) -> int:
        """扣 ``card_score`` 触发一次抽卡机会，返回扣了多少。

        mode=endless 固定 500；其他按 campaign 第 n 次公式。

        """
        if mode == "endless":
            cost = endless_card_cost()
        else:
            from ..cards.cards import campaign_card_cost
            cost = campaign_card_cost(n)
        cost = min(cost, run_context.card_score)
        run_context.card_score -= cost
        if cost > 0:
            run_context.pending_cards += 1
        return cost

    def check_clear(self, run_context: RunContext, *, clear_score: int) -> bool:
        return run_context.stage_score >= clear_score and run_context.state_machine.current.name in ("RUNNING",)

    def apply_stage_clear(self, run_context: RunContext, *, hp_recovery_pct: float = 0.35) -> None:
        """关卡通过时调用：恢复 HP、不清 stage_score（已通关）。"""
        eff_hp = run_context.timer.run_time
        # 当前关卡记入历史
        self.bus.publish(Event(
            id=f"stage-clr-{run_context.timer.run_time}-{run_context.stage_index}",
            type="stage_cleared",
            payload={
                "stage": run_context.stage_index,
                "stage_score": run_context.stage_score,
                "run_score": run_context.run_score,
                "run_time": eff_hp,
            },
            timestamp=eff_hp,
        ))
        # HP 恢复：调用方负责

    def check_endless_cycle(self, run_context: RunContext, *, cycle_score: int = 5000) -> Optional[int]:
        """检查无尽循环完成（每次跨过 (cycle+1)*cycle_score 时返回新 cycle 编号）。"""
        if run_context.mode != "endless":
            return None
        cycle_threshold = (run_context.endless_cycle + 1) * cycle_score
        if run_context.stage_score >= cycle_threshold:
            run_context.endless_cycle += 1
            self.bus.publish(Event(
                id=f"cycle-{run_context.endless_cycle}",
                type="endless_cycle_completed",
                payload={
                    "cycle": run_context.endless_cycle,
                    "stage_score": run_context.stage_score,
                    "run_score": run_context.run_score,
                },
                timestamp=run_context.timer.run_time,
            ))
            return run_context.endless_cycle
        return None


def award_kill_score(
    scoring: ScoringSystem,
    run_context: RunContext,
    *,
    base_kill_score: int,
    elite_factor: int = 1,
    special_risk_factor: int = 1,
    no_score: bool = False,
) -> int:
    return scoring.award_kill(
        run_context,
        base_kill_score=base_kill_score,
        elite_factor=elite_factor,
        special_risk_factor=special_risk_factor,
        no_score=no_score,
    )


def process_level_state_changes(
    run_context: RunContext,
    *,
    stages_cfg: dict,
    stage_clear_score: int,
) -> Optional[str]:
    """驱动 ``STAGE_CLEAR`` 转换。

    返回 ``"stage_clear"`` / ``"endless_cycle"`` / ``None``。
    """
    if run_context.mode == "endless":
        cycle = run_context.endless_cycle
        next_threshold = (cycle + 1) * 5000
        if run_context.stage_score >= next_threshold:
            run_context.endless_cycle = cycle + 1
            return "endless_cycle"
        return None
    if run_context.stage_score >= stage_clear_score:
        return "stage_clear"
    return None
