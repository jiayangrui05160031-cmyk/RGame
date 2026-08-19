"""Generate the first RGame vertical-slice art pack.

The generated assets are original procedural prototypes, intentionally using the
project palette and transparent PNG conventions. They can be replaced later by
hand-painted or AI-produced art without changing the content IDs.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1] / "assets" / "v2"


def rgba(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGBA", size, (0, 0, 0, 0))


def polygon(draw: ImageDraw.ImageDraw, points, fill, outline=(8, 10, 16, 255), width=10):
    draw.polygon(points, fill=fill)
    draw.line(points + [points[0]], fill=outline, width=width, joint="curve")


def save_enemy_sheet(name: str, kind: str) -> None:
    sheet = rgba((2048, 2048))
    cell = 512
    for idx in range(8):
        frame = rgba((cell, cell))
        d = ImageDraw.Draw(frame)
        cx = cy = cell // 2
        bob = int(math.sin(idx * math.pi / 4) * 10)
        if kind == "leech":
            # Mineral parasite: dark shell, cyan core, orange crack energy.
            shell = (42, 65, 82, 255)
            core = (65, 225, 205, 255)
            hot = (255, 156, 66, 255)
            pts = [(cx, 82 + bob), (410, 170), (382, 370), (cx, 442 + bob), (130, 370), (102, 170)]
            polygon(d, pts, shell, width=12)
            d.ellipse((cx - 104, cy - 92 + bob, cx + 104, cy + 112 + bob), fill=(12, 28, 42, 255), outline=(8, 10, 16, 255), width=12)
            d.ellipse((cx - 62, cy - 57 + bob, cx + 62, cy + 67 + bob), fill=core, outline=(220, 255, 245, 255), width=8)
            for ray in range(6):
                a = ray * math.tau / 6 + idx * 0.08
                x1, y1 = cx + int(math.cos(a) * 70), cy + int(math.sin(a) * 70) + bob
                x2, y2 = cx + int(math.cos(a) * 154), cy + int(math.sin(a) * 154) + bob
                d.line((x1, y1, x2, y2), fill=hot, width=13)
            for side in (-1, 1):
                d.line((cx + side * 105, cy + bob, cx + side * 205, cy - 48 + bob), fill=hot, width=16)
        else:
            # Rail turret: heavy ring, exposed rail core, four stabilizer legs.
            steel = (66, 78, 102, 255)
            blue = (84, 225, 255, 255)
            violet = (148, 100, 255, 255)
            for a in range(0, 360, 90):
                rad = math.radians(a + idx * 2)
                x1, y1 = cx + int(math.cos(rad) * 152), cy + int(math.sin(rad) * 152)
                x2, y2 = cx + int(math.cos(rad) * 230), cy + int(math.sin(rad) * 230)
                d.line((x1, y1, x2, y2), fill=(8, 10, 16, 255), width=34)
                d.line((x1, y1, x2, y2), fill=steel, width=22)
            d.ellipse((88, 88 + bob, 424, 424 + bob), fill=steel, outline=(8, 10, 16, 255), width=14)
            d.ellipse((132, 132 + bob, 380, 380 + bob), fill=(18, 31, 52, 255), outline=violet, width=12)
            d.rounded_rectangle((cx - 26, 70 + bob, cx + 26, 442 + bob), radius=22, fill=blue, outline=(8, 10, 16, 255), width=10)
            d.line((cx, 112 + bob, cx, 400 + bob), fill=(240, 255, 255, 255), width=10)
            d.ellipse((cx - 38, cy - 38 + bob, cx + 38, cy + 38 + bob), fill=(255, 175, 75, 255), outline=(8, 10, 16, 255), width=8)
        x = (idx % 4) * cell
        y = (idx // 4) * cell
        sheet.alpha_composite(frame, (x, y))
    path = ROOT / "enemies" / f"{name}_sheet.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def save_weapon_icon(name: str, kind: str) -> None:
    img = rgba((256, 256))
    glow = rgba((256, 256))
    gd = ImageDraw.Draw(glow)
    d = ImageDraw.Draw(img)
    cx = cy = 128
    if kind == "railbow":
        gd.line((32, 214, 218, 42), fill=(65, 220, 255, 110), width=32)
        d.arc((40, 30, 222, 228), 204, 332, fill=(8, 10, 16, 255), width=28)
        d.arc((40, 30, 222, 228), 204, 332, fill=(86, 225, 255, 255), width=16)
        d.line((55, 205, 207, 53), fill=(8, 10, 16, 255), width=20)
        d.line((55, 205, 207, 53), fill=(255, 184, 88, 255), width=10)
        d.line((63, 197, 194, 66), fill=(245, 255, 255, 255), width=4)
        d.ellipse((190, 34, 234, 78), fill=(255, 214, 105, 255), outline=(8, 10, 16, 255), width=7)
    else:
        gd.ellipse((38, 38, 218, 218), outline=(255, 118, 55, 105), width=32)
        d.ellipse((48, 48, 208, 208), fill=(42, 55, 74, 255), outline=(8, 10, 16, 255), width=12)
        d.ellipse((82, 82, 174, 174), fill=(255, 101, 48, 255), outline=(255, 220, 150, 255), width=7)
        for i in range(4):
            a = i * math.tau / 4 + math.pi / 4
            x1, y1 = cx + int(math.cos(a) * 74), cy + int(math.sin(a) * 74)
            x2, y2 = cx + int(math.cos(a) * 108), cy + int(math.sin(a) * 108)
            d.line((x1, y1, x2, y2), fill=(255, 134, 60, 255), width=14)
        d.ellipse((108, 108, 148, 148), fill=(255, 250, 215, 255), outline=(8, 10, 16, 255), width=6)
    glow = glow.filter(ImageFilter.GaussianBlur(12))
    img.alpha_composite(glow)
    path = ROOT / "weapons" / f"weapon_{name}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def save_background(stage: int, palette: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
    w, h = 1920, 1080
    img = Image.new("RGBA", (w, h), (*palette, 255))
    px = img.load()
    for y in range(h):
        for x in range(w):
            vignette = ((x - w / 2) ** 2 + (y - h / 2) ** 2) ** 0.5 / 1200
            r = max(0, int(palette[0] + accent[0] * (1 - vignette) * 0.16))
            g = max(0, int(palette[1] + accent[1] * (1 - vignette) * 0.16))
            b = max(0, int(palette[2] + accent[2] * (1 - vignette) * 0.16))
            px[x, y] = (min(255, r), min(255, g), min(255, b), 255)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(-h, w, 96):
        d.line((x, 0, x + h, h), fill=(*accent, 38), width=2)
    for x in range(0, w, 192):
        d.line((x, 0, x, h), fill=(*accent, 24), width=2)
    for y in range(0, h, 192):
        d.line((0, y, w, y), fill=(*accent, 24), width=2)
    for i in range(18):
        x = (i * 317) % w
        y = 90 + (i * 197) % (h - 160)
        r = 4 + (i % 5) * 2
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*accent, 150))
    d.rectangle((24, 24, w - 24, h - 24), outline=(*accent, 125), width=5)
    path = ROOT / "backgrounds" / f"arena_bg_stage{stage}-v2.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> None:
    save_enemy_sheet("mine_leech", "leech")
    save_enemy_sheet("rail_turret", "turret")
    save_weapon_icon("railbow", "railbow")
    save_weapon_icon("ember_drone", "drone")
    save_background(4, (18, 42, 58), (60, 210, 170))
    save_background(5, (34, 22, 58), (186, 92, 255))
    print("generated: 2 enemy sheets, 2 weapon icons, 2 stage backgrounds")


if __name__ == "__main__":
    main()
