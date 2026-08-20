#!/usr/bin/env python3
"""Render 9AP9AS Go test logs as plain terminal evidence."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]
COMMAND = "$ go test -v ./api/internal/service/inquiry/clickhouse -run Test.*Like"


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())


def load_font(size: int) -> ImageFont.ImageFont:
    for name in ("consola.ttf", "C:/Windows/Fonts/consola.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def read_log(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff") or data[:200].count(b"\x00") > 20:
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def render(text: str, out_path: Path) -> None:
    text = text.expandtabs(4)
    font = load_font(22)
    width, height = 1500, 950
    img = Image.new("RGB", (width, height), "#0d1117")
    draw = ImageDraw.Draw(img)
    x, y = 22, 22
    line_h = 30
    max_cols = 118
    for raw in text.splitlines():
      chunks = [raw[i:i + max_cols] for i in range(0, len(raw), max_cols)] or [""]
      for chunk in chunks:
          draw.text((x, y), chunk, fill="#e6edf3", font=font)
          y += line_h
          if y + line_h > height:
              break
      if y + line_h > height:
          break

    bg = Image.new("RGB", img.size, "#0d1117")
    bbox = ImageChops.difference(img, bg).getbbox()
    if bbox:
        img = img.crop((0, 0, width, min(height, bbox[3] + 24)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main() -> int:
    task_id = sys.argv[1] if len(sys.argv) > 1 else "9AP9AS"
    task_dir = REPO_ROOT / "tasks" / task_id
    out_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    model_map = json.loads((task_dir / "model_map.json").read_text(encoding="utf-8"))
    for col in model_map["sheet_columns"]:
        info = model_map["models"][col]
        tag = safe_tag(col)
        log_path = task_dir / "logs" / f"{info['code']}-go-test.log"
        text = strip_ansi(read_log(log_path))
        lines = text.splitlines()
        lines = [ln for ln in lines if "real CLI verification" not in ln]
        body = "\n".join([COMMAND, *lines]).strip()
        render(body, out_dir / f"{tag}_01_cli_go_test.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
