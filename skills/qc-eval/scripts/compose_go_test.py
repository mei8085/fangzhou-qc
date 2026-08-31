#!/usr/bin/env python3
"""Render Go test evidence PNGs for backend bug-fix QC tasks.

The script expects test logs already saved under tasks/<TASK_ID>/ as
logs_<CODE>_go_test*.txt, then creates per-model terminal and code-summary
panels under delivery/<TASK_ID>/screenshots/. Run compose.py afterwards to
build the *_verify.png composites.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from compose_cli import _FONT_CANDIDATES, load_font, render_panel as _render_panel, trim_panel  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())


def render_panel(text: str, out: Path, *, width: int = 1180, height: int = 1320) -> None:
    font = load_font(_FONT_CANDIDATES, 15)
    img = trim_panel(_render_panel(text, font, (width, height)))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def head_tail(text: str, max_lines: int = 62) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    keep_head = max_lines // 2
    keep_tail = max_lines - keep_head - 2
    return "\n".join(lines[:keep_head] + ["", f"... omitted {len(lines) - keep_head - keep_tail} lines ...", ""] + lines[-keep_tail:])


def grep_lines(path: Path, patterns: list[str], context: int = 2) -> str:
    if not path.exists():
        return f"{path.name} not found"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    hits: list[int] = []
    for i, line in enumerate(lines):
        if any(p in line for p in patterns):
            hits.append(i)
    selected: list[str] = []
    seen: set[int] = set()
    for hit in hits[:8]:
        for i in range(max(0, hit - context), min(len(lines), hit + context + 1)):
            if i in seen:
                continue
            seen.add(i)
            selected.append(f"{i + 1:>4}: {lines[i]}")
        selected.append("")
    return "\n".join(selected).strip() or "no matching lines"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    args = parser.parse_args()

    task_dir = REPO_ROOT / "tasks" / args.task_id
    model_map = json.loads((task_dir / "model_map.json").read_text(encoding="utf-8"))
    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"

    for col in model_map.get("sheet_columns", model_map["models"].keys()):
        code = model_map["models"][col]["code"]
        tag = safe_tag(col)
        log_candidates = sorted(task_dir.glob(f"logs_{code}_go_test*.txt"))
        log = log_candidates[0] if log_candidates else None
        log_text = log.read_text(encoding="utf-8", errors="replace") if log else "go test log not found"
        render_panel(head_tail(log_text), out_dir / f"{tag}_01_terminal_test.png")

        code_file = task_dir / "extracted" / code / "controller" / "channel_upstream_update.go"
        if not code_file.exists() and code == "1PFMT":
            code_file = task_dir / "extracted" / "1PFMT" / "controller" / "channel_upstream_update.go"
        snippets = grep_lines(
            code_file,
            [
                "targetInUpstream",
                "protectedLocalByMapping",
                "activeMappingSourceSet",
                "redirectSourceSet",
                "protectedRemoveSet",
                "regexp.Compile",
                "regexp.MatchString",
                "pendingAdd",
                "pendingRemove",
            ],
        )
        summary = (
            f"{args.task_id}  {col} ({code})\n"
            "Key implementation lines checked against the prompt\n\n"
            f"{snippets}\n"
        )
        render_panel(summary, out_dir / f"{tag}_02_test_code_summary.png")
        print(f"==> {col} ({code})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
