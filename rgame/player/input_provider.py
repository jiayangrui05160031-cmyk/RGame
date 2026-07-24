"""输入抽象与键鼠 / 触屏实现。

按《玩家操作》§2 与《跨平台与手游适配》§3：

- 抽象 :class:`InputProvider`，键鼠 / 触屏 / 手柄实现；
- 每帧调用 :py:meth:`sample` 返回 :class:`InputAction`。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InputAction:
    """单帧输入汇总。"""

    move_x: float = 0.0
    move_y: float = 0.0
    switch_weapon: bool = False
    active_skill: bool = False
    weapon_index: Optional[int] = None
    pause_press: bool = False
    select_index: Optional[int] = None   # 关卡 / 卡牌选择序号
    refresh_card: bool = False
    attack_active_hint: float = 0.0       # 仅用于调试，不参与逻辑


class InputProvider:
    def sample(self) -> InputAction: ...
    def end_frame(self) -> None: ...


# 键盘输入（键按下 → 状态数组索引；每帧 scan 一次）
class KeyboardInputProvider(InputProvider):
    """依赖外部注入键状态，避免与 GUI 强耦合。

    :param key_state: ``{'w':True,...}`` 字典；调用方负责将 SDL/Pygame 按键
        投影成 ``w/a/s/d/esc/q/digits/enter`` 等规范键名。
    :param switch_requested: 当 ``True`` 时下一帧视为发生切换请求。
    """

    def __init__(self) -> None:
        self._state: dict[str, bool] = {}
        self._switch_requested = False
        self._active_skill_requested = False
        self._weapon_index_requested: Optional[int] = None
        self._pause_requested = False
        self._refresh_requested = False
        self._select_index_requested: Optional[int] = None
        self.last_pause = False
        self.last_switch = False
        self.last_select: Optional[int] = None

    def update_key(self, key: str, pressed: bool) -> None:
        self._state[key] = pressed

    def request_switch(self) -> None:
        self._switch_requested = True

    def request_active_skill(self) -> None:
        self._active_skill_requested = True

    def request_weapon_index(self, idx: int) -> None:
        self._weapon_index_requested = idx

    def request_pause(self) -> None:
        self._pause_requested = True

    def request_refresh(self) -> None:
        self._refresh_requested = True

    def request_select(self, idx: int) -> None:
        self._select_index_requested = idx

    def sample(self) -> InputAction:
        # 同方向求和；反向键相互抵消
        x = (1 if self._state.get("d") else 0) - (1 if self._state.get("a") else 0)
        y = (1 if self._state.get("s") else 0) - (1 if self._state.get("w") else 0)
        switch = self._switch_requested
        pause = self._pause_requested
        refresh = self._refresh_requested
        idx = self._select_index_requested
        return InputAction(
            move_x=float(x),
            move_y=float(y),
            switch_weapon=switch,
            active_skill=self._active_skill_requested,
            weapon_index=self._weapon_index_requested,
            pause_press=pause,
            refresh_card=refresh,
            select_index=idx,
        )

    def end_frame(self) -> None:
        self._switch_requested = False
        self._active_skill_requested = False
        self._weapon_index_requested = None
        self._pause_requested = False
        self._refresh_requested = False
        self._select_index_requested = None


# 虚拟摇杆 / 触屏按钮
class TouchInputProvider(InputProvider):
    """虚拟摇杆与按钮集合，按钮区域由外部 :class:`pygame` 事件映射。"""

    def __init__(
        self,
        *,
        joystick_center: tuple[float, float],
        joystick_radius: float = 90.0,
        joy_deadzone: float = 0.1,
        joystick_deadzone: float | None = None,
        switch_button_rect: tuple[float, float, float, float] = (0, 0, 0, 0),
        pause_button_rect: tuple[float, float, float, float] = (0, 0, 0, 0),
    ) -> None:
        # 兼容 ``joy_deadzone`` 与 ``joystick_deadzone`` 两种命名；
        # 仅当 ``joystick_deadzone`` 显式传入（非 None）时覆盖。
        if joystick_deadzone is not None:
            joy_deadzone = joystick_deadzone
        self.joy_center = joystick_center
        self.joy_radius = float(joystick_radius)
        self.joy_deadzone = float(joy_deadzone)
        self.switch_rect = switch_button_rect
        self.pause_rect = pause_button_rect
        self._stick_pos = joystick_center
        self._switch_pressed = False
        self._active_skill_pressed = False
        self._pause_pressed = False
        self._refresh_pressed = False
        self._select_index_requested: Optional[int] = None

    # --- 事件层 ---

    def on_touch(self, finger_id: int, pos: tuple[float, float], phase: str) -> None:
        x0, y0, w, h = self.switch_rect
        if x0 <= pos[0] <= x0 + w and y0 <= pos[1] <= y0 + h and phase == "down":
            self._switch_pressed = True
        x0, y0, w, h = self.pause_rect
        if x0 <= pos[0] <= x0 + w and y0 <= pos[1] <= y0 + h and phase == "down":
            self._pause_pressed = True
        # 摇杆
        jx, jy = self.joy_center
        d = math.hypot(pos[0] - jx, pos[1] - jy)
        if d <= self.joy_radius and phase in ("down", "motion"):
            self._stick_pos = pos

    def on_touch_release(self, finger_id: int) -> None:
        # 不严格按 finger_id，简单重置
        self._stick_pos = self.joy_center

    def request_refresh(self) -> None:
        self._refresh_pressed = True

    def request_active_skill(self) -> None:
        self._active_skill_pressed = True

    def request_select(self, idx: int) -> None:
        self._select_index_requested = idx

    # --- 读取层 ---

    def sample(self) -> InputAction:
        jx, jy = self.joy_center
        dx = self._stick_pos[0] - jx
        dy = self._stick_pos[1] - jy
        d = math.hypot(dx, dy)
        if d < self.joy_radius * self.joy_deadzone:
            mx, my = 0.0, 0.0
        else:
            mx = dx / self.joy_radius
            my = dy / self.joy_radius
            norm = math.hypot(mx, my)
            if norm > 1.0:
                mx /= norm
                my /= norm
        return InputAction(
            move_x=mx,
            move_y=my,
            switch_weapon=self._switch_pressed,
            active_skill=self._active_skill_pressed,
            pause_press=self._pause_pressed,
            refresh_card=self._refresh_pressed,
            select_index=self._select_index_requested,
        )

    def end_frame(self) -> None:
        self._switch_pressed = False
        self._active_skill_pressed = False
        self._pause_pressed = False
        self._refresh_pressed = False
        self._select_index_requested = None


class CompositeInputProvider(InputProvider):
    """组合：触屏和键鼠可同时接入，按位最大处理。"""

    def __init__(self, *providers: InputProvider) -> None:
        self.providers = list(providers)

    def sample(self) -> InputAction:
        out = InputAction()
        for p in self.providers:
            a = p.sample()
            # 移动向量取最大绝对值组合（同向取最大，反向自然取较大者）
            if abs(a.move_x) > abs(out.move_x):
                out.move_x = a.move_x
            if abs(a.move_y) > abs(out.move_y):
                out.move_y = a.move_y
            out.switch_weapon = out.switch_weapon or a.switch_weapon
            out.active_skill = out.active_skill or a.active_skill
            if a.weapon_index is not None:
                out.weapon_index = a.weapon_index
            out.pause_press = out.pause_press or a.pause_press
            out.refresh_card = out.refresh_card or a.refresh_card
            if a.select_index is not None:
                out.select_index = a.select_index
        return out

    def end_frame(self) -> None:
        for p in self.providers:
            p.end_frame()
