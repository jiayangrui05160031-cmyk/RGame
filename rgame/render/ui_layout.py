from __future__ import annotations

from dataclasses import dataclass

import pygame


MIN_SCREEN_SIZE = (960, 540)
BASE_SIZE = (1280, 720)


def ui_scale(width: int, height: int) -> float:
    return max(0.75, min(1.25, min(width / BASE_SIZE[0], height / BASE_SIZE[1])))


def clamp_screen_size(width: int, height: int) -> tuple[int, int]:
    return max(MIN_SCREEN_SIZE[0], int(width)), max(MIN_SCREEN_SIZE[1], int(height))


@dataclass(frozen=True)
class LoginLayout:
    panel: pygame.Rect
    title: pygame.Rect
    subtitle: pygame.Rect
    input_box: pygame.Rect
    account_label: pygame.Rect
    option_rows: tuple[pygame.Rect, ...]
    login_button: pygame.Rect


@dataclass(frozen=True)
class CombatLayout:
    status: pygame.Rect
    stage: pygame.Rect
    score: pygame.Rect
    event: pygame.Rect
    build: pygame.Rect
    challenge: pygame.Rect
    skill: pygame.Rect
    weapons: tuple[pygame.Rect, ...]
    experience: pygame.Rect


def login_layout(width: int, height: int, option_count: int) -> LoginLayout:
    width, height = clamp_screen_size(width, height)
    s = ui_scale(width, height)
    panel_w = min(int(660 * s), width - int(72 * s))
    row_h = max(32, int(36 * s))
    row_gap = max(6, int(7 * s))
    top_h = int(205 * s)
    options_h = max(1, option_count) * row_h + max(0, option_count - 1) * row_gap
    button_h = max(46, int(52 * s))
    panel_h = top_h + options_h + int(92 * s)
    panel_h = min(panel_h, height - int(48 * s))
    panel = pygame.Rect(0, 0, panel_w, panel_h)
    panel.center = (width // 2, height // 2)
    inset = int(90 * s)
    content_w = panel.w - 2 * inset
    title = pygame.Rect(panel.x, panel.y + int(20 * s), panel.w, int(52 * s))
    subtitle = pygame.Rect(panel.x + inset // 2, title.bottom + int(2 * s), panel.w - inset, int(26 * s))
    input_box = pygame.Rect(panel.x + inset, subtitle.bottom + int(18 * s), content_w, max(50, int(58 * s)))
    account_label = pygame.Rect(input_box.x, input_box.bottom + int(4 * s), content_w, int(20 * s))
    first_y = account_label.bottom + int(4 * s)
    rows = tuple(
        pygame.Rect(input_box.x, first_y + i * (row_h + row_gap), content_w, row_h)
        for i in range(option_count)
    )
    login_button = pygame.Rect(0, 0, min(int(300 * s), content_w), button_h)
    login_button.centerx = panel.centerx
    login_button.bottom = panel.bottom - int(14 * s)
    return LoginLayout(panel, title, subtitle, input_box, account_label, rows, login_button)


def combat_layout(width: int, height: int, weapon_count: int = 3) -> CombatLayout:
    width, height = clamp_screen_size(width, height)
    s = ui_scale(width, height)
    margin = int(16 * s)
    status = pygame.Rect(margin, margin, int(252 * s), int(92 * s))
    stage = pygame.Rect(width // 2 - int(116 * s), margin, int(232 * s), int(66 * s))
    score = pygame.Rect(width - margin - int(280 * s), margin, int(280 * s), int(110 * s))
    event = pygame.Rect(width // 2 - int(235 * s), stage.bottom + int(8 * s), int(470 * s), int(54 * s))
    build = pygame.Rect(margin, status.bottom + int(10 * s), int(260 * s), int(92 * s))
    challenge = pygame.Rect(margin, height - margin - int(68 * s), int(360 * s), int(68 * s))
    slot_w, slot_h, gap = int(96 * s), int(64 * s), int(8 * s)
    total = weapon_count * slot_w + max(0, weapon_count - 1) * gap
    weapons_x = width - margin - total
    weapons_y = height - margin - slot_h
    weapons = tuple(pygame.Rect(weapons_x + i * (slot_w + gap), weapons_y, slot_w, slot_h) for i in range(weapon_count))
    skill = pygame.Rect(weapons_x - int(98 * s), weapons_y, int(86 * s), slot_h)
    experience = pygame.Rect(width // 2 - int(120 * s), height - margin - int(48 * s), int(240 * s), int(48 * s))
    return CombatLayout(status, stage, score, event, build, challenge, skill, weapons, experience)
