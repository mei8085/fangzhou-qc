#!/usr/bin/env python3
"""Upload per-model composite screenshots to Feishu Sheet2 screenshot cells.

For every model that has a tasks/<TASK_ID>/screenshots/<model>_composite.png,
embed it into the model's 验证截图 column at the task row.

Usage:
    push_images.py <TASK_ID> [--profile PROFILE] [--dry-run] [--only MODEL ...]
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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--profile", default=os.environ.get("LARK_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--only", nargs="+", help="only upload for these model names")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    task_dir = Path(args.tasks_dir) / args.task_id
    sheet2_meta = json.loads((task_dir / "sheet2_row.json").read_text(encoding="utf-8"))
    layout = sheet2_meta["layout"]
    row = sheet2_meta["row"]
    spreadsheet_token = sheet2_meta["spreadsheet_token"]
    sheet_id = sheet2_meta["sheet_id"]

    screens_root = task_dir / "screenshots"
    if not screens_root.exists():
        print(f"no screenshots dir: {screens_root}", file=sys.stderr)
        return 2

    target_models = set(args.only) if args.only else None

    uploaded = 0
    for m in layout["models"]:
        if target_models and m["name"] not in target_models:
            continue
        img_path = screens_root / f"{m['name']}_composite.png"
        if not img_path.exists():
            print(f"  skip {m['name']}: {img_path.name} missing")
            continue
        cell = f"{m['screenshot']}{row}"
        print(f"==> {cell}  <-  {img_path.name}")
        if args.dry_run:
            continue
        res = feishu.upload_image_to_cell(
            spreadsheet_token=spreadsheet_token,
            sheet_id=sheet_id,
            cell=cell,
            image_path=img_path,
            profile=args.profile,
            name=f"{args.task_id}_{m['name']}.png",
        )
        token = (res.get("data") or {}).get("file_token") or "?"
        print(f"    file_token = {token}")
        uploaded += 1
    if args.dry_run:
        print("(dry-run, nothing uploaded)")
    else:
        print(f"\n✓ uploaded {uploaded} composite(s) to row {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
