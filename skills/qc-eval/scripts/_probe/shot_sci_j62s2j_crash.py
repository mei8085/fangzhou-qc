#!/usr/bin/env python3
"""Focused crash screenshot for 6U7Q4 — one query, full traceback rendered as PNG."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO = Path("D:/fz/fangzhou/fangzhou")
TASK = "J62S2J"
OUT = REPO / "delivery" / TASK / "screenshots"
CWD = REPO / "tasks" / TASK / "extracted" / "6U7Q4"
COL = "30B-Release-Merge-0616E-29"

RUNNER = r"""
import sys, traceback
sys.path.insert(0, '.')
from sci_retrieval.pipeline import run_phase1_query_understanding
q = '基于图神经网络的多跳推理'
print('query:', q)
try:
    r = run_phase1_query_understanding(q)
    print('OK', r)
except Exception:
    traceback.print_exc()
"""


def render_text_png(title: str, subtitle: str, text: str, out_path: Path) -> None:
    try:
        font = ImageFont.truetype("consola.ttf", 18)
        font_title = ImageFont.truetype("consolab.ttf", 24)
        font_sub = ImageFont.truetype("consola.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
        font_title = font
        font_sub = font
    lines = text.splitlines()
    line_h = 24
    pad = 24
    max_line_w = 0
    for ln in [title, subtitle] + lines:
        try:
            bbox = font.getbbox(ln)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(ln) * 11
        if w > max_line_w:
            max_line_w = w
    W = max(1000, min(1900, max_line_w + pad * 2))
    H = pad * 2 + line_h * (len(lines) + 4)
    img = Image.new("RGB", (W, H), (12, 12, 12))
    d = ImageDraw.Draw(img)
    d.text((pad, pad), title, fill=(255, 100, 100), font=font_title)
    d.text((pad, pad + 34), subtitle, fill=(200, 200, 200), font=font_sub)
    y = pad + 34 + line_h + 8
    for ln in lines:
        color = (220, 220, 220)
        low = ln.lower()
        if "traceback" in low or "error" in low:
            color = (255, 120, 120)
        elif "file " in low and ".py" in low:
            color = (150, 200, 255)
        elif "valueerror" in low or "mismatch" in low:
            color = (255, 160, 60)
        elif ln.startswith("query:"):
            color = (140, 200, 255)
        d.text((pad, y), ln, fill=color, font=font)
        y += line_h
    img.save(out_path)


def main() -> int:
    proc = subprocess.run(
        [sys.executable, "-c", RUNNER],
        cwd=str(CWD),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )
    body = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    out = OUT / f"{COL}_03_crash.png"
    render_text_png(
        f"[{COL}] Phase 1 crash — topics/topic_store.py _search_numpy",
        f"cwd = extracted/6U7Q4    query = 基于图神经网络的多跳推理",
        body,
        out,
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
