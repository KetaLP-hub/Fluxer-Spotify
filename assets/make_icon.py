"""Regenerates assets/icon.ico (the program icon). Needs Pillow: pip install pillow. Run from the repo root: python assets/make_icon.py

A green disc with a dark note on a dark rounded square - the same mark the launcher window shows in its header.
"""
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024  # drawn large, then scaled down for smooth edges
BG, GREEN, INK = (14, 16, 19, 255), (30, 215, 96, 255), (4, 19, 10, 255)
OUT = Path(__file__).resolve().parent / "icon.ico"


def draw():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=230, fill=BG)
    c, r = SIZE // 2, 372
    d.ellipse((c - r, c - r, c + r, c + r), fill=GREEN)
    # the note: head, stem, flag
    d.ellipse((340, 590, 540, 730), fill=INK)
    d.rectangle((500, 300, 548, 668), fill=INK)
    d.polygon([(548, 300), (704, 360), (724, 470), (664, 548), (690, 448), (548, 404)], fill=INK)
    return img


if __name__ == "__main__":
    big = draw()
    sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    big.save(OUT, format="ICO", sizes=sizes)
    big.resize((256, 256), Image.LANCZOS).save(OUT.with_suffix(".png"))
    print("written", OUT, "and", OUT.with_suffix(".png"))
