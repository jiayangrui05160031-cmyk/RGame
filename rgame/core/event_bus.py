"""事件总线。

按《游戏总体流程》的最低事件集实现，提供：

- 单局内唯一 :class:`Event` 标识，避免重复结算；
- 同步订阅与触发；
- 历史回放所需的结构化载荷。
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class Event:
    """游戏内事件。

    Attributes:
        id: 全局或单局内唯一的标识，用于去重。
        type: 事件类型，例如 ``enemy_defeated`` / ``damage_applied``。
        payload: 稳定字段名的载荷字典。禁止使用自然语言描述。
        tick: 事件发生的逻辑步序号。
        timestamp: 事件发生的时间戳（秒，浮点）。
    """

    id: str
    type: str
    payload: dict = field(default_factory=dict)
    tick: int = 0
    timestamp: float = 0.0


@dataclass
class _Subscription:
    event_type: str
    callback: Callable[[Event], None]
    once: bool = False


class EventBus:
    """同步事件总线 + 单局去重。

    用法：

        bus = EventBus()
        bus.subscribe("enemy_defeated", lambda e: handle(e))
        bus.publish(Event(id="e1", type="enemy_defeated", payload={"enemy_id": "x"}))

    同 id 的事件第二次 ``publish`` 时会被丢弃，避免双结算。
    """

    def __init__(self) -> None:
        self._subs: list[_Subscription] = []
        self._by_type: dict[str, list[_Subscription]] = defaultdict(list)
        self._seen: dict[str, Event] = {}
        self._seen_lock = threading.Lock()
        self._history: list[Event] = []
        self._max_history = 4096

    # --- 订阅 --------------------------------------------------------------

    def subscribe(self, event_type: str, callback: Callable[[Event], None]) -> None:
        sub = _Subscription(event_type=event_type, callback=callback)
        self._subs.append(sub)
        self._by_type[event_type].append(sub)

    def subscribe_once(self, event_type: str, callback: Callable[[Event], None]) -> None:
        sub = _Subscription(event_type=event_type, callback=callback, once=True)
        self._subs.append(sub)
        self._by_type[event_type].append(sub)

    def clear_subscribers(self) -> None:
        self._subs.clear()
        self._by_type.clear()

    # --- 触发 --------------------------------------------------------------

    def publish(self, event: Event) -> bool:
        """触发事件。返回 ``False`` 表示同 id 重复被丢弃。"""
        with self._seen_lock:
            if event.id in self._seen:
                return False
            self._seen[event.id] = event
        self._history.append(event)
        if len(self._history) > self._max_history:
            del self._history[: len(self._history) - self._max_history]
        for sub in list(self._by_type.get(event.type, [])):
            try:
                sub.callback(event)
            finally:
                if sub.once:
                    self._by_type[sub.event_type].remove(sub)
                    self._subs.remove(sub)
        return True

    def has_seen(self, event_id: str) -> bool:
        with self._seen_lock:
            return event_id in self._seen

    def reset(self) -> None:
        """重置去重集合与历史（用于新开一局）。"""
        with self._seen_lock:
            self._seen.clear()
        self._history.clear()

    # --- 调试 --------------------------------------------------------------

    def history(self, event_type: str | None = None) -> list[Event]:
        if event_type is None:
            return list(self._history)
        return [e for e in self._history if e.type == event_type]

    @property
    def seen_event_ids(self) -> set[str]:
        with self._seen_lock:
            return set(self._seen.keys())

    def stats(self) -> dict[str, Any]:
        """调试用统计信息。"""
        by_type: dict[str, int] = defaultdict(int)
        for e in self._history:
            by_type[e.type] += 1
        return {
            "seen": len(self._seen),
            "history": len(self._history),
            "by_type": dict(by_type),
            "subscribers": len(self._subs),
        }
