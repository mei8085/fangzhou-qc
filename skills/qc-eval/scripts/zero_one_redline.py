"""Helpers for the reviewer-confirmed initial-empty-workspace redline."""

from __future__ import annotations

from copy import deepcopy
import re


NOTE = "题目触发0-1红线"
DIRTY_TAG = "用户问题:低质量任务"
REDLINE = "0-1题目，题目不合理"
REQUIRED_MODEL_COUNT = 4


def split_redline_options(value) -> list[str]:
    """Split the workbook's comma-like redline option list."""
    return [
        item.strip()
        for item in re.split(r"[，,；;、\n]+", str(value or ""))
        if item.strip()
    ]


def is_zero_one(sheet: dict) -> bool:
    """Only recognize an explicit 0-1 option; never infer it from missing files."""
    value = (
        sheet.get("redline_issue")
        or sheet.get("redline_problem")
        or sheet.get("red_flag_issue")
        or ""
    )
    return "0-1题目" in split_redline_options(value)


def delivery_sheet(sheet: dict, model_names=None) -> dict:
    """Normalize delivery values without mutating source scores or qc_cells."""
    if not is_zero_one(sheet):
        return sheet

    result = deepcopy(sheet)
    result.update(
        prompt_quality="不合格",
        prompt_quality_note=NOTE,
        redline_issue=REDLINE,
        redline_note=NOTE,
        is_normal_task="否",
        is_high_quality_task="否",
    )
    models = result.setdefault("models", {})
    names = list(model_names) if model_names is not None else list(models)
    for name in names:
        data = models.setdefault(name, {})
        data.update(
            rating="不合格",
            note=NOTE,
            platform_feedback_note=NOTE,
            audit_reason=NOTE,
            platform_audit_reason=NOTE,
            dirty_tag=DIRTY_TAG,
            dirty_tag_reason=NOTE,
            suppress_score_append=True,
        )
    result["platform_audit_reasons"] = "\n".join(
        f"{name}：{NOTE}" for name in names
    )
    return result
