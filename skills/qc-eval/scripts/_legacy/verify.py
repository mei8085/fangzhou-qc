#!/usr/bin/env python3
"""Read back the QC cells from Feishu Sheet2 to confirm what is currently stored.

Usage:
    verify.py <TASK_ID> [--profile PROFILE]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import feishu  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
DEFAULT_PROFILE = "quan"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--profile", default=os.environ.get("LARK_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    task_dir = Path(args.tasks_dir) / args.task_id
    sheet2_meta = json.loads((task_dir / "sheet2_row.json").read_text(encoding="utf-8"))
    spreadsheet_token = sheet2_meta["spreadsheet_token"]
    sheet_id = sheet2_meta["sheet_id"]
    layout = sheet2_meta["layout"]
    row = sheet2_meta["row"]

    cells = []
    cells.append((layout["prompt_quality_col"] + str(row),       "出题质量"))
    cells.append((layout["prompt_quality_note_col"] + str(row),  "题目质量说明"))
    cells.append((layout["verifiable_col"] + str(row),           "是否可验证"))
    cells.append((layout["verifiable_reason_col"] + str(row),    "不可验证原因"))
    for m in layout["models"]:
        cells.append((m["rating"] + str(row),     f"{m['name']} 反馈质量"))
        cells.append((m["screenshot"] + str(row), f"{m['name']} 验证截图"))
        cells.append((m["note"] + str(row),       f"{m['name']} 质量备注"))
    if layout.get("reviewer_col"):
        cells.append((layout["reviewer_col"] + str(row), "质检人"))

    print(f"{'CELL':<6} {'FIELD':<35} CONTENT")
    print("-" * 80)
    for cell, label in cells:
        out = subprocess.run([
            "lark-cli", "--profile", args.profile, "sheets", "+cells-get",
            "--spreadsheet-token", spreadsheet_token,
            "--sheet-id", sheet_id,
            "--range", cell,
            "--jq", '.data.ranges[0].cells[0][0] | if .rich_text then "[img " + (.rich_text[0].image_token // "?") + "]" else (.value // "—") end',
        ], capture_output=True, text=True)
        val = (out.stdout or "").strip().strip('"')
        if len(val) > 50:
            val = val[:47] + "..."
        print(f"{cell:<6} {label:<35} {val}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
