#!/usr/bin/env python3
"""Merge missing Ark AI-QC results from docs/aiqc.xlsx into local task evidence.

This is a manually-triggered supplement step. It only patches the local
``audit.json``/``task.json`` cache and never evaluates feedback or writes Ark or
Feishu. After applying it, continue with the existing AI-QC accuracy workflow.

Examples:
    python3 skills/qc-eval/scripts/supplement_aiqc.py 9228
    python3 skills/qc-eval/scripts/supplement_aiqc.py 9228 --apply
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))

from lib.aiqc_supplement import (  # noqa: E402
    SupplementRecord,
    cell_text,
    load_supplement_records,
    merge_audit_trajectory,
    merge_task_summary,
    new_audit_cache,
)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"文件不存在：{path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 无法解析：{path}") from exc


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def model_by_run_id(model_map: dict, run_id: str) -> tuple[str, dict]:
    for sheet_model, row in (model_map.get("models") or {}).items():
        if cell_text(row.get("task_model_run_id") or row.get("run_id")) == run_id:
            return sheet_model, row
    raise ValueError(f"model_map.json 未找到 run_id={run_id}")


def audit_path(task_dir: Path, model_row: dict) -> Path:
    run_id = cell_text(model_row.get("task_model_run_id") or model_row.get("run_id"))
    platform = cell_text(model_row.get("platform"))
    if not run_id or not platform:
        raise ValueError(f"model_map 中模型记录缺少 run_id/platform：{model_row}")
    return task_dir / "ark_g1" / f"{run_id}__{platform}" / "audit.json"


def task_summary(task_dir: Path, records: list[SupplementRecord], apply: bool, force: bool) -> str:
    path = task_dir / "ark_g1" / "task.json"
    if not path.exists():
        return "skipped_missing"
    current = read_json(path)
    updated, action = merge_task_summary(current, records, force=force)
    if apply and action == "applied":
        write_json_atomic(path, updated)
    return action


def run(task_id: str, source: Path, *, apply: bool, force: bool) -> dict:
    task_dir = REPO_ROOT / "tasks" / str(task_id)
    if not task_dir.exists():
        raise FileNotFoundError(f"任务目录不存在：{task_dir}")
    model_map = read_json(task_dir / "model_map.json")
    records = load_supplement_records(source, str(task_id))
    actions: list[dict] = []
    for record in records:
        sheet_model, model_row = model_by_run_id(model_map, record.run_id)
        path = audit_path(task_dir, model_row)
        audit_preexisting = path.exists()
        audit = read_json(path) if audit_preexisting else new_audit_cache(str(task_id), model_row, record)
        updated, action = merge_audit_trajectory(audit, record, force=force)
        if apply and action == "applied":
            write_json_atomic(path, updated)
        actions.append(
            {
                "run_id": record.run_id,
                "model": sheet_model,
                "platform": cell_text(model_row.get("platform")),
                "grade": record.trajectory_grade,
                "status": record.trajectory_status,
                "audit": str(path.relative_to(REPO_ROOT)),
                "audit_preexisting": audit_preexisting,
                "action": action,
            }
        )

    summary_action = task_summary(task_dir, records, apply, force)
    report = {
        "task_id": str(task_id),
        "source": str(source.relative_to(REPO_ROOT) if source.is_relative_to(REPO_ROOT) else source),
        "mode": "apply" if apply else "dry_run",
        "force": force,
        "records": actions,
        "task_summary_action": summary_action,
        "generated_at": int(time.time() * 1000),
    }
    if apply:
        write_json_atomic(task_dir / "aiqc_supplement_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", help="任务 ID")
    parser.add_argument(
        "--source",
        default=str(REPO_ROOT / "docs" / "aiqc.xlsx"),
        help="AIQC 补充表路径，默认 docs/aiqc.xlsx",
    )
    parser.add_argument("--apply", action="store_true", help="实际写入本地 audit.json/task.json")
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已经有 success + FeedbackGrade 的本地 AIQC 结果，默认跳过",
    )
    args = parser.parse_args()
    source = Path(args.source).expanduser().resolve()
    try:
        report = run(args.task_id, source, apply=args.apply, force=args.force)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    print(
        f"==> {'写入' if args.apply else '预览'}任务 {args.task_id} AIQC 补充结果 "
        f"（来源 {source}）"
    )
    for item in report["records"]:
        print(
            f"   {item['model']} ({item['platform']}, run_id={item['run_id']}): "
            f"{item['action']} -> {item['status']}/{item['grade']}"
        )
    print(f"   task.json: {report['task_summary_action']}")
    if args.apply:
        print(f"   report: tasks/{args.task_id}/aiqc_supplement_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
