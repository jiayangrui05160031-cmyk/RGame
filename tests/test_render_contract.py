"""Pure and low-level rendering contract tests."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

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
