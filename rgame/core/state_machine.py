"""有限状态机。

按《游戏总体流程》的状态机要求实现：

    BOOT → MAIN_MENU → MODE_SELECT → PRESET_SELECT → RUNNING ↔ PAUSED/SUPER_WARNING
    → LEVEL_UP/CARD_SELECT → RUNNING → STAGE_CLEAR/NEXT_STAGE → RESULT

切换规则：

- 只有合法出口允许的状态变更；
- 同帧多个状态请求按优先级队列排队，在逻辑步末统一出栈；
- 没有合法出口时拒绝切换并记录异常。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


class StateError(RuntimeError):
    """不合法的状态迁移。"""


@dataclass(frozen=True)
class State:
    name: str


# 常量状态名。总览约束状态机的可命名集合。
BOOT = State("BOOT")
MAIN_MENU = State("MAIN_MENU")
MODE_SELECT = State("MODE_SELECT")
PRESET_SELECT = State("PRESET_SELECT")
RUNNING = State("RUNNING")
PAUSED = State("PAUSED")
SUPER_WARNING = State("SUPER_WARNING")
LEVEL_UP = State("LEVEL_UP")
CARD_SELECT = State("CARD_SELECT")
STAGE_CLEAR = State("STAGE_CLEAR")
ENDING = State("ENDING")
RESULT = State("RESULT")
ERROR = State("ERROR")


# 合法迁移表。对应《游戏总体流程》§2 状态机。
# 状态 -> 其下一状态的合法集合。
_LEGAL: dict[State, frozenset[State]] = {
    BOOT: frozenset({MAIN_MENU, ERROR}),
    MAIN_MENU: frozenset({MODE_SELECT, RESULT, ERROR}),
    MODE_SELECT: frozenset({PRESET_SELECT, MAIN_MENU, ERROR}),
    PRESET_SELECT: frozenset({RUNNING, MODE_SELECT, ERROR}),
    RUNNING: frozenset({PAUSED, SUPER_WARNING, LEVEL_UP, CARD_SELECT, STAGE_CLEAR, ENDING, ERROR}),
    PAUSED: frozenset({RUNNING, RESULT, ERROR}),
    SUPER_WARNING: frozenset({RUNNING, LEVEL_UP, CARD_SELECT, STAGE_CLEAR, ENDING, ERROR}),
    LEVEL_UP: frozenset({RUNNING, ENDING, ERROR}),
    CARD_SELECT: frozenset({RUNNING, STAGE_CLEAR, ENDING, ERROR}),
    STAGE_CLEAR: frozenset({RUNNING, RESULT, ERROR}),
    ENDING: frozenset({RESULT, ERROR}),
    RESULT: frozenset({MAIN_MENU, RUNNING, ERROR}),
    ERROR: frozenset({MAIN_MENU, RESULT}),
}


class StateMachine:
    """严格的状态机。

    用于：

    - :py:meth:`request` 把目标状态排队，等待 :py:meth:`flush` 时按队列顺序提交；
    - :py:meth:`force` 在初始化与异常恢复时直接设置状态；
    - 提供订阅 :py:attr:`on_enter` / :py:attr:`on_exit` 回调。
    """

    def __init__(self, initial: State = BOOT, clock_now: Callable[[], float] | None = None) -> None:
        self._current = initial
        self._queue: list[State] = []
        self._on_enter: list[Callable[[State], None]] = []
        self._on_exit: list[Callable[[State], None]] = []
        self._clock_now = clock_now or (lambda: 0.0)

    # --- 基础查询 --------------------------------------------------------

    @property
    def current(self) -> State:
        return self._current

    def is_in(self, *states: State) -> bool:
        return self._current in states

    # --- 状态变更请求 ----------------------------------------------------

    def request(self, target: State) -> None:
        """入队一个状态变更请求。

        队列在 :py:meth:`flush` 时按"同帧优先级"提交：
        DEATH/STAGE_CLEAR > LEVEL_UP > CARD_SELECT > SUPER_WARNING > PAUSED。
        """
        self._queue.append(target)

    def force(self, target: State) -> None:
        """直接设置状态，跳过校验（用于初始化与错误恢复）。"""
        self._do_transition(target)

    def flush(self) -> bool:
        """提交一个逻辑步内的全部状态变更。

        将队列按优先级排序后逐个尝试执行；中途失败则停在第一个失败前。
        返回值表示本步是否发生过状态切换。
        """
        if not self._queue:
            return False
        # 同帧优先级（死亡最优先）。具体见《游戏总体流程》§5 同时事件优先级。
        priority = [
            ENDING,
            STAGE_CLEAR,
            LEVEL_UP,
            CARD_SELECT,
            SUPER_WARNING,
            PAUSED,
            RESULT,
            ERROR,
            RUNNING,
        ]
        self._queue.sort(key=lambda s: priority.index(s) if s in priority else 99)
        touched = False
        for target in self._queue:
            if self._can_transition(target):
                self._do_transition(target)
                touched = True
            else:
                # 中断：剩余请求丢弃（视为同一逻辑步内不可再切换）
                break
        self._queue.clear()
        return touched

    def cancel_pending(self) -> None:
        """清除尚未提交的状态请求（用于暂停、后台、强制界面）。"""
        self._queue.clear()

    # --- 回调订阅 --------------------------------------------------------

    def on_enter(self, callback: Callable[[State], None]) -> None:
        self._on_enter.append(callback)

    def on_exit(self, callback: Callable[[State], None]) -> None:
        self._on_exit.append(callback)

    # --- 内部 ------------------------------------------------------------

    def _can_transition(self, target: State) -> bool:
        if target == self._current:
            return False
        return target in _LEGAL.get(self._current, frozenset())

    def _do_transition(self, target: State) -> None:
        prev = self._current
        for cb in self._on_exit:
            cb(prev)
        self._current = target
        for cb in self._on_enter:
            cb(target)
