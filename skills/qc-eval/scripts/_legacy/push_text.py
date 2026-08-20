#!/usr/bin/env python3
"""Write the QC text + rating cells to Feishu Sheet2.

Reads tasks/<TASK_ID>/qc_cells.json which the agent produces, then writes each
field to the right column based on the cached Sheet2 layout in sheet2_row.json.

Usage:
    push_text.py <TASK_ID> [--profile PROFILE] [--dry-run]

qc_cells.json shape:
{
  "prompt_quality":          "高（优秀）",
  "prompt_quality_note":     "...",
  "verifiable":              "是",
  "verifiable_reason":       "",
  "reviewer":                "quan",
  "models": {
    "60B-0614C-OPD":          {"rating": "高（优秀）", "note": "..."},
    ...
  }
}

Any field that is missing or set to null is skipped (not overwritten).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import feishu  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
DEFAULT_PROFILE = "quan"

VALID_RATINGS = {"高（优秀）", "中（中等）", "低（差）", "不可用（红线）"}
VALID_VERIFIABLE = {"是", "否"}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--profile", default=os.environ.get("LARK_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    task_dir = Path(args.tasks_dir) / args.task_id
    sheet2_meta = json.loads((task_dir / "sheet2_row.json").read_text(encoding="utf-8"))
    qc_path = task_dir / "qc_cells.json"
    if not qc_path.exists():
        print(f"missing {qc_path} — agent must write QC values first", file=sys.stderr)
        return 2
    qc = json.loads(qc_path.read_text(encoding="utf-8"))

    spreadsheet_token = sheet2_meta["spreadsheet_token"]
    sheet_id = sheet2_meta["sheet_id"]
    layout = sheet2_meta["layout"]
    row = sheet2_meta["row"]

    plans: list[tuple[str, str]] = []  # (cell_a1, value)

    if qc.get("prompt_quality") is not None:
        v = qc["prompt_quality"]
        if v not in VALID_RATINGS:
            print(f"WARN: prompt_quality {v!r} not in {VALID_RATINGS}", file=sys.stderr)
        plans.append((f"{layout['prompt_quality_col']}{row}", v))
    if qc.get("prompt_quality_note") is not None:
        plans.append((f"{layout['prompt_quality_note_col']}{row}", qc["prompt_quality_note"]))
    if qc.get("verifiable") is not None:
        v = qc["verifiable"]
        if v not in VALID_VERIFIABLE:
            print(f"WARN: verifiable {v!r} not in {VALID_VERIFIABLE}", file=sys.stderr)
        plans.append((f"{layout['verifiable_col']}{row}", v))
    if qc.get("verifiable_reason") not in (None, ""):
        plans.append((f"{layout['verifiable_reason_col']}{row}", qc["verifiable_reason"]))
    if qc.get("reviewer") is not None and layout.get("reviewer_col"):
        plans.append((f"{layout['reviewer_col']}{row}", qc["reviewer"]))

    model_layout = {m["name"]: m for m in layout["models"]}
    for name, mvals in (qc.get("models") or {}).items():
        if name not in model_layout:
            print(f"WARN: model {name!r} not in Sheet2 layout — skipping", file=sys.stderr)
            continue
        cols = model_layout[name]
        if mvals.get("rating") is not None:
            r = mvals["rating"]
            if r not in VALID_RATINGS:
                print(f"WARN: {name} rating {r!r} not in {VALID_RATINGS}", file=sys.stderr)
            plans.append((f"{cols['rating']}{row}", r))
        if mvals.get("note") is not None:
            plans.append((f"{cols['note']}{row}", mvals["note"]))

    if not plans:
        print("no cells to write")
        return 0

    print(f"==> writing {len(plans)} cells to row {row}")
    for cell, val in plans:
        preview = val if len(val) <= 60 else val[:57] + "..."
        print(f"    {cell}: {preview}")
        if args.dry_run:
            continue
        feishu.write_cells(
            spreadsheet_token=spreadsheet_token,
            sheet_id=sheet_id,
            a1=cell,
            cells=[[{"value": val}]],
            profile=args.profile,
            work_dir=task_dir,
        )
    if args.dry_run:
        print("(dry-run, nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
