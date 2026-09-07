#!/usr/bin/env python3
"""Scan the visible task prompt and uploaded text for round-quota cheating.

Run this after fetch_g1_platform.js has collected the first Prompt's
"上传产物", before any product retest. QC does not count trajectory rounds; it
only checks whether the visible prompt or uploaded Markdown/text tells the
model to reach a round quota.

Usage:
    python3 skills/qc-eval/scripts/check_prompt_cheat.py <TASK_ID>
    python3 skills/qc-eval/scripts/check_prompt_cheat.py <TASK_ID> --scan-only
    python3 skills/qc-eval/scripts/check_prompt_cheat.py <TASK_ID> --apply
    python3 skills/qc-eval/scripts/check_prompt_cheat.py --self-test

Exit codes:
    0  prompt is clean
    10 prompt contains round-quota cheating
    1  screenshot / apply failed after a hit
    2  missing inputs or detector self-test failed
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.g1 import SHEET_MODELS  # noqa: E402
from lib.paths import REPO_ROOT  # noqa: E402
from lib.prompt_cheat import (  # noqa: E402
    extract_prompt_text,
    find_task_json,
    highlight_windows,
    load_task_payload,
    quote_hits,
    scan_round_cheat,
    self_test,
)
from screenshot_static_walkthrough import render_snippet  # noqa: E402

TASKS_DIR = REPO_ROOT / "tasks"
DELIVERY_DIR = REPO_ROOT / "delivery"
EXIT_CLEAN = 0
EXIT_CHEAT = 10
DIRTY_TAG = "用户问题:低质量任务"
REDLINE_ISSUE = "题目不合理"


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp for generated JSON files."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def model_tag(name: str) -> str:
    """Match compose.py / screenshot_vue.js column filename tags."""
    return str(name).replace(" ", "_")


def load_json(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON object, accepting a leading BOM."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    """Write pretty UTF-8 JSON used by later QC steps."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def model_names(task_id: str) -> list[str]:
    """Return sheet model headers for screenshot copies and qc_cells drafts."""
    map_path = TASKS_DIR / task_id / "model_map.json"
    if map_path.exists():
        model_map = load_json(map_path)
        cols = model_map.get("sheet_columns")
        if cols:
            return list(cols)
        models = model_map.get("models") or {}
        if models:
            names = [name for name in SHEET_MODELS if name in models]
            names.extend(name for name in models if name not in names)
            return names
    return list(SHEET_MODELS)


def artifact_download_unavailable_names(task_id: str) -> set[str]:
    """Return models that must use the download-blocker template instead."""
    map_path = TASKS_DIR / task_id / "model_map.json"
    if not map_path.exists():
        return set()
    model_map = load_json(map_path)
    return {
        str(name)
        for name, info in (model_map.get("models") or {}).items()
        if (info or {}).get("artifact_download_unavailable")
        or (info or {}).get("artifact_download_state") == "unavailable"
    }


def source_row(task_id: str) -> dict[str, str]:
    """Read reviewer / title / supplier from the local G1 source xlsx when present."""
    from probe_g1_task_ids import load_rows  # noqa: E402
    from lib.g1 import SOURCE_SHEET  # noqa: E402
    from lib.paths import default_g1_source_xlsx  # noqa: E402

    source = default_g1_source_xlsx()
    if not source.exists():
        return {}
    try:
        _title, _header_row, _headers, rows = load_rows(source, SOURCE_SHEET)
    except Exception:
        return {}
    for row in rows:
        if str(row.get("task_id") or "").strip() == str(task_id):
            return {
                "task_title": str(row.get("task") or "").strip(),
                "reviewer": str(row.get("reviewer") or "").strip(),
                "supplier": str(row.get("supplier") or "").strip(),
            }
    return {}


