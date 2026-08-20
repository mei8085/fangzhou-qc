#!/usr/bin/env python3
"""Generate per-model platform QC fill-in text from tasks/<TASK_ID>/qc_cells.json.

Output:
    delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md

This file is for manually filling the Ark per-model QC form. It is local-only
and must not trigger Feishu writes.

Default audit reasons are short conclusions. Full evidence stays in the
feedback note. Per-model audit_reason/platform_audit_reason overrides the
default when a special explanation is needed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

HIGH_QUALITY = "\u9ad8\u8d28\u91cf"
QUALIFIED = "\u5408\u683c"
MID_QUALITY = "\u4e2d\u8d28\u91cf"
LOW_QUALITY = "\u4f4e\u8d28\u91cf"
UNQUALIFIED = "\u4e0d\u5408\u683c"
UNUSABLE = "\u4e0d\u53ef\u7528"
REDLINE = "\u7ea2\u7ebf"
TASK_HIGH = "\u9ad8"
TASK_MID = "\u4e2d"
TASK_LOW = "\u4f4e"
FULLY_USABLE = "\u5b8c\u5168\u53ef\u7528"
PARTLY_USABLE = "\u90e8\u5206\u53ef\u7528"
FULLY_UNUSABLE = "\u5b8c\u5168\u4e0d\u53ef\u7528"
DEFAULT_DIRTY_TAG = "\u975e\u810f\u6570\u636e"

PROMPT_QUALITY_MAP = {
    HIGH_QUALITY: TASK_HIGH,
    QUALIFIED: TASK_MID,
    MID_QUALITY: TASK_MID,
    LOW_QUALITY: TASK_LOW,
    UNQUALIFIED: UNUSABLE,
    UNUSABLE: UNUSABLE,
    REDLINE: UNUSABLE,
}

FEEDBACK_QUALITY_MAP = {
    HIGH_QUALITY: FULLY_USABLE,
    QUALIFIED: PARTLY_USABLE,
    PARTLY_USABLE: PARTLY_USABLE,
    UNQUALIFIED: FULLY_UNUSABLE,
    FULLY_UNUSABLE: FULLY_UNUSABLE,
    REDLINE: FULLY_UNUSABLE,
}


def load_qc(task_id: str, tasks_dir: Path) -> dict:
    path = tasks_dir / task_id / "qc_cells.json"
    if not path.exists():
        raise FileNotFoundError(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def platform_prompt_quality(value: str) -> str:
    value = str(value or "").strip()
    return PROMPT_QUALITY_MAP.get(value, value or TASK_HIGH)


def platform_feedback_quality(value: str) -> str:
    value = str(value or "").strip()
    return FEEDBACK_QUALITY_MAP.get(value, value or PARTLY_USABLE)


def audit_evidence_summary(note: str) -> str:
    text = str(note or "").strip()
    text = re.sub(r"^标注人给[^。；;]*[。；;]\s*", "", text)
    for lead in (
        "用户反馈指出",
        "用户反馈提到",
        "反馈指出",
        "反馈说明",
        "备注指出",
        "备注说明",
        "标注人指出",
        "标注人认为",
    ):
        idx = text.find(lead)
        if idx >= 0:
            text = text[idx + len(lead):].strip()
            break
    text = re.split(r"[。；;]", text, maxsplit=1)[0].strip(" ，,。；;")
    if len(text) > 54:
        text = text[:54].rstrip("，,、和及与") + "等问题"
    return text


def default_audit_reason(feedback_quality: str, dirty_tag: str, note: str = "") -> str:
    if dirty_tag == DEFAULT_DIRTY_TAG:
        dirty_part = "\u672a\u53d1\u73b0\u810f\u6570\u636e\u95ee\u9898"
    else:
        dirty_part = f"\u547d\u4e2d\u810f\u6570\u636e\u6807\u7b7e\uff1a{dirty_tag}"
    summary = audit_evidence_summary(note)
    if feedback_quality == FULLY_USABLE:
        if summary:
            return f"\u6807\u6ce8\u4eba\u53cd\u9988\u6307\u51fa{summary}\uff1b\u590d\u6838\u7ed3\u679c\u4e0e\u4e3b\u8981\u95ee\u9898\u4e00\u81f4\uff0c\u8f93\u51fa\u4ee3\u7801\u6216\u4ea7\u7269\u53ef\u590d\u6838\uff0c{dirty_part}\u3002"
        return f"\u54cd\u5e94\u5185\u5bb9\u7b26\u5408\u4efb\u52a1\u8981\u6c42\uff0c\u8f93\u51fa\u4ee3\u7801\u6216\u4ea7\u7269\u53ef\u590d\u6838\uff1b\u6807\u6ce8\u4eba\u53cd\u9988\u4e0e\u590d\u6838\u7ed3\u679c\u4e00\u81f4\uff0c{dirty_part}\u3002"
    if feedback_quality == PARTLY_USABLE:
        if summary:
            return f"\u6807\u6ce8\u4eba\u53cd\u9988\u4e3b\u8981\u6d89\u53ca{summary}\uff1b\u590d\u6838\u540e\u8be5\u95ee\u9898\u90e8\u5206\u6210\u7acb\u6216\u8bc1\u636e\u4e0d\u5b8c\u6574\uff0c\u8f93\u51fa\u4ee3\u7801\u6216\u4ea7\u7269\u4ecd\u53ef\u590d\u6838\uff0c{dirty_part}\u3002"
        return f"\u54cd\u5e94\u5185\u5bb9\u90e8\u5206\u7b26\u5408\u4efb\u52a1\u8981\u6c42\uff0c\u8f93\u51fa\u4ee3\u7801\u6216\u4ea7\u7269\u4ecd\u53ef\u590d\u6838\uff1b\u6807\u6ce8\u4eba\u53cd\u9988\u6709\u504f\u5dee\u6216\u8bc1\u636e\u4e0d\u5b8c\u6574\uff0c{dirty_part}\u3002"
    if summary:
        return f"\u6807\u6ce8\u4eba\u53cd\u9988\u4e3b\u8981\u6d89\u53ca{summary}\uff1b\u590d\u6838\u540e\u53cd\u9988\u4e0e\u4ea7\u7269\u8bc1\u636e\u5b58\u5728\u660e\u663e\u51b2\u7a81\u6216\u652f\u6491\u4e0d\u8db3\uff0c{dirty_part}\u3002"
    return f"\u54cd\u5e94\u5185\u5bb9\u660e\u663e\u504f\u79bb\u4efb\u52a1\u8981\u6c42\uff0c\u6216\u6807\u6ce8\u4eba\u53cd\u9988\u4e0e\u590d\u6838\u7ed3\u679c\u4e0d\u4e00\u81f4\uff1b\u53cd\u9988\u8bc1\u636e\u4e0d\u8db3\u4ee5\u652f\u6491\u7ed3\u8bba\uff0c{dirty_part}\u3002"


def compose_feedback_note(data: dict) -> str:
    note = str(data.get("platform_feedback_note") or data.get("note") or "").strip()
    if note.startswith("标注人给执行过程"):
        return note
    process = data.get("execution_process_score")
    artifact = data.get("execution_artifact_score")
    prefix = ""
    if process is not None or artifact is not None:
        process_text = "" if process is None else str(process).strip()
        artifact_text = "" if artifact is None else str(artifact).strip()
        if process_text and artifact_text:
            prefix = f"标注人给执行过程 {process_text} 分、执行产物 {artifact_text} 分。"
        elif process_text:
            prefix = f"标注人给执行过程 {process_text} 分。"
        elif artifact_text:
            prefix = f"标注人给执行产物 {artifact_text} 分。"
    if prefix and note:
        return f"{prefix}{note}"
    return prefix or note


def format_dirty_tag(value) -> str:
    if value is None:
        return DEFAULT_DIRTY_TAG
    if isinstance(value, list):
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return "\u3001".join(cleaned) if cleaned else DEFAULT_DIRTY_TAG
    text = str(value).strip()
    return text or DEFAULT_DIRTY_TAG


def dirty_tag_for(qc: dict, sheet: dict, model_name: str, data: dict) -> str:
    for key in ("dirty_tag", "dirty_tags", "platform_dirty_tag"):
        if key in data:
            return format_dirty_tag(data.get(key))
    for platform_qc in (qc.get("platform_qc") or {}, sheet.get("platform_qc") or {}):
        dirty_tags = platform_qc.get("dirty_tag") or platform_qc.get("dirty_tags") or {}
        if isinstance(dirty_tags, dict) and model_name in dirty_tags:
            return format_dirty_tag(dirty_tags.get(model_name))
    sheet_dirty_tags = sheet.get("dirty_tag") or sheet.get("dirty_tags") or {}
    if isinstance(sheet_dirty_tags, dict) and model_name in sheet_dirty_tags:
        return format_dirty_tag(sheet_dirty_tags.get(model_name))
    return DEFAULT_DIRTY_TAG


def render(task_id: str, qc: dict) -> str:
    sheet = qc.get("sheet") or {}
    task_title = qc.get("task_title") or sheet.get("task_title") or ""
    prompt_quality = platform_prompt_quality(sheet.get("prompt_quality"))
    prompt_note = str(sheet.get("prompt_quality_note") or "").strip()
    models = sheet.get("models") or {}

    lines: list[str] = []
    lines.append(f"# {task_id} \u6bcf\u6a21\u578b\u8d28\u68c0\u586b\u5199\u5185\u5bb9")
    lines.append("")
    if task_title:
        lines.append(f"\u4efb\u52a1\uff1a{task_title}")
        lines.append("")
    lines.append("## \u901a\u7528\u4efb\u52a1\u8d28\u91cf")
    lines.append("")
    lines.append(f"\u4efb\u52a1\u8d28\u91cf\uff1a{prompt_quality}")
    lines.append("")
    lines.append("\u4efb\u52a1\u8d28\u91cf\u5907\u6ce8\uff1a")
    lines.append("```text")
    lines.append(prompt_note)
    lines.append("```")
    lines.append("")

    for model_name, data in models.items():
        feedback_quality = platform_feedback_quality(data.get("rating"))
        note = compose_feedback_note(data)
        dirty_tag = dirty_tag_for(qc, sheet, model_name, data)
        audit_reason = str(data.get("audit_reason") or data.get("platform_audit_reason") or "").strip()
        if not audit_reason:
            audit_reason = default_audit_reason(feedback_quality, dirty_tag, note)

        lines.append(f"## {model_name}")
        lines.append("")
        lines.append(f"\u7528\u6237\u53cd\u9988\u8d28\u91cf\uff1a{feedback_quality}")
        lines.append("")
        lines.append("\u53cd\u9988\u8d28\u91cf\u5907\u6ce8\uff1a")
        lines.append("```text")
        lines.append(note)
        lines.append("```")
        lines.append("")
        lines.append("\u5ba1\u6838\u7406\u7531\uff1a")
        lines.append("```text")
        lines.append(audit_reason)
        lines.append("```")
        lines.append("")
        lines.append(f"\u810f\u6570\u636e\u6807\u7b7e\uff1a{dirty_tag}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_ids", nargs="+")
    parser.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    parser.add_argument("--delivery-dir", default=str(REPO_ROOT / "delivery"))
    args = parser.parse_args()

    tasks_dir = Path(args.tasks_dir)
    delivery_dir = Path(args.delivery_dir)
    for task_id in args.task_ids:
        qc = load_qc(task_id, tasks_dir)
        out_dir = delivery_dir / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{task_id}_model_qc_platform.md"
        out.write_text(render(task_id, qc), encoding="utf-8")
        print(f"  ==> {task_id}: wrote {out.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
