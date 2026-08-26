#!/usr/bin/env python3
"""顶层 Python 脚本类题目通用截图脚本：不像 pytest / <pkg>.cli，只是模型在项目根目录
产出一个可执行 .py 文件，用 `python <script>.py <args>` 直接跑；本脚本把输出渲染成
终端截图 + 合成图。

Outputs (under delivery/<TASK_ID>/screenshots/):
    <COL>_01_<label>.png   — 每次执行的终端输出（label 由 --label 指定，默认 run）
    <COL>_verify.png       — 多次执行的并排合成图

用法::

    compose_pyfile_cli.py <TASK_ID>
        --script preflight_check.py --script validate_briefing.py
        --run "<script> daily-codex-summary-2026-06-05.md" --label pass
        --run "<script> --help" --label help

`<script>` 会在每模型的 extracted 目录里按 `--script` 候选自动查找，第一个存在的就用。
`--run` 里的 `<script>` 会被替换为该模型实际找到的脚本名。多次 `--run` 就产出多张
子图，最后并排合成为 verify.png。
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
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

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def find_script(model_dir: Path, candidates: list[str]) -> str | None:
    for c in candidates:
        if (model_dir / c).is_file():
            return c
    return None


def run_cmd(model_dir: Path, cmd_argv: list[str], timeout: int) -> str:
    try:
        r = subprocess.run(
            [sys.executable, *cmd_argv],
            cwd=str(model_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"<timeout after {timeout}s>"
    except Exception as e:
        return f"<failed: {e}>"
    out = (r.stdout or "") + (r.stderr or "")
    return f"$ python {' '.join(cmd_argv)}\n(exit={r.returncode})\n\n" + strip_ansi(out).strip()


def compose_one(sheet_label: str, model_dir: Path, out_dir: Path,
                script_candidates: list[str], runs: list[tuple[str, str]],
                timeout: int) -> Path | None:
    mono = load_font(_FONT_CANDIDATES, 13)
    panel_w, panel_h = 950, 1600
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = sheet_label.replace(" ", "_")

    script = find_script(model_dir, script_candidates)
    if not script:
        text = "<script not found: tried " + ", ".join(script_candidates) + ">"
        pngs = [trim_panel(render_panel(text, mono, (panel_w, panel_h)))]
        labels = ["missing"]
    else:
        pngs = []
        labels = []
        for cmd_template, label in runs:
            argv_str = cmd_template.replace("<script>", script)
            argv = shlex.split(argv_str)
            out = run_cmd(model_dir, argv, timeout)
            png = trim_panel(render_panel(out, mono, (panel_w, panel_h)))
            pngs.append(png)
            labels.append(label)

    saved: list[Path] = []
    for idx, (img, lbl) in enumerate(zip(pngs, labels), start=1):
        p = out_dir / f"{tag}_{idx:02d}_{lbl}.png"
        img.save(p)
        saved.append(p)

    if not saved:
        return None
    gap = 8
    total_w = sum(im.width for im in pngs) + gap * (len(pngs) + 1)
    total_h = max(im.height for im in pngs) + gap * 2
    canvas = Image.new("RGB", (total_w, total_h), "black")
    x = gap
    for im in pngs:
        canvas.paste(im, (x, gap))
        x += im.width + gap
    verify = out_dir / f"{tag}_verify.png"
    canvas.save(verify)
    return verify


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("task_id")
    p.add_argument("--script", action="append", required=True,
                   help="脚本文件名候选（可多次；按顺序找第一个存在的）")
    p.add_argument("--run", action="append", required=True,
                   help='一次执行的命令行；`<script>` 会被替换成实际脚本名')
    p.add_argument("--label", action="append", required=True,
                   help="每次执行对应的短标签（用于文件名，与 --run 一一对应）")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    if len(args.run) != len(args.label):
        print("ERROR: --run 与 --label 数量必须一致", file=sys.stderr)
        return 2

    tasks_dir = Path(args.tasks_dir)
    task_dir = tasks_dir / args.task_id
    map_path = task_dir / "model_map.json"
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(map_path.read_text(encoding="utf-8"))
    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"

    runs = list(zip(args.run, args.label))
    for col, info in mm["models"].items():
        code = info["code"]
        entry = info.get("entry", ".")
        model_dir = task_dir / "extracted" / code
        if entry and entry != ".":
            model_dir = model_dir / entry
        print(f"==> {col} ({code})")
        v = compose_one(col, model_dir, out_dir, args.script, runs, args.timeout)
        if v:
            print(f"   -> {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
