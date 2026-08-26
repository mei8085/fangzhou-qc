#!/usr/bin/env python3
"""Compare annotator attribution tags with dimension remarks.

Run after collect, before writing qc_cells.json. Selected tags are part of
the annotator's evaluation and do not need to be repeated in remarks. Only
explicit tag/remark contradictions are wrong-tag issues: feedback quality
cannot be 高质量, and the QC note must name the contradiction.

Usage:
    python3 skills/qc-eval/scripts/check_annotator_tags.py <TASK_ID>
    python3 skills/qc-eval/scripts/check_annotator_tags.py --self-test

Exit codes:
    0  no tag/remark contradictions, or --self-test passed
    10 task has tag/remark contradictions (print them; QC must cover them)
    2  missing inputs or detector self-test failed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.annotator_tags import (  # noqa: E402
    iter_model_evaluations,
    self_test,
)
from lib.paths import REPO_ROOT  # noqa: E402

EXIT_CLEAN = 0
EXIT_MISMATCH = 10
EXIT_USAGE = 2


def write_summary(task_id: str, models: list[dict]) -> Path:
    """Write tasks/<TASK_ID>/annotator_tags.json for later QC steps."""
    path = REPO_ROOT / "tasks" / str(task_id) / "annotator_tags.json"
    payload = {
        "task_id": str(task_id),
        "models": models,
        "mismatch_count": sum(1 for row in models if row.get("mismatches")),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def print_model(row: dict) -> None:
    """Print one model's tags, remarks, and mismatch codes."""
    sheet = row.get("sheet") or ""
    platform = row.get("platform") or ""
    print(f"  {sheet} / {platform}")
    for dim in row.get("dimensions") or []:
        tags = "、".join(dim.get("tags") or []) or "（未选）"
        score = dim.get("score")
        print(f"    {dim.get('dimension')} {score}分 标签：{tags}")
        remark = str(dim.get("remark") or "").strip() or "（无维度备注）"
        print(f"      备注：{remark}")
        for item in dim.get("mismatches") or []:
            print(f"      [mismatch] {item}")
    if not row.get("mismatches"):
        print("    未发现标签与备注矛盾")


def main() -> int:
    """Scan one task or run the detector self-test."""
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="*")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        failures = self_test()
        if failures:
            print("  [BAD] annotator-tag detector")
            for item in failures:
                print(f"     {item}")
            return EXIT_USAGE
        print("  [OK]  annotator-tag detector")
        if not args.task_ids:
            return EXIT_CLEAN

    if not args.task_ids:
        parser.print_usage()
        return EXIT_USAGE

    worst = EXIT_CLEAN
    for task_id in args.task_ids:
        models = iter_model_evaluations(task_id)
        if not models:
            print(f"  [skip] {task_id}: no evaluation.json")
            continue
        summary = write_summary(task_id, models)
        mismatched = [row for row in models if row.get("mismatches")]
        if mismatched:
            print(f"  [mismatch] {task_id}  ({len(mismatched)} model(s))")
            for row in models:
                print_model(row)
            print(f"  wrote {summary.relative_to(REPO_ROOT)}")
            print("  标签与备注矛盾不能定高质量；质量备注必须点名不符之处。")
            worst = EXIT_MISMATCH
        else:
            print(f"  [OK]  {task_id}  no tag/remark contradictions")
            write_summary(task_id, models)
    return worst


if __name__ == "__main__":
    sys.exit(main())
