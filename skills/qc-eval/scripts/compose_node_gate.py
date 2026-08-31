#!/usr/bin/env python3
"""针对 Node.js CLI 质量门禁类任务（如 KCW4AS 决策评测质量门禁改造）：
左栏 npm test 输出、右栏 decision:history --window CLI 输出，
合成 verify.png。

Outputs (under delivery/<TASK_ID>/screenshots/):
    <COL>_01_npm_test.png
    <COL>_02_window.png
    <COL>_verify.png
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from compose_cli import _FONT_CANDIDATES, load_font, render_panel, trim_panel
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent


def run_cmd(cmd: list[str], cwd: Path, timeout: int = 180) -> str:
    prompt = f"$ {shlex.join(cmd)}"
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        return f"{prompt}\n{out}".strip()
    except Exception as e:
        return f"{prompt}\n{e}".strip()
    out = (r.stdout or "") + (r.stderr or "")
    return f"{prompt}\n{out}".strip()


def compose_one(sheet_label: str, model_dir: Path, out_dir: Path) -> dict:
    mono = load_font(_FONT_CANDIDATES, 13)
    panel_w, panel_h = 950, 1400

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = sheet_label.replace(" ", "_")

    test_text = run_cmd(["npm", "test"], model_dir)
    window_text = run_cmd(
        ["npm", "run", "decision:history", "--", "--window", "--size", "5", "--drift-threshold", "5"],
        model_dir,
    )

    npm_png = out_dir / f"{tag}_01_npm_test.png"
    win_png = out_dir / f"{tag}_02_window.png"
    verify_png = out_dir / f"{tag}_verify.png"

    left = trim_panel(render_panel(test_text, mono, (panel_w, panel_h)))
    left.save(npm_png)
    right = trim_panel(render_panel(window_text, mono, (panel_w, panel_h)))
    right.save(win_png)

    gap = 8
    total_w = left.width + right.width + gap * 3
    total_h = max(left.height, right.height) + gap * 2
    composite = Image.new("RGB", (total_w, total_h), "black")
    composite.paste(left, (gap, gap))
    composite.paste(right, (gap + left.width + gap, gap))
    composite.save(verify_png)

    return {"npm_test": npm_png, "window": win_png, "verify": verify_png}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_id")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    task_dir = tasks_dir / args.task_id
    map_path = task_dir / "model_map.json"
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(map_path.read_text(encoding="utf-8"))

    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    for col, info in mm["models"].items():
        code = info["code"]
        model_dir = task_dir / "extracted" / code
        print(f"==> {col} ({code})")
        outs = compose_one(col, model_dir, out_dir)
        for k, v in outs.items():
            print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
