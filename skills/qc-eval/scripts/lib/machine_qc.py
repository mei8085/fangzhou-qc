"""Helpers for current-period machine-QC status fields."""

from __future__ import annotations

import json
from pathlib import Path


MACHINE_QC_NORMAL_HEADERS = ("机评是否正常", "机评是否正常显示")


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _trajectory_result(audit: dict) -> dict | None:
    ai_qc = audit.get("aiQc") if isinstance(audit.get("aiQc"), dict) else {}
    trajectory = ai_qc.get("trajectoryResult") or audit.get("trajectoryResult")
    return trajectory if isinstance(trajectory, dict) else None


def has_returned_machine_qc_result(audit: dict) -> bool:
    """Return True only when the machine QC completed with a usable grade."""
    trajectory = _trajectory_result(audit)
    if not trajectory or trajectory.get("status") != "success":
        return False
    result_json = trajectory.get("resultJson")
    return isinstance(result_json, dict) and bool(result_json.get("FeedbackGrade"))


def machine_qc_normal_for_task(repo_root: Path, task_id: str) -> str | None:
    """Return 是/否 for the task-level machine-QC display column.

    The sheet column is task-level: it is 是 only when every submitted model has
    a completed machine-QC result. Missing audit files, failed/exhausted jobs, or
    status without FeedbackGrade are treated as no returned result and therefore
    否. Missing expected models are skipped because there is no model run to
    evaluate.
    """
    task_dir = repo_root / "tasks" / str(task_id)
    model_map = _read_json(task_dir / "model_map.json")
    if not model_map:
        return None

    eligible = 0
    for row in (model_map.get("models") or {}).values():
        if not isinstance(row, dict):
            continue
        if row.get("missing"):
            continue
        run_id = str(row.get("task_model_run_id") or "").strip()
        platform = str(row.get("platform") or "").strip()
        if not run_id or not platform:
            continue
        eligible += 1
        audit = _read_json(task_dir / "ark_g1" / f"{run_id}__{platform}" / "audit.json")
        if not audit or not has_returned_machine_qc_result(audit):
            return "否"

    if eligible == 0:
        return None
    return "是"
