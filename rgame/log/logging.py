"""结构化日志。

按《日志与回放规范》：

- 每条结构化日志：``timestamp / logic_tick / run_id / run_seed / app_version /
  config_version / platform / state / event_id / event_type / payload / severity``；
- 默认摘要日志，深度日志由 build config 开启；
- 不记录隐私字段。
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any


class LogLevel:
    DEBUG = 10
    INFO = 20
    WARN = 30
    ERROR = 40


@dataclass
class LogEvent:
    timestamp: float
    logic_tick: int
    run_id: str
    run_seed: int
    app_version: str
    config_version: str
    platform: str
    state: str
    event_id: str
    event_type: str
    payload: dict
    severity: str = "info"


class StructuredLogger:
    """内存 + 可选文件日志。

    默认只把事件存到内存 deque，``maxlen`` 控制上限，避免长局无限增长；
    ``enable_disk=True`` 时同时写文件。
    """

    def __init__(
        self,
        *,
        run_id: str,
        run_seed: int,
        app_version: str,
        config_version: str,
        platform: str,
        maxlen: int = 4096,
        path: str | None = None,
        enable_disk: bool = False,
    ) -> None:
        self.run_id = run_id
        self.run_seed = run_seed
        self.app_version = app_version
        self.config_version = config_version
        self.platform = platform
        self.events: deque[LogEvent] = deque(maxlen=maxlen)
        self._tick = 0
        self._state = "BOOT"
        self._path = path
        self._fp = None
        if enable_disk and self._path:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            self._fp = open(self._path, "a", encoding="utf-8")

    def set_state(self, name: str) -> None:
        self._state = name

    def tick(self) -> None:
        self._tick += 1

    def log(self, *, event_type: str, payload: dict, severity: str = "info", event_id: str | None = None) -> LogEvent:
        ev = LogEvent(
            timestamp=time.time(),
            logic_tick=self._tick,
            run_id=self.run_id,
            run_seed=self.run_seed,
            app_version=self.app_version,
            config_version=self.config_version,
            platform=self.platform,
            state=self._state,
            event_id=event_id or f"{event_type}-{self._tick}",
            event_type=event_type,
            payload=payload,
            severity=severity,
        )
        self.events.append(ev)
        if self._fp is not None:
            try:
                self._fp.write(json.dumps({
                    "timestamp": ev.timestamp,
                    "tick": ev.logic_tick,
                    "state": ev.state,
                    "type": ev.event_type,
                    "payload": ev.payload,
                    "severity": ev.severity,
                }, ensure_ascii=False) + "\n")
                self._fp.flush()
            except Exception:
                pass
        return ev

    def close(self) -> None:
        if self._fp is not None:
            try:
                self._fp.close()
            finally:
                self._fp = None


class NullLogger:
    def set_state(self, *_a, **_kw): ...
    def tick(self): ...
    def log(self, **_kw): ...
    def close(self): ...


def create_logger(*, run_id: str, run_seed: int, app_version: str, config_version: str, platform: str, maxlen: int = 4096, path: str | None = None, enable_disk: bool = False) -> StructuredLogger:
    return StructuredLogger(
        run_id=run_id,
        run_seed=run_seed,
        app_version=app_version,
        config_version=config_version,
        platform=platform,
        maxlen=maxlen,
        path=path,
        enable_disk=enable_disk,
    )
