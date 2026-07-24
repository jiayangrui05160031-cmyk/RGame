from __future__ import annotations

import pygame


def alpha_stats(surface: pygame.Surface) -> tuple[int, int, int]:
    """返回透明、半透明、不透明像素数量。"""
    surf = surface.convert_alpha()
    raw = pygame.image.tostring(surf, "RGBA")
    transparent = translucent = opaque = 0
    for alpha in raw[3::4]:
        if alpha == 0:
            transparent += 1
        elif alpha == 255:
            opaque += 1
        else:
            translucent += 1
    return transparent, translucent, opaque


def has_usable_transparency(surface: pygame.Surface, min_transparent_pixels: int = 16) -> bool:
    """图标/特效必须含真实透明像素；仅把模式改成 RGBA 不算透明素材。"""
    transparent, translucent, _opaque = alpha_stats(surface)
    if transparent + translucent < 1:
        return False
    if transparent + translucent >= max(1, int(min_transparent_pixels)):
        return True
    # 半透明像素极少时，仍要求 0.5% 的不透明不等于全画布。
    width, height = surface.get_size()
    total = max(1, width * height)
    return (transparent + translucent) / total >= 0.005
