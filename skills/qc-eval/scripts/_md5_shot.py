"""Render md5 comparison PNG for Opus 4.7 (PDCOF) verify screenshot."""

import hashlib
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.fonts import CJK_FONT_CANDIDATES, MONO_FONT_CANDIDATES, load_font  # noqa: E402

REPO = HERE.parent.parent.parent
SRC = REPO / "tasks" / "6GPZWM" / "extracted" / "source"
DUT = REPO / "tasks" / "6GPZWM" / "extracted" / "PDCOF"
OUT = REPO / "delivery" / "6GPZWM" / "screenshots" / "Opus_4.7_01_md5_diff.png"


def md5_of(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def size_of(p: Path) -> int:
    return p.stat().st_size


def find_font(size: int, mono: bool = False):
    pool = MONO_FONT_CANDIDATES if mono else CJK_FONT_CANDIDATES
    return load_font(pool, size)


def main():
    files = [
        ("main.py", SRC / "main.py", DUT / "main.py"),
        ("trades.csv", SRC / "trades.csv", DUT / "trades.csv"),
    ]

    W, H = 1440, 720
    bg = (11, 15, 25)
    panel = (24, 30, 46)
    fg = (232, 236, 244)
    dim = (150, 160, 180)
    ok_red = (232, 90, 90)
    accent = (94, 176, 255)
    div = (48, 56, 78)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    title = find_font(30)
    subtitle = find_font(18)
    label = find_font(18)
    mono_lg = find_font(22, mono=True)
    mono_md = find_font(18, mono=True)

    draw.text((40, 32), "Opus 4.7 (PDCOF) 复测：产物 vs 起始代码 md5 对比",
              font=title, fill=fg)
    draw.text((40, 74),
              "路径：tasks/6GPZWM/extracted/{source,PDCOF}/  (source 为出题起始代码，PDCOF 为 Opus 4.7 交回产物)",
              font=subtitle, fill=dim)

    y = 130
    row_h = 250
    for name, src, dut in files:
        draw.rectangle([(30, y), (W - 30, y + row_h - 20)], fill=panel, outline=div, width=1)

        draw.text((52, y + 20), f"文件  {name}", font=title, fill=accent)

        s_md5 = md5_of(src)
        d_md5 = md5_of(dut)
        same = s_md5 == d_md5
        s_size = size_of(src)
        d_size = size_of(dut)

        draw.text((52, y + 74), "source (起始代码)", font=label, fill=dim)
        draw.text((52, y + 100), f"md5  {s_md5}", font=mono_lg, fill=fg)
        draw.text((52, y + 132), f"size {s_size} bytes", font=mono_md, fill=dim)

        draw.text((720, y + 74), "PDCOF (Opus 4.7 产物)", font=label, fill=dim)
        draw.text((720, y + 100), f"md5  {d_md5}", font=mono_lg, fill=fg)
        draw.text((720, y + 132), f"size {d_size} bytes", font=mono_md, fill=dim)

        verdict = "IDENTICAL — 逐字节完全相同，模型未做任何改动" if same else "DIFFERENT"
        vcolor = ok_red if same else (140, 200, 130)
        draw.text((52, y + 180), verdict, font=label, fill=vcolor)

        y += row_h

    footer = ("PDCOF 目录仅有 main.py 与 trades.csv 两个文件，md5 与 source 完全一致；"
              "无 Flask 后端、无前端 dashboard、无 SQLite、无 Docker，交付零内容。")
    draw.text((40, H - 60), footer, font=subtitle, fill=dim)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"wrote: {OUT}")


if __name__ == "__main__":
    main()
