"""核心：单局无关的基础设施——状态机、事件总线、命名随机流。

不依赖任何 GUI 与第三方渲染库，可独立用 pytest 进行规则测试。
"""

from .state_machine import State, StateMachine, StateError
from .event_bus import EventBus, Event
from .rng import NameRng, RngStream, make_rng_streams
from .run_context import RunContext, RunMode, RunStatus
from .time_keeper import TimeKeeper

__all__ = [
    "State",
    "StateMachine",
    "StateError",
    "EventBus",
    "Event",
    "NameRng",
    "RngStream",
    "make_rng_streams",
    "RunContext",
    "RunMode",
    "RunStatus",
    "TimeKeeper",
]
