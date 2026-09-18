#!/usr/bin/env python3
"""Apply current-period annotation-score redline templates.

This script is intentionally narrow: it only consumes the machine-readable
report produced by fetch_g1_platform.js after the platform evaluation pages
have been collected. It does not fetch platform data, write Feishu, or edit
Ark forms.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.concurrency import atomic_write_json, validate_task_id  # noqa: E402
from lib.g1 import SHEET_MODELS  # noqa: E402
from lib.paths import REPO_ROOT  # noqa: E402

ISSUE_CONFIG = {
    "task_discrimination_too_low": {
        "issue": "题目区分度过低",
        "affects_task_quality": True,
        "prompt_quality": "不合格",
        "dirty_tag": "用户问题:低质量任务",
        "platform_audit_reason": "题目区分度过低，反馈完全不可用",
    },
    "perfunctory_feedback": {
        "issue": "完全敷衍",
        "affects_task_quality": False,
        "dirty_tag": "用户问题:敷衍恶意打分",
        "platform_audit_reason": "标注人评分备注完全敷衍，反馈完全不可用",
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def model_names(model_map: dict) -> list[str]:
    names = list(model_map.get("sheet_columns") or [])
    if not names:
        names = list((model_map.get("models") or {}).keys())
    if not names:
        names = list(SHEET_MODELS)
    return names


def read_task_title(task_id: str, ark_dir: Path, existing: dict) -> str:
    for key in ("task_title", "task"):
        value = str(existing.get(key) or "").strip()
        if value:
            return value
    task_path = ark_dir / "task.json"
    if task_path.exists():
        task = load_json(task_path)
        for value in (
            task.get("title"),
            (task.get("task") or {}).get("title") if isinstance(task.get("task"), dict) else "",
        ):
            text = str(value or "").strip()
            if text:
                return text
    probe = REPO_ROOT / "tasks" / task_id / "source_probe.json"
    if probe.exists():
        payload = load_json(probe)
        matches = payload.get("target_matches") or []
        if matches:
            return str(matches[0].get("task") or "").strip()
    return ""


def evidence_for_model(task_id: str, sheet: str, ark_dir: Path, report: dict) -> Path:
    screenshots = report.get("evidence_screenshots") or {}
    raw = str(screenshots.get(sheet) or "").strip()
    if raw:
        path = Path(raw)
        candidate = path if path.is_absolute() else REPO_ROOT / path
        if candidate.exists() and candidate.suffix.lower() == ".png":
            return candidate
    fallback = ark_dir / "_evaluation_redline.png"
    if fallback.exists():
        return fallback
    matches = sorted(ark_dir.glob("_evaluation_redline_*.png"))
    if matches:
        return matches[0]
    raise RuntimeError(f"{task_id} 缺少平台评分页红线截图")


def install_screenshots(task_id: str, names: list[str], ark_dir: Path, report: dict) -> tuple[list[str], str]:
    delivery_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    prior = []
    for name in names:
        prior.extend(delivery_dir.glob(f"{name}_*.png"))
    prior = sorted(set(prior))
    backup_text = ""
    if prior:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = REPO_ROOT / "tasks" / task_id / "screenshots_before_evaluation_redline" / stamp
        backup.mkdir(parents=True, exist_ok=False)
        for path in prior:
            path.replace(backup / path.name)
        backup_text = str(backup.relative_to(REPO_ROOT))

    written = []
    for name in names:
        source = evidence_for_model(task_id, name, ark_dir, report)
        numbered = delivery_dir / f"{name}_01_evaluation_redline.png"
        verify = delivery_dir / f"{name}_verify.png"
        shutil.copy2(source, numbered)
        shutil.copy2(source, verify)
        written.extend([str(numbered.relative_to(REPO_ROOT)), str(verify.relative_to(REPO_ROOT))])
    return written, backup_text


def build_qc(task_id: str, qc: dict, model_map: dict, report: dict) -> dict:
    classification = str(report.get("classification") or "").strip()
    cfg = ISSUE_CONFIG.get(classification)
    if not cfg:
        raise RuntimeError(f"不支持的红线类型：{classification or '-'}")
    issue = cfg["issue"]
    ark_dir = REPO_ROOT / "tasks" / task_id / "ark_g1"
    qc.setdefault("task_id", task_id)
    title = read_task_title(task_id, ark_dir, qc)
    if title:
        qc["task_title"] = title
    sheet = qc.setdefault("sheet", {})
    sheet.update({
        "verifiable": "是",
        "verifiable_reason": "",
        "category_correct": sheet.get("category_correct") or "是",
        "redline_issue": issue,
        "redline_note": issue,
        "evaluation_redline": {
            "classification": classification,
            "issue": issue,
            "affects_task_quality": bool(cfg.get("affects_task_quality")),
            "report": str((ark_dir / "evaluation_redline.json").relative_to(REPO_ROOT)),
        },
    })
    if cfg.get("affects_task_quality"):
        sheet["prompt_quality"] = cfg["prompt_quality"]
        sheet["prompt_quality_note"] = issue

    models = sheet.setdefault("models", {})
    submitted = []
    for name in model_names(model_map):
        info = (model_map.get("models") or {}).get(name) or {}
        if info.get("missing"):
            continue
        submitted.append(name)
        scores = ((report.get("models") or {}).get(name) or {}).get("scores") or {}
        data = models.setdefault(name, {})
        data.update({
            "rating": "不合格",
            "execution_process_score": scores.get("执行过程"),
            "execution_artifact_score": scores.get("产物质量"),
            "note": issue,
            "suppress_score_append": True,
            "platform_audit_reason": cfg["platform_audit_reason"],
            "dirty_tag": cfg["dirty_tag"],
            "dirty_tag_reason": issue,
        })
    if not submitted:
        raise RuntimeError("model_map 中没有已提交模型，无法应用评分红线")
    return qc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--apply", action="store_true", help="写入 qc_cells.json 并安装截图")
    args = parser.parse_args()
    task_id = validate_task_id(args.task_id)

    task_dir = REPO_ROOT / "tasks" / task_id
    ark_dir = task_dir / "ark_g1"
    report_path = ark_dir / "evaluation_redline.json"
    map_path = task_dir / "model_map.json"
    qc_path = task_dir / "qc_cells.json"
    missing = [p for p in (report_path, map_path) if not p.exists()]
    if missing:
        raise SystemExit("缺少文件：" + ", ".join(str(p.relative_to(REPO_ROOT)) for p in missing))

    report = load_json(report_path)
    if not report.get("triggered"):
        print(f"[OK] {task_id}: 未命中评分红线；不应用模板")
        return 0
    model_map = load_json(map_path)
    qc = load_json(qc_path) if qc_path.exists() else {"task_id": task_id, "sheet": {}}
    plan = build_qc(task_id, qc, model_map, report)
    names = [
        name for name in model_names(model_map)
        if not ((model_map.get("models") or {}).get(name) or {}).get("missing")
    ]

    issue = str((plan.get("sheet") or {}).get("redline_issue") or "")
    if not args.apply:
        print(f"[OK] {task_id}: 命中评分红线：{issue}")
        print("[dry-run] models=" + ", ".join(names))
        print("重新运行并加 --apply 才会更新本地质检文件。")
        return 0

    atomic_write_json(qc_path, plan)
    screenshots, backup = install_screenshots(task_id, names, ark_dir, report)
    result = {
        "task_id": task_id,
        "issue": issue,
        "report": str(report_path.relative_to(REPO_ROOT)),
        "screenshots": screenshots,
        "backup": backup,
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }
    result_path = task_dir / "evaluation_redline_apply.json"
    atomic_write_json(result_path, result)
    print(f"[OK] {task_id}: 已套用评分红线模板：{issue}")
    print(f"     qc={qc_path.relative_to(REPO_ROOT)}")
    print(f"     result={result_path.relative_to(REPO_ROOT)}")
    if backup:
        print(f"     prior screenshots moved to {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
