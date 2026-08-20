#!/usr/bin/env python3
"""Download a task's row + attachments from Feishu and lay them out under
tasks/<TASK_ID>/.

Usage:
    fetch.py <TASK_ID> [--url FEISHU_URL] [--profile PROFILE]

What it does:
    1. Resolve the Feishu wiki URL to a spreadsheet token.
    2. Look up the task row in Sheet2 by ID.
    3. Look up the matching row in Sheet3 by ID.
    4. Download:
         - the 评估链接 HTML attachment (from Sheet2)
         - source_<ID>.zip + per-model output zips (from Sheet3)
    5. Extract zips into tasks/<TASK_ID>/source/ and extracted/<model>/.
    6. Parse the eval HTML into labeler_feedback.json.

After this, a QC agent can read the source, extracted/, and labeler_feedback.json
to start verification.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib import feishu, sheet_layout, eval_html  # noqa: E402

DEFAULT_URL = "https://ecnuoc61gjml.feishu.cn/wiki/XlBSwTXyOiAtzJkGL0ScBXUqnOh"
DEFAULT_PROFILE = "quan"

REPO_ROOT = HERE.parent.parent.parent  # skills/qc-eval/scripts -> repo root


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id", help="task ID, e.g. XLVL42")
    p.add_argument("--url", default=os.environ.get("FEISHU_URL", DEFAULT_URL))
    p.add_argument("--profile", default=os.environ.get("LARK_PROFILE", DEFAULT_PROFILE))
    p.add_argument("--sheet2", default="Sheet2", help="sheet title with task rows")
    p.add_argument("--sheet3", default="Sheet3", help="sheet title with attachment zips")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"),
                   help="parent directory for per-task workspaces (default: <repo>/tasks)")
    p.add_argument("--keep-existing", action="store_true",
                   help="skip download if file already exists locally")
    args = p.parse_args()

    task_dir = Path(args.tasks_dir) / args.task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    print(f"==> resolving wiki → spreadsheet")
    spreadsheet_token = feishu.resolve_wiki_to_sheet(args.url, args.profile)
    print(f"    spreadsheet_token = {spreadsheet_token}")

    sheet2 = feishu.find_sheet(spreadsheet_token, args.sheet2, args.profile)
    sheet3 = feishu.find_sheet(spreadsheet_token, args.sheet3, args.profile)
    print(f"    {args.sheet2} = {sheet2.sheet_id} ({sheet2.row_count} rows)")
    print(f"    {args.sheet3} = {sheet3.sheet_id} ({sheet3.row_count} rows)")

    # --- Sheet2: full grid + header parsing ---
    print(f"==> reading {args.sheet2} header + rows")
    sheet2_values = feishu.read_range(
        spreadsheet_token, sheet2.sheet_id,
        f"A1:{sheet_layout.col_letter(sheet2.column_count - 1)}{sheet2.row_count}",
        args.profile,
    )
    s2_layout = sheet_layout.parse_sheet2(sheet2_values[0])
    id_idx = sheet_layout.col_letter_to_idx0(s2_layout.id_col)
    row_num = sheet_layout.find_row_by_id(sheet2_values, id_idx, args.task_id)
    if not row_num:
        print(f"ERROR: task {args.task_id!r} not found in {args.sheet2}", file=sys.stderr)
        return 2
    print(f"    found {args.task_id} at row {row_num}")

    row = sheet2_values[row_num - 1]
    (task_dir / "sheet2_row.json").write_text(
        json.dumps({
            "row": row_num,
            "task_id": args.task_id,
            "spreadsheet_token": spreadsheet_token,
            "sheet_id": sheet2.sheet_id,
            "layout": _layout_to_dict(s2_layout),
            "values": row,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- Download 评估链接 HTML ---
    eval_idx = sheet_layout.col_letter_to_idx0(s2_layout.eval_col)
    eval_cell = row[eval_idx] if len(row) > eval_idx else None
    html_path: Path | None = None
    if isinstance(eval_cell, list) and eval_cell:
        att = eval_cell[0]
        html_name = att.get("text") or f"{args.task_id}_task.html"
        html_name = Path(html_name).name  # strip any path prefix
        html_path = task_dir / html_name
        if html_path.exists() and args.keep_existing:
            print(f"    skip {html_name} (exists)")
        else:
            print(f"==> downloading eval HTML: {html_name} ({att.get('size', 0):,} bytes)")
            feishu.download_attachment(att["fileToken"], spreadsheet_token, html_path, args.profile)
    else:
        print(f"WARN: no 评估链接 attachment on row {row_num}")

    # --- Sheet3: header + locate row ---
    print(f"==> reading {args.sheet3} header + rows")
    sheet3_values = feishu.read_range(
        spreadsheet_token, sheet3.sheet_id,
        f"A1:{sheet_layout.col_letter(sheet3.column_count - 1)}{sheet3.row_count}",
        args.profile,
    )
    s3_layout = sheet_layout.parse_sheet3(sheet3_values[0])
    id3_idx = sheet_layout.col_letter_to_idx0(s3_layout.id_col)
    row3_num = sheet_layout.find_row_by_id(sheet3_values, id3_idx, args.task_id)
    if not row3_num:
        print(f"ERROR: task {args.task_id!r} not found in {args.sheet3}", file=sys.stderr)
        return 2
    row3 = sheet3_values[row3_num - 1]

    (task_dir / "sheet3_row.json").write_text(
        json.dumps({
            "row": row3_num,
            "task_id": args.task_id,
            "sheet_id": sheet3.sheet_id,
            "layout": {"source_col": s3_layout.source_col, "id_col": s3_layout.id_col, "models": s3_layout.models},
            "values": row3,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- Download source + per-model zips ---
    downloads: list[tuple[str, Path]] = []  # (model_or_source, local_zip_path)
    if s3_layout.source_col:
        si = sheet_layout.col_letter_to_idx0(s3_layout.source_col)
        cell = row3[si] if len(row3) > si else None
        if isinstance(cell, list) and cell:
            att = cell[0]
            name = Path(att.get("text") or f"source_{args.task_id}.zip").name
            local = task_dir / name
            if not (args.keep_existing and local.exists()):
                print(f"==> downloading {name} ({att.get('size', 0):,} bytes)")
                feishu.download_attachment(att["fileToken"], spreadsheet_token, local, args.profile)
            downloads.append(("__source__", local))

    for model_name, col in s3_layout.models.items():
        i = sheet_layout.col_letter_to_idx0(col)
        cell = row3[i] if len(row3) > i else None
        if not isinstance(cell, list) or not cell:
            print(f"    skip {model_name}: empty")
            continue
        att = cell[0]
        name = Path(att.get("text") or f"{args.task_id}_{model_name}.zip").name
        local = task_dir / name
        if local.exists() and args.keep_existing:
            print(f"    skip {name} (exists)")
        else:
            print(f"==> downloading {name} ({att.get('size', 0):,} bytes)")
            feishu.download_attachment(att["fileToken"], spreadsheet_token, local, args.profile)
        downloads.append((model_name, local))

    # --- Unzip ---
    source_dir = task_dir / "source"
    extracted_dir = task_dir / "extracted"
    for kind, zip_path in downloads:
        if kind == "__source__":
            _refresh_dir(source_dir)
            _unzip(zip_path, source_dir)
            print(f"    unpacked source → source/")
        else:
            target = extracted_dir / kind
            _refresh_dir(target)
            _unzip(zip_path, target)
            print(f"    unpacked {kind} → extracted/{kind}/")

    # --- Parse eval HTML ---
    if html_path and html_path.exists():
        print(f"==> parsing {html_path.name} → labeler_feedback.json")
        entries = eval_html.parse_eval_html(html_path.read_text(encoding="utf-8"))
        eval_html.write_json(entries, task_dir / "labeler_feedback.json")
        print(f"    parsed {len(entries)} model sections")
        for e in entries:
            scores = ", ".join(f"{s.name}={s.score}" for s in e.scores)
            print(f"      • {e.model_name}: {scores}, {len(e.bullets)} bullets")

    print(f"\n✓ task workspace ready: {task_dir}")
    return 0


def _layout_to_dict(layout: sheet_layout.Sheet2Layout) -> dict:
    return {
        "id_col": layout.id_col,
        "task_col": layout.task_col,
        "prompt_col": layout.prompt_col,
        "eval_col": layout.eval_col,
        "prompt_quality_col": layout.prompt_quality_col,
        "prompt_quality_note_col": layout.prompt_quality_note_col,
        "verifiable_col": layout.verifiable_col,
        "verifiable_reason_col": layout.verifiable_reason_col,
        "reviewer_col": layout.reviewer_col,
        "models": [
            {"name": m.name, "rating": m.rating, "screenshot": m.screenshot, "note": m.note}
            for m in layout.models
        ],
    }


def _refresh_dir(p: Path) -> None:
    if p.exists():
        shutil.rmtree(p)
    p.mkdir(parents=True, exist_ok=True)


def _unzip(zip_path: Path, target: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(target)


if __name__ == "__main__":
    raise SystemExit(main())
