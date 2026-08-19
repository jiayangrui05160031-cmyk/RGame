"""Pure and low-level rendering contract tests."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from rgame.enemies.enemies import spawn_enemy
from rgame.render import pygame_app


def test_damage_number_layout_spreads_same_position_and_fades() -> None:
    items = [
        {"position": (100.0, 100.0), "time": 10.0},
        {"position": (100.0, 100.0), "time": 10.0},
    ]

    layout = pygame_app.RGameApp._layout_damage_numbers(items, 10.05)

    assert layout[0]["x_offset"] == 0
    assert layout[1]["x_offset"] == 14
    assert layout[0]["scale"] > 1.0
    assert layout[0]["alpha"] == 255
    assert pygame_app.RGameApp._layout_damage_numbers(items, 10.8)[0]["alpha"] < 255


def test_ui_font_cache_reuses_same_scaled_font() -> None:
    pygame.init()
    try:
        pygame_app._app_state.ui_scale = 1.0
        pygame_app._font_cache.clear()
        first = pygame_app.get_ui_font(18)
        second = pygame_app.get_ui_font(18)
        assert first is second
    finally:
        pygame.quit()


def test_world_render_handles_spawned_enemy_states(tmp_path) -> None:
    app = pygame_app.RGameApp(
        seed=42,
        platform="linux",
        save_path=str(tmp_path / "profile.json"),
        log_path=str(tmp_path / "run.log"),
    )
    try:
        app.login_active = False
        app.engine.start_run(preset_id="preset_balanced")
        cfg = app.engine.bundle.enemies["spinner_chaser"]
        # 覆盖满血 / 半血破损（damage1）/ 重伤裂甲（damage2）/ 时间形态 T2 四条渲染路径，
        # 防止再次出现 enemy_sprite 中 frames 未定义导致的 UnboundLocalError。
        for i, (hp_ratio, time_form) in enumerate(
            ((1.0, "T0"), (0.35, "T0"), (0.12, "T0"), (1.0, "T2"))
        ):
            enemy = spawn_enemy(
                config=cfg,
                position=(1200.0 + i * 40, 540.0),
                rng=app.engine.context.rng.get("enemy_spawn_rng"),
                time_form=time_form,
            )
            enemy.current_hp = enemy.max_hp * hp_ratio
            app.engine.spawn_director.enemies.append(enemy)
        app._render()
    finally:
        app.engine.logger.close()
        pygame.quit()


def test_enter_battle_first_poll_events_no_crash(tmp_path) -> None:
    """回归：进战斗后第一帧事件轮询不得抛 AttributeError。

    复现路径：启动 → 直接进入 RUNNING → 未产生任何按键/鼠标事件 →
    _poll_events() 触发 _update_mouse_movement()。修复前 _mouse_move_target
    只在事件处理器里赋值、__init__ 未初始化，菜单态短路不崩、战斗态必崩，
    表现为"进战斗界面直接卡死、键盘无响应"。
    """
    app = pygame_app.RGameApp(
        seed=7,
        platform="linux",
        save_path=str(tmp_path / "profile.json"),
        log_path=str(tmp_path / "run.log"),
    )
    try:
        app.login_active = False
        app.engine.start_run(preset_id="preset_balanced")
        # 关键：先跑若干帧菜单轮询，再进战斗，全程不投递任何事件
        for _ in range(3):
            app._poll_events()
            app.engine.tick(1 / 60)
        app._poll_events()  # 战斗态第一帧事件轮询（修复前在此抛 AttributeError）
        app.engine.tick(1 / 60)
        app._render()
    finally:
        app.engine.logger.close()
        pygame.quit()
