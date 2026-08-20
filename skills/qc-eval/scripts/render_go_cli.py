#!/usr/bin/env python3
"""Render actual Go CLI execution logs as evidence screenshots for local bundles."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())


def load_font(size: int) -> ImageFont.ImageFont:
    for name in (
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/consola.ttf",
        "DejaVuSansMono.ttf",
    ):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def read_log(path: Path) -> str:
    if not path.exists():
        return f"<missing log: {path.name}>"
    data = path.read_bytes()
    if not data:
        return "<no output>"
    return data.decode("utf-8", errors="replace")


def clean_terminal_text(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = text.replace("\r", "\n")
    text = text.translate(str.maketrans({"■": "=", "□": "-", "█": "=", "▇": "="}))
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)


def render_text(text: str, out_path: Path) -> None:
    font = load_font(22)
    width, height = 1500, 980
    bg = "#0d1117"
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    x, y = 22, 22
    line_h = 31
    max_cols = 118
    for raw in clean_terminal_text(text).splitlines():
        chunks = [raw[i : i + max_cols] for i in range(0, len(raw), max_cols)] or [""]
        for chunk in chunks:
            draw.text((x, y), chunk, fill="#e6edf3", font=font)
            y += line_h
            if y + line_h > height:
                break
        if y + line_h > height:
            break

    blank = Image.new("RGB", img.size, bg)
    bbox = ImageChops.difference(img, blank).getbbox()
    if bbox:
        img = img.crop((0, 0, width, min(height, bbox[3] + 24)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def render_model(task_dir: Path, out_dir: Path, col: str, code: str) -> None:
    tag = safe_tag(col)
    cli_log = read_log(task_dir / "logs" / f"{code}-cli-download.log")
    render_text(cli_log.strip(), out_dir / f"{tag}_01_cli_download.png")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = parser.parse_args()

    task_dir = Path(args.tasks_dir) / args.task_id
    model_map = json.loads((task_dir / "model_map.json").read_text(encoding="utf-8"))
    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    for col in model_map["sheet_columns"]:
        code = model_map["models"][col]["code"]
        print(f"==> {col} ({code})")
        render_model(task_dir, out_dir, col, code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
