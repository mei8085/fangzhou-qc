#!/usr/bin/env python3
"""Generate per-model Ark QC fill-in files from tasks/<TASK_ID>/qc_cells.json.

Output:
    delivery/<TASK_ID>/<TASK_ID>_model_qc_platform.md
    delivery/<TASK_ID>/<TASK_ID>_audit_form_fill.json

The markdown is for copying into the Ark per-model QC form. The JSON uses the
exact field labels from skills/qc-eval/config/g1_audit_form.json (captured from
review/12232?mode=audit). Both files are local-only and must not trigger Feishu
writes.

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
sys.path.insert(0, str(HERE))
from lib.g1 import (  # noqa: E402
    AUDIT_FORM_TEMPLATE,
    DEFAULT_DIRTY_TAG,
    SHEET_MODELS,
    SHEET_TO_PLATFORM,
    audit_url_for_run,
    load_g1_config,
)

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
EMPTY_DIRTY_DISPLAY = "\u4e0d\u9009\uff08\u9875\u9762\u65e0\u300c\u975e\u810f\u6570\u636e\u300d\u6309\u94ae\uff0c\u7559\u7a7a\u5373\u975e\u810f\u6570\u636e\uff09"

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


def load_audit_form_template() -> dict:
    """Load the G1 QC form schema captured from the Ark audit page."""
    if not AUDIT_FORM_TEMPLATE.exists():
        return {}
    return json.loads(AUDIT_FORM_TEMPLATE.read_text(encoding="utf-8"))


def dirty_field_spec(template: dict | None = None) -> dict:
    """Return the dirty-tag field definition from the form template."""
    template = template or load_audit_form_template()
    for field in (template.get("qc_form") or {}).get("fields") or []:
        if field.get("key") == "dirty_tags":
            return field
    return {}


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
    if dirty_tag in ("", DEFAULT_DIRTY_TAG, EMPTY_DIRTY_DISPLAY):
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


def raw_dirty_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[、,，;/|]+", text) if part.strip()]


def map_dirty_tags_to_platform(values) -> list[str]:
    """Map Feishu/spec dirty-tag names onto the exact Ark QC form options."""
    spec = dirty_field_spec()
    aliases = spec.get("aliases") or {}
    options = spec.get("options") or []
    option_set = set(options)
    mapped: list[str] = []
    seen: set[str] = set()
    for raw in raw_dirty_values(values):
        if raw == DEFAULT_DIRTY_TAG:
            continue
        hits = aliases.get(raw)
        if hits is None:
            hits = aliases.get(raw.replace(" ", ""))
        if hits is None and raw in option_set:
            hits = [raw]
        if not hits:
            hits = ["其他"]
        for item in hits:
            if item and item not in seen:
                seen.add(item)
                mapped.append(item)
    return mapped


def format_dirty_tag(value) -> str:
    mapped = map_dirty_tags_to_platform(value)
    if mapped:
        return "\u3001".join(mapped)
    return EMPTY_DIRTY_DISPLAY


def dirty_tag_source(qc: dict, sheet: dict, model_name: str, data: dict):
    for key in ("dirty_tag", "dirty_tags", "platform_dirty_tag"):
        if key in data:
            return data.get(key)
    for platform_qc in (qc.get("platform_qc") or {}, sheet.get("platform_qc") or {}):
        dirty_tags = platform_qc.get("dirty_tag") or platform_qc.get("dirty_tags") or {}
        if isinstance(dirty_tags, dict) and model_name in dirty_tags:
            return dirty_tags.get(model_name)
    sheet_dirty_tags = sheet.get("dirty_tag") or sheet.get("dirty_tags") or {}
    if isinstance(sheet_dirty_tags, dict) and model_name in sheet_dirty_tags:
        return sheet_dirty_tags.get(model_name)
    return DEFAULT_DIRTY_TAG


def dirty_tag_for(qc: dict, sheet: dict, model_name: str, data: dict) -> str:
    return format_dirty_tag(dirty_tag_source(qc, sheet, model_name, data))


def load_model_map(task_id: str, tasks_dir: Path) -> dict:
    path = tasks_dir / task_id / "model_map.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def model_run_meta(model_name: str, model_map: dict) -> dict:
    info = ((model_map or {}).get("models") or {}).get(model_name) or {}
    run_id = info.get("task_model_run_id") or info.get("run_id")
    url = str(info.get("audit_url") or info.get("platform_url") or "").strip()
    if not url and run_id:
        url = audit_url_for_run(run_id)
    return {
        "sheet": model_name,
        "code": info.get("code") or "",
        "platform": info.get("platform") or SHEET_TO_PLATFORM.get(model_name, ""),
        "task_model_run_id": run_id,
        "audit_url": url,
    }


def ordered_model_names(sheet: dict) -> list[str]:
    models = sheet.get("models") or {}
    names = [name for name in SHEET_MODELS if name in models]
    names.extend([name for name in models if name not in names])
    return names


def model_fill_row(qc: dict, model_name: str, model_map: dict) -> dict:
    sheet = qc.get("sheet") or {}
    data = (sheet.get("models") or {}).get(model_name) or {}
    meta = model_run_meta(model_name, model_map)
    prompt_quality = platform_prompt_quality(sheet.get("prompt_quality"))
    prompt_note = str(sheet.get("prompt_quality_note") or "").strip()
    feedback_quality = platform_feedback_quality(data.get("rating"))
    note = compose_feedback_note(data)
    dirty_source = dirty_tag_source(qc, sheet, model_name, data)
    dirty_tags = map_dirty_tags_to_platform(dirty_source)
    dirty_display = format_dirty_tag(dirty_source)
    audit_reason = str(data.get("audit_reason") or data.get("platform_audit_reason") or "").strip()
    if not audit_reason:
        audit_reason = default_audit_reason(feedback_quality, dirty_display, note)
    return {
        "sheet": model_name,
        "code": meta["code"],
        "platform": meta["platform"],
        "task_model_run_id": meta["task_model_run_id"],
        "audit_url": meta["audit_url"],
        "fields": {
            "请选择该任务的质量": prompt_quality,
            "任务质量备注": prompt_note,
            "请选择该用户的反馈质量": feedback_quality,
            "反馈质量备注": note,
            "审核理由": audit_reason,
            "请选择脏数据标签": dirty_tags,
        },
        "dirty_tag_display": dirty_display,
    }


def build_fill_payload(task_id: str, qc: dict, model_map: dict) -> dict:
    sheet = qc.get("sheet") or {}
    g1 = load_g1_config()
    rows = [model_fill_row(qc, name, model_map) for name in ordered_model_names(sheet)]
    first = rows[0]["fields"] if rows else {}
    example_url = str(g1.get("audit_url_template") or "")
    if "{taskModelRunId}" in example_url:
        example_url = example_url.format(taskModelRunId=12232)
    return {
        "task_id": task_id,
        "task_title": qc.get("task_title") or sheet.get("task_title") or "",
        "form_template": "skills/qc-eval/config/g1_audit_form.json",
        "source_example_url": example_url,
        "shared": {
            "请选择该任务的质量": first.get("请选择该任务的质量", ""),
            "任务质量备注": first.get("任务质量备注", ""),
        },
        "models": rows,
    }


def render(task_id: str, qc: dict, model_map: dict | None = None) -> str:
    sheet = qc.get("sheet") or {}
    task_title = qc.get("task_title") or sheet.get("task_title") or ""
    payload = build_fill_payload(task_id, qc, model_map or {})
    shared = payload["shared"]

    lines: list[str] = []
    lines.append(f"# {task_id} 平台质检表单填写")
    lines.append("")
    if task_title:
        lines.append(f"任务：{task_title}")
        lines.append("")
    lines.append("页面：每个模型打开 `projects/277/review/<taskModelRunId>?mode=audit`，右侧切到「质检」。")
    lines.append("字段名与选项与 `skills/qc-eval/config/g1_audit_form.json` 一致。")
    lines.append("")
    lines.append("## 通用 · 请选择该任务的质量")
    lines.append("")
    lines.append(f"请选择该任务的质量：{shared.get('请选择该任务的质量', '')}")
    lines.append("")
    lines.append("任务质量备注：")
    lines.append("```text")
    lines.append(shared.get("任务质量备注") or "")
    lines.append("```")
    lines.append("")

    for row in payload["models"]:
        fields = row["fields"]
        dirty_tags = fields.get("请选择脏数据标签") or []
        dirty_text = "、".join(dirty_tags) if dirty_tags else (
            row.get("dirty_tag_display") or EMPTY_DIRTY_DISPLAY
        )
        lines.append(f"## {row['sheet']} / {row.get('platform') or ''}")
        lines.append("")
        if row.get("audit_url"):
            lines.append(f"录入页：{row['audit_url']}")
            lines.append("")
        lines.append(f"请选择该任务的质量：{fields.get('请选择该任务的质量', '')}")
        lines.append("")
        lines.append("任务质量备注：")
        lines.append("```text")
        lines.append(fields.get("任务质量备注") or "")
        lines.append("```")
        lines.append("")
        lines.append(f"请选择该用户的反馈质量：{fields.get('请选择该用户的反馈质量', '')}")
        lines.append("")
        lines.append("反馈质量备注：")
        lines.append("```text")
        lines.append(fields.get("反馈质量备注") or "")
        lines.append("```")
        lines.append("")
        lines.append("审核理由：")
        lines.append("```text")
        lines.append(fields.get("审核理由") or "")
        lines.append("```")
        lines.append("")
        lines.append(f"请选择脏数据标签：{dirty_text}")
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
        model_map = load_model_map(task_id, tasks_dir)
        out_dir = delivery_dir / task_id
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / f"{task_id}_model_qc_platform.md"
        json_path = out_dir / f"{task_id}_audit_form_fill.json"
        md_path.write_text(render(task_id, qc, model_map), encoding="utf-8")
        json_path.write_text(
            json.dumps(build_fill_payload(task_id, qc, model_map), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  ==> {task_id}: wrote {md_path.relative_to(REPO_ROOT)}")
        print(f"  ==> {task_id}: wrote {json_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
