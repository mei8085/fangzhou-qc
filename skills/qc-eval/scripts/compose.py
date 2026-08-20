#!/usr/bin/env python3
"""Compose <COL>_verify.png from the individual <COL>_NN_*.png snapshots that
screenshot_vue.js (or any other per-state shooter) produced.

Layout style: no labels, captions, scaling, or artificial annotations. When a
model has only one evidence image, <COL>_verify.png is a byte-for-byte copy of
that original screenshot. Multiple images are pasted horizontally on a black
canvas, so shorter images leave plain black fill but no labels or padding
between images.

The xlsx 验证截图 column stays blank by convention; individual PNGs sit next to
this composite under delivery/<TASK_ID>/screenshots/ for inspection.

Usage:
    compose.py <TASK_ID>
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

GAP = 0


def compose_model(
    col: str,
    code: str,
    screenshots: list[Path],
    out_dir: Path,
    wrap_cols: int = 0,
) -> Path | None:
    tag = col.replace(" ", "_")
    out = out_dir / f"{tag}_verify.png"
    if not screenshots:
        print(f"   [skip] {col}: no individual PNGs found")
        return None

    if len(screenshots) == 1:
        shutil.copyfile(screenshots[0], out)
        return out

    imgs = [Image.open(p).convert("RGB") for p in screenshots]
    if wrap_cols and wrap_cols > 0:
        rows = [imgs[i:i + wrap_cols] for i in range(0, len(imgs), wrap_cols)]
        row_widths = [sum(im.width for im in row) + GAP * (len(row) - 1) for row in rows]
        row_heights = [max(im.height for im in row) for row in rows]
        total_w = max(row_widths)
        total_h = sum(row_heights) + GAP * (len(rows) - 1)
        canvas = Image.new("RGB", (total_w, total_h), "black")
        y = 0
        for row, row_h in zip(rows, row_heights):
            x = 0
            for im in row:
                canvas.paste(im, (x, y))  # top-aligned within each row
                x += im.width + GAP
            y += row_h + GAP
    else:
        total_w = sum(im.width for im in imgs) + GAP * (len(imgs) - 1)
        total_h = max(im.height for im in imgs)
        canvas = Image.new("RGB", (total_w, total_h), "black")
        x = 0
        for im in imgs:
            canvas.paste(im, (x, 0))  # top-aligned; shorter images leave transparent space
            x += im.width + GAP
    canvas.save(out)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--wrap-cols", type=int, default=0,
                   help="按指定列数换行排布；默认 0 为原横向拼接")
    args = p.parse_args()

    map_path = Path(args.tasks_dir) / args.task_id / "model_map.json"
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(map_path.read_text(encoding="utf-8"))

    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    for col, info in mm["models"].items():
        tag = col.replace(" ", "_")
        code = info["code"]
        cands = sorted(out_dir.glob(f"{tag}_*.png"))
        individuals = [p for p in cands if re.match(rf"{re.escape(tag)}_\d+_.+\.png$", p.name)]
        print(f"==> {col} ({code}): {len(individuals)} individual PNG(s)")
        out = compose_model(col, code, individuals, out_dir, wrap_cols=args.wrap_cols)
        if out:
            print(f"   -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
