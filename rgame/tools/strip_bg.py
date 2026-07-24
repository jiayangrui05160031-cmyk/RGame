"""
去背景脚本：将生成图的纯色背景转为RGBA透明
用法：
    python strip_bg.py <input.png> [threshold=240]
策略：把 RGB 中接近白色(>threshold)或纯黑(0)的像素 alpha 设为 0
"""
import sys
from pathlib import Path
from PIL import Image


def strip_background(input_path: str, threshold: int = 240) -> None:
    p = Path(input_path)
    img = Image.open(p).convert("RGBA")
    pixels = img.load()
    w, h = img.size
    made_transparent = 0
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            # 接近白色
            if r >= threshold and g >= threshold and b >= threshold:
                pixels[x, y] = (r, g, b, 0)
                made_transparent += 1
            # 纯黑色背景（不是深色描边！）
            elif r <= 5 and g <= 5 and b <= 5:
                pixels[x, y] = (r, g, b, 0)
                made_transparent += 1
    img.save(p)
    total = w * h
    print(f"  -> {p.name}: {made_transparent}/{total} px 透明化 ({100*made_transparent/total:.1f}%)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python strip_bg.py <input.png> [threshold=240]")
        sys.exit(1)
    thresh = int(sys.argv[2]) if len(sys.argv) > 2 else 240
    strip_background(sys.argv[1], thresh)
