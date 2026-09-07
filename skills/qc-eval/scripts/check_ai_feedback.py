#!/usr/bin/env python3
"""Require annotator-side evidence for AI feedback labels; never classify task self-tests."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lib.annotator_tags import evaluation_path_for_model
from lib.paths import REPO_ROOT


def has_ai_tag(value) -> bool:
    if isinstance(value, list):
        return any(has_ai_tag(item) for item in value)
    return "AI打分/AI评价" in re.sub(r"\s+", "", str(value or ""))


def evidence_issues(model: dict, evaluation: dict) -> list[str]:
    if not has_ai_tag(model.get("dirty_tag")):
        return []
    evidence = model.get("ai_feedback_evidence")
    if not isinstance(evidence, dict):
        return ["ai-feedback-missing-annotator-evidence"]
    if evidence.get("source") != "annotator_feedback":
        return ["ai-feedback-wrong-subject:task-self-evaluation-is-not-annotator-feedback"]
    quote = evidence.get("quote")
    reason = evidence.get("reason")
    if not isinstance(quote, str) or not quote.strip() or not isinstance(reason, str) or not reason.strip():
        return ["ai-feedback-requires-quote-and-attribution-reason"]
    # Only evaluator-owned fields count. Prompt, model output and report text
    # must not accidentally become evidence of the annotator's AI usage.
    annotation = evaluation.get("evaluation") or {}
    texts = [annotation.get("remark"), annotation.get("summary")]
    texts.extend(row.get("remark") for row in annotation.get("dimensionResults") or [])
    if not any(quote.strip() in text for text in texts if isinstance(text, str)):
        return ["ai-feedback-quote-not-in-annotator-feedback"]
    return []


def check_task(task_dir: Path, labels: dict | None = None) -> list[str]:
    qc = json.loads((task_dir / "qc_cells.json").read_text(encoding="utf-8"))
    models = (qc.get("sheet") or {}).get("models") or {}
    selected = set(models) | set(labels or {})
    mapping = None
    issues = []
    for name in selected:
        model = dict(models.get(name) or {})
        # Check both current QC and the actual outgoing artifact, including
        # stale generated files whose AI label was removed from qc_cells.
        if labels and has_ai_tag(labels.get(name)):
            model["dirty_tag"] = labels[name]
        if not has_ai_tag(model.get("dirty_tag")):
            continue
        if mapping is None:
            mapping = json.loads((task_dir / "model_map.json").read_text(encoding="utf-8"))
        path = evaluation_path_for_model(task_dir, name, (mapping.get("models") or {}).get(name) or {})
        evaluation = json.loads(path.read_text(encoding="utf-8")) if path else {}
        issues.extend(f"{name}:{issue}" for issue in evidence_issues(model, evaluation))
    return issues


def workbook_labels(ws) -> dict:
    suffix = "脏数据标签"
    return {
        str(ws.cell(1, col).value).removesuffix(suffix): ws.cell(2, col).value
        for col in range(1, ws.max_column + 1)
        if str(ws.cell(1, col).value or "").endswith(suffix)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--fill-file", type=Path)
    args = parser.parse_args()
    labels = None
    if args.fill_file:
        payload = json.loads(args.fill_file.read_text(encoding="utf-8"))
        labels = {row["sheet"]: (row.get("fields") or {}).get("请选择脏数据标签")
                  for row in payload.get("models") or []}
    issues = check_task(REPO_ROOT / "tasks" / args.task_id, labels)
    for issue in issues:
        print(f"[BAD] {issue}")
    if not issues:
        print(f"[OK] {args.task_id} AI feedback evidence")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
