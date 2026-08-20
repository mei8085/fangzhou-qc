#!/usr/bin/env python3
"""Python CLI 类题目通用截图脚本：跑 `python -m pytest` + `python -m <pkg>.cli <fixtures> --pretty`
渲染成每模型两张单图 + 一张并排合成图。

Outputs (under delivery/<TASK_ID>/screenshots/):
    <COL>_01_pytest.png    — terminal output of pytest
    <COL>_02_cli.png       — terminal output of CLI pretty run
    <COL>_verify.png       — side-by-side composite

Usage:
    compose_pytest_cli.py <TASK_ID> \
        --package refund_policy \
        --fixtures fixtures/refund_cases.json \
        [--cli-extra "--pretty"]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from compose_cli import (
    _FONT_CANDIDATES,
    load_font,
    render_panel,
    trim_panel,
)
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def run_pytest(model_dir: Path) -> str:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=model_dir,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except Exception as e:
        return f"<failed to run pytest: {e}>"
    out = (r.stdout or "") + (r.stderr or "")
    return _strip_ansi(out).strip()


def run_cli(model_dir: Path, package: str, fixtures: str, extra: list[str]) -> str:
    try:
        r = subprocess.run(
            [sys.executable, "-m", f"{package}.cli", fixtures, *extra],
            cwd=model_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        return f"<failed to run cli: {e}>"
    out = (r.stdout or "") + (r.stderr or "")
    return _strip_ansi(out).strip()


def compose_one(sheet_label: str, model_dir: Path, out_dir: Path, package: str, fixtures: str, cli_extra: list[str]) -> dict:
    mono = load_font(_FONT_CANDIDATES, 13)
    panel_w, panel_h = 950, 1600

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = sheet_label.replace(" ", "_")

    pytest_text = run_pytest(model_dir)
    cli_text = run_cli(model_dir, package, fixtures, cli_extra)

    pytest_png = out_dir / f"{tag}_01_pytest.png"
    cli_png = out_dir / f"{tag}_02_cli.png"
    verify_png = out_dir / f"{tag}_verify.png"

    left = trim_panel(render_panel(pytest_text, mono, (panel_w, panel_h)))
    left.save(pytest_png)
    right = trim_panel(render_panel(cli_text, mono, (panel_w, panel_h)))
    right.save(cli_png)

    gap = 8
    total_w = left.width + right.width + gap * 3
    total_h = max(left.height, right.height) + gap * 2
    composite = Image.new("RGB", (total_w, total_h), "black")
    composite.paste(left, (gap, gap))
    composite.paste(right, (gap + left.width + gap, gap))
    composite.save(verify_png)

    return {"pytest": pytest_png, "cli": cli_png, "verify": verify_png}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--package", required=True, help="Python package containing cli module (e.g. refund_policy)")
    p.add_argument("--fixtures", required=True, help="Relative path to fixtures file")
    p.add_argument("--cli-extra", default="--pretty", help="Extra CLI flags (default: --pretty)")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    task_dir = tasks_dir / args.task_id
    map_path = task_dir / "model_map.json"
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(map_path.read_text(encoding="utf-8"))

    cli_extra = args.cli_extra.split() if args.cli_extra else []
    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    for col, info in mm["models"].items():
        code = info["code"]
        model_dir = task_dir / "extracted" / code
        print(f"==> {col} ({code})")
        outs = compose_one(col, model_dir, out_dir, args.package, args.fixtures, cli_extra)
        for k, v in outs.items():
            print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