def task_title_from_payload(payload: Any) -> str:
    """Best-effort title from CaseBffV1CrowdtestTaskGet JSON."""
    if not isinstance(payload, dict):
        return ""
    for key in ("title", "taskTitle", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    task = payload.get("task")
    if isinstance(task, dict):
        for key in ("title", "taskTitle", "name"):
            value = task.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def build_notes(quote: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (prompt_quality_note, per-model (note, audit_reason) pairs).

    Model notes all state the round-cheating fact. Openings vary so delivery
    text is not five identical sentences.
    """
    prompt_note = (
        f"提示词要求模型{quote}，属轮次作弊红线。题目质量不合格，不再复测各模型产物。"
    )
    model_specs = [
        (
            f"提示词要求模型{quote}，属轮次作弊红线，本题不再核产物。反馈质量为不合格。",
            f"提示词要求{quote}，属轮次作弊红线，反馈完全不可用。",
        ),
        (
            f"提示词写明{quote}，属题目红线，本题不再核产物。反馈质量为不合格。",
            f"提示词含轮次配额，属红线，反馈完全不可用。",
        ),
        (
            f"出题把{quote}写进提示词，属轮次作弊，结论不可信。反馈质量为不合格。",
            f"轮次作弊，不核产物，反馈完全不可用。",
        ),
        (
            f"提示词把工具轮次设成硬性门槛（{quote}），属红线。反馈质量为不合格。",
            f"提示词轮次作弊，属红线，反馈完全不可用。",
        ),
        (
            f"题目用{quote}要求模型凑轮次，属低质量任务红线。反馈质量为不合格。",
            f"凑轮次指令明确，属红线，反馈完全不可用。",
        ),
    ]
    return prompt_note, model_specs


def draft_qc_cells(
    task_id: str,
    payload: Any,
    hits: list[dict[str, Any]],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a complete qc_cells.json for a prompt-cheat short-circuit."""
    src = source_row(task_id)
    quote = quote_hits(hits)
    prompt_note, model_specs = build_notes(quote)
    title = (
        (existing or {}).get("task_title")
        or src.get("task_title")
        or task_title_from_payload(payload)
        or ""
    )
    sheet_in = (existing or {}).get("sheet") or {}
    existing_models = sheet_in.get("models") or {}
    models: dict[str, Any] = {}
    names = model_names(task_id)
    unavailable = artifact_download_unavailable_names(task_id)
    for idx, name in enumerate(names):
        if name in unavailable:
            if name in existing_models:
                models[name] = existing_models[name]
            continue
        note, audit = model_specs[idx % len(model_specs)]
        models[name] = {
            "rating": "不合格",
            "note": note,
            "dirty_tag": DIRTY_TAG,
            "dirty_tag_reason": "提示词轮次作弊，题目质量不合格。",
            "platform_audit_reason": audit,
        }
    return {
        "task_id": task_id,
        "task_title": title,
        "sheet": {
            "reviewer": sheet_in.get("reviewer") or src.get("reviewer") or "",
            "supplier": sheet_in.get("supplier") or src.get("supplier") or "",
            "is_high_quality_task": "否",
            "prompt_quality": "不合格",
            "prompt_quality_note": prompt_note,
            "verifiable": "否",
            "verifiable_reason": "提示词存在轮次作弊，按规则不再复测产物，验证截图改为提示词框选。",
            "category_correct": sheet_in.get("category_correct") or "是",
            "redline_issue": REDLINE_ISSUE,
            "redline_note": f"提示词要求模型{quote}，属于轮次作弊。",
            "prompt_cheat": True,
            "prompt_cheat_kind": "轮次作弊",
            "artifact_download_unavailable_models": sorted(unavailable),
            "models": models,
        },
    }


def write_prompt_files(task_dir: Path, prompt: str, report: dict[str, Any]) -> None:
    """Persist the extracted prompt and the scan report for later QC steps."""
    (task_dir / "prompt.md").write_text(prompt + ("\n" if prompt else ""), encoding="utf-8")
    write_json(task_dir / "prompt_cheat.json", report)


def task_attachments(payload: Any) -> list[dict[str, Any]]:
    """Return first-round uploads reported by CaseBffV1CrowdtestTaskGet."""
    if not isinstance(payload, dict):
        return []
    value = payload.get("attachments")
    if value is None and isinstance(payload.get("task"), dict):
        value = payload["task"].get("attachments")
    return value if isinstance(value, list) else []


def uploaded_prompt_materials(task_json: Path, payload: Any) -> list[dict[str, Any]]:
    """Load inspected Markdown/text from first-round task uploads.

    If Ark reports uploads, missing or incomplete collection is a hard stop;
    otherwise the prompt gate could silently ignore the user's real prompt.
    """
    ark_dir = task_json.parent
    manifest_path = ark_dir / "task_uploads.json"
    reported = task_attachments(payload)
    if not manifest_path.exists():
        if reported:
            raise FileNotFoundError(
                f"{manifest_path.relative_to(REPO_ROOT)} 不存在，但 task.json 报告了 "
                f"{len(reported)} 个首轮上传产物；重新运行 fetch_g1_platform.js collect"
            )
        return []

    manifest = load_json(manifest_path)
    if manifest.get("status") != "complete":
        raise ValueError(
            f"首轮上传产物未完整采集：{manifest_path.relative_to(REPO_ROOT)} "
            f"status={manifest.get('status')!r}"
        )
    if int(manifest.get("reported_count") or 0) != len(manifest.get("items") or []):
        raise ValueError("首轮上传产物清单数量不一致，停止提示词检查")
    if reported and int(manifest.get("reported_count") or 0) != len(reported):
        raise ValueError("task.json 与首轮上传产物清单数量不一致，重新采集后再质检")

    materials_path = ark_dir / str(manifest.get("prompt_materials_path") or "task_prompt_materials.json")
    if not materials_path.exists():
        raise FileNotFoundError(f"首轮上传文本索引缺失：{materials_path.relative_to(REPO_ROOT)}")
    indexed = load_json(materials_path)
    materials = indexed.get("materials") or []
    if int(indexed.get("material_count") or 0) != len(materials):
        raise ValueError("首轮上传文本索引数量不一致，停止提示词检查")
    return materials


def combined_prompt(task_json: Path, payload: Any) -> tuple[str, list[dict[str, Any]]]:
    """Combine the page prompt with inspected uploaded Markdown/text."""
    visible = extract_prompt_text(payload)
    materials = uploaded_prompt_materials(task_json, payload)
    sections: list[str] = []
    sources: list[dict[str, Any]] = []
    if visible:
        sections.append("# 平台首轮 Prompt\n\n" + visible)
        sources.append({"kind": "visible_prompt", "source": str(task_json.relative_to(REPO_ROOT))})
    for item in materials:
        source = str(item.get("source") or item.get("source_file") or "uploaded text")
        text = str(item.get("text") or "").strip()
        sources.append({
            "kind": "task_upload_text",
            "source": source,
            "occurrence_count": item.get("occurrence_count", 1),
            "size_bytes": item.get("size_bytes"),
            "sha256": item.get("sha256"),
        })
        if not text:
            continue
        sections.append(f"# 首轮上传产物文本：{source}\n\n{text}")
    return "\n\n---\n\n".join(sections), sources


def render_screenshots(task_id: str, prompt_path: Path, hits: list[dict[str, Any]]) -> int:
    """Render prompt evidence only for models whose artifacts are downloadable."""
    lines = prompt_path.read_text(encoding="utf-8").splitlines() or [""]
    hit_lines = [int(hit["line"]) for hit in hits if hit.get("line")]
    windows = highlight_windows(len(lines), hit_lines)
    out_dir = DELIVERY_DIR / task_id / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    unavailable = artifact_download_unavailable_names(task_id)
    names = [name for name in model_names(task_id) if name not in unavailable]
    if not names:
        print("  [skip] all submitted model artifacts are download-unavailable; keep download-list evidence")
        return 0

    first_tag = model_tag(names[0])
    target_tags = {model_tag(name) for name in names}
    for old in out_dir.glob("*.png"):
        if any(old.name.startswith(f"{tag}_") for tag in target_tags):
            old.unlink()

    frame_paths: list[Path] = []
    for idx, (start, end, spans) in enumerate(windows, start=1):
        frame = out_dir / f"{first_tag}_{idx:02d}_prompt_cheat.png"
        render_snippet(
            prompt_path,
            frame,
            display_path="prompt.md",
            start=start,
            end=end,
            highlights=spans,
        )
        frame_paths.append(frame)
        print(f"  {frame.relative_to(REPO_ROOT)}")

    for name in names[1:]:
        tag = model_tag(name)
        for idx, src in enumerate(frame_paths, start=1):
            dest = out_dir / f"{tag}_{idx:02d}_prompt_cheat.png"
            shutil.copyfile(src, dest)

    result = subprocess.run(
        [sys.executable, str(HERE / "compose.py"), task_id],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        print("  [err] compose.py failed")
        return 1
    return 0


def scan_task(task_id: str) -> tuple[dict[str, Any], Path, Any]:
    """Scan page + uploaded prompt material and write the combined evidence."""
    task_dir = TASKS_DIR / task_id
    task_json = find_task_json(task_dir)
    if not task_json:
        raise FileNotFoundError(
            f"tasks/{task_id}/*/task.json 不存在；先跑 fetch_g1_platform.js collect"
        )
    payload = load_task_payload(task_json)
    prompt, prompt_sources = combined_prompt(task_json, payload)
    hits = scan_round_cheat(prompt) if prompt else []
    report = {
        "task_id": task_id,
        "task_json": str(task_json.relative_to(REPO_ROOT)).replace("\\", "/"),
        "hit": bool(hits),
        "kind": "轮次作弊" if hits else "",
        "prompt_chars": len(prompt),
        "prompt_sources": prompt_sources,
        "uploaded_text_source_count": sum(
            1 for source in prompt_sources if source.get("kind") == "task_upload_text"
        ),
        "hits": hits,
        "quote": quote_hits(hits) if hits else "",
        "skip_product_retest": bool(hits),
        "generated_at": utc_now(),
    }
    write_prompt_files(task_dir, prompt, report)
    return report, task_json, payload


def print_verdict(report: dict[str, Any]) -> None:
    """Print a stop/continue banner the agent can follow without extra context."""
    task_id = report.get("task_id")
    if report.get("hit"):
        print(f"==> PROMPT CHEAT  tasks/{task_id}", flush=True)
        print("    提示词要求模型达到指定工具轮次，属于轮次作弊。", flush=True)
        print("    质检不统计实际轮次。题目质量不合格；下载可用模型按轮次作弊填写。", flush=True)
        print("    下载不可用模型仍套下载阻断模板；所有模型都不要复测产物。", flush=True)
        for hit in report.get("hits") or []:
            print(f"    L{hit.get('line')}: {hit.get('text')}", flush=True)
        return
    print(f"==> prompt clean  tasks/{task_id}  继续按正常流程复测产物", flush=True)


def apply_qc_cells(task_id: str, payload: Any, hits: list[dict[str, Any]], force: bool) -> int:
    """Write qc_cells.json for a cheat hit unless a non-cheat file already exists."""
    path = TASKS_DIR / task_id / "qc_cells.json"
    existing = load_json(path) if path.exists() else None
    if existing and not force:
        sheet = existing.get("sheet") or {}
        if not sheet.get("prompt_cheat"):
            print(f"  [skip] {path.relative_to(REPO_ROOT)} exists; pass --force to overwrite")
            return 0
    qc = draft_qc_cells(task_id, payload, hits, existing=existing)
    write_json(path, qc)
    print(f"  wrote {path.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("task_ids", nargs="*", help="源表任务ID")
    parser.add_argument("--scan-only", action="store_true", help="只扫提示词，不截图、不写 qc_cells")
    parser.add_argument("--apply", action="store_true", help="命中时写入 qc_cells.json 短路径草稿")
    parser.add_argument("--force", action="store_true", help="覆盖已有 qc_cells.json")
    parser.add_argument("--no-screenshot", action="store_true", help="命中时也不出提示词截图")
    parser.add_argument("--self-test", action="store_true", help="跑检测器内置样例")
    args = parser.parse_args()

    if args.self_test:
        errors = self_test()
        if errors:
            print("  [FAIL] prompt-cheat self-test")
            for err in errors:
                print(f"    - {err}")
            return 2
        print("  [OK] prompt-cheat self-test")
        return 0

    if not args.task_ids:
        parser.error("missing TASK_ID")

    worst = EXIT_CLEAN
    for task_id in args.task_ids:
        try:
            report, _task_json, payload = scan_task(task_id)
        except (FileNotFoundError, ValueError) as exc:
            print(f"  [err] {exc}", file=sys.stderr)
            return 2
        print_verdict(report)
        print(f"  wrote tasks/{task_id}/prompt.md")
        print(f"  wrote tasks/{task_id}/prompt_cheat.json")
        if not report.get("hit"):
            continue
        worst = EXIT_CHEAT
        if args.apply:
            if apply_qc_cells(task_id, payload, report["hits"], args.force) != 0:
                return 1
        if args.scan_only or args.no_screenshot:
            continue
        map_path = TASKS_DIR / task_id / "model_map.json"
        if not map_path.exists():
            print("  [info] model_map.json 还没有，采集结束后再跑本脚本出提示词截图")
            continue
        prompt_path = TASKS_DIR / task_id / "prompt.md"
        if render_screenshots(task_id, prompt_path, report["hits"]) != 0:
            return 1
    return worst


if __name__ == "__main__":
    sys.exit(main())
