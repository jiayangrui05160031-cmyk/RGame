from __future__ import annotations

import os
from functools import lru_cache

import pygame

from . import theme as T


FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "DengXian", "SimHei")


def resolve_ui_font() -> str | None:
    """返回当前平台可用的首选中文 UI 字体路径。"""
    override = os.environ.get("RGAME_UI_FONT", "").strip()
    if override:
        matched = pygame.font.match_font(override)
        if matched:
            return matched
    for name in FONT_CANDIDATES:
        matched = pygame.font.match_font(name)
        if matched:
            return matched
    return None


@lru_cache(maxsize=48)
def font_cache(size: int, bold: bool = False) -> pygame.font.Font:
    path = resolve_ui_font()
    font = pygame.font.Font(path, max(8, int(size))) if path else pygame.font.Font(None, max(8, int(size)))
    font.set_bold(bool(bold))
    return font


def _text_width(font: pygame.font.Font, text: str) -> int:
    """测量文本像素宽度。

    Windows MSYS 沙箱里 pygame.font.size / render 偶尔会触发 SDL 内部
    access violation。fit_text 只比较"已超出 vs 未超出"，这里用
    font.get_linesize 做粗略估算，避开 native 路径。
    """
    if not text:
        return 0
    line = max(1, font.get_linesize())
    # CJK 字符通常比 ASCII 宽 50%
    cjk = sum(1 for c in text if ord(c) > 127)
    return line * len(text) + line * cjk // 2


def fit_text(text: str, font: pygame.font.Font, max_width: int) -> str:
    """把单行文字收敛到给定宽度，超出时使用省略号。"""
    value = str(text)
    if max_width <= 0 or not value:
        return ""
    if _text_width(font, value) <= max_width:
        return value
    ellipsis = "…"
    if _text_width(font, ellipsis) > max_width:
        return ""
    lo, hi = 0, len(value)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _text_width(font, value[:mid] + ellipsis) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return value[:lo] + ellipsis


def normalize_color(color) -> pygame.Color:
    """兼容 RGB/RGBA；绘制到普通 Surface 时明确丢弃 alpha。"""
    c = pygame.Color(*color) if isinstance(color, (tuple, list)) else pygame.Color(color)
    return pygame.Color(c.r, c.g, c.b)


def draw_text(
    surf: pygame.Surface,
    text,
    pos,
    *,
    size: int = 20,
    color=T.TEXT_PRIMARY,
    font: pygame.font.Font | None = None,
    outline: int = 0,
    outline_color=T.TEXT_OUTLINE,
    max_width: int | None = None,
):
    font = font or font_cache(size)
    value = str(text)
    if max_width is not None:
        value = fit_text(value, font, max_width)
    img = font.render(value, True, normalize_color(color))
    if outline > 0:
        shadow = font.render(value, True, normalize_color(outline_color))
        for ox, oy in (
            (-outline, 0), (outline, 0), (0, -outline), (0, outline),
            (-outline, -outline), (-outline, outline),
            (outline, -outline), (outline, outline),
        ):
            surf.blit(shadow, (pos[0] + ox, pos[1] + oy))
    surf.blit(img, pos)
    return img.get_width(), img.get_height()


def draw_text_center(
    surf: pygame.Surface,
    text,
    rect: pygame.Rect,
    *,
    color=T.TEXT_PRIMARY,
    font: pygame.font.Font | None = None,
    y_offset: int = 0,
    outline: int = 0,
    outline_color=T.TEXT_OUTLINE,
    max_width: int | None = None,
):
    font = font or font_cache(20)
    value = fit_text(str(text), font, max_width or max(0, rect.w - 12))
    img = font.render(value, True, normalize_color(color))
    x = rect.centerx - img.get_width() // 2
    y = rect.centery - img.get_height() // 2 + y_offset
    if outline > 0:
        shadow = font.render(value, True, normalize_color(outline_color))
        for ox, oy in (
            (-outline, 0), (outline, 0), (0, -outline), (0, outline),
            (-outline, -outline), (-outline, outline),
            (outline, -outline), (outline, outline),
        ):
            surf.blit(shadow, (x + ox, y + oy))
    surf.blit(img, (x, y))
    return img.get_width(), img.get_height()


def draw_panel(
    surf: pygame.Surface,
    rect: pygame.Rect,
    *,
    border=T.BLACK_OUTLINE,
    fill=T.BG_PANEL,
    alpha: int = 220,
    radius: int = 14,
    outline: int = 3,
):
    panel = pygame.Surface((max(1, rect.w), max(1, rect.h)), pygame.SRCALPHA)
    border_rgb = normalize_color(border)
    fill_rgb = normalize_color(fill)
    width, height = panel.get_size()
    cut = max(4, min(int(radius), width // 7, height // 4))

    def corners(inset: int, bevel: int):
        left, top = inset, inset
        right, bottom = width - inset, height - inset
        bevel = max(2, min(bevel, max(2, (right - left) // 4), max(2, (bottom - top) // 3)))
        return [
            (left + bevel, top), (right - bevel, top), (right, top + bevel),
            (right, bottom - bevel), (right - bevel, bottom), (left + bevel, bottom),
            (left, bottom - bevel), (left, top + bevel),
        ]

    pygame.draw.polygon(panel, border_rgb, corners(0, cut))
    if outline > 0:
        pygame.draw.polygon(panel, (*fill_rgb[:3], alpha), corners(outline, max(2, cut - outline)))
    else:
        pygame.draw.polygon(panel, (*fill_rgb[:3], alpha), corners(0, cut))
    pygame.draw.line(panel, (*T.ACCENT, min(112, alpha // 2)),
                     (cut + outline + 5, outline + 1), (width - cut - outline - 5, outline + 1), 1)
    # 两侧短刻线让面板读起来像舰载仪表，而不是通用圆角卡片。
    mark = min(12, max(4, width // 18))
    pygame.draw.line(panel, (*T.ACCENT_2, min(145, alpha)), (2, cut + 4), (2, cut + 4 + mark), 2)
    pygame.draw.line(panel, (*T.ACCENT_3, min(145, alpha)), (width - 3, height - cut - 4), (width - 3, height - cut - 4 - mark), 2)
    surf.blit(panel, rect.topleft)


def draw_button(
    surf: pygame.Surface,
    rect: pygame.Rect,
    label,
    *,
    font: pygame.font.Font,
    active: bool = False,
    accent=T.ACCENT,
    accent_fill=None,
):
    accent_rgb = normalize_color(accent_fill if accent_fill is not None else accent)
    fill = accent_rgb if active else normalize_color(T.BG_PANEL_ALT)
    draw_panel(
        surf, rect,
        border=accent_rgb if active else T.ACCENT,
        fill=fill,
        alpha=248 if active else 232,
        radius=12,
        outline=3,
    )
    inner = rect.inflate(-6, -6)
    if active:
        pygame.draw.line(surf, (255, 255, 255), (inner.x + 10, inner.y + 5), (inner.right - 10, inner.y + 5), 1)
    text_color = T.TEXT_DARK if active and sum(fill[:3]) > 470 else T.TEXT_PRIMARY
    draw_text_center(
        surf,
        label,
        rect,
        color=text_color,
        font=font,
        outline=0 if active else 1,
        max_width=max(0, rect.w - 18),
    )
