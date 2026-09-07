#!/usr/bin/env python3
"""Apply the QC result for a task whose Ark download buttons are all disabled.

Run ``fetch_g1_platform.js discover-download`` first. Without ``--apply`` this
script only validates the captured page state and prints the changes it would
make. It never writes Feishu or Ark audit forms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.concurrency import atomic_write_json, validate_task_id  # noqa: E402
from lib.paths import REPO_ROOT, SKILL_DIR  # noqa: E402

TEMPLATE_PATH = SKILL_DIR / "config" / "artifact_download_unavailable.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def resolve_evidence_screenshot(discovery: dict, ark_dir: Path) -> Path:
    ark_root = ark_dir.resolve()

    def valid(candidate: Path) -> bool:
        try:
            resolved = candidate.resolve()
            resolved.relative_to(ark_root)
        except (OSError, ValueError):
            return False
        return resolved.is_file() and resolved.suffix.lower() == ".png" \
            and resolved.name.startswith("_discover_download_")

    raw = str(discovery.get("evidence_screenshot") or "").strip()
    if raw:
        path = Path(raw)
        candidate = path if path.is_absolute() else REPO_ROOT / path
        if valid(candidate):
            return candidate.resolve()
    for item in discovery.get("clickResults") or []:
        if not item.get("ok"):
            continue
        candidate = ark_dir / f"_discover_download_{item.get('index')}.png"
        if valid(candidate):
            return candidate.resolve()
    raise RuntimeError("下载列表截图不存在，请重新运行 discover-download")


def evaluation_scores(ark_dir: Path, run_id, platform: str) -> tuple[object, object]:
    candidates = []
    if run_id and platform:
        candidates.append(ark_dir / f"{run_id}__{platform}" / "evaluation.json")
    if run_id:
        candidates.extend(sorted(ark_dir.glob(f"{run_id}__*/evaluation.json")))
    path = next((item for item in candidates if item.exists()), None)
    if not path:
        raise RuntimeError(f"模型 {platform or run_id} 缺少 evaluation.json，无法读取页面分数")
    payload = load_json(path)
    names = {
        item.get("id"): str(item.get("name") or "").strip()
        for item in (payload.get("dictionaries") or {}).get("dimensions") or []
    }
    scores = {}
    for item in (payload.get("evaluation") or {}).get("dimensionResults") or []:
        name = names.get(item.get("dimensionId"), "")
        if name:
            scores[name] = item.get("score")
    process_score = scores.get("执行过程")
    artifact_score = scores.get("产物质量")
    if process_score is None or artifact_score is None:
        raise RuntimeError(f"模型 {platform or run_id} 缺少执行过程分或产物质量分")
    return process_score, artifact_score


def validate_discovery(discovery: dict, model_map: dict, task_id: str = "") -> list[str]:
    errors = []
    if task_id and not str(discovery.get("url") or "").rstrip("/").endswith(f"/task/{task_id}"):
        errors.append("discover-download 结果不属于当前任务")
    if discovery.get("classification") != "artifact_download_unavailable":
        errors.append("discover-download 未判定为 artifact_download_unavailable")
    if discovery.get("artifact_download_unavailable") is not True:
        errors.append("artifact_download_unavailable 不是 true")
    if discovery.get("all_expected_models_present") is not True:
        errors.append("下载列表未覆盖全部预期模型")
    if discovery.get("all_download_buttons_disabled") is not True:
        errors.append("并非全部预期模型的下载按钮都处于禁用状态")

    rows = discovery.get("download_rows") or []
    row_platforms = {str(row.get("platform") or "").strip() for row in rows}
    expected = []
    for model in model_map.get("sheet_columns") or (model_map.get("models") or {}).keys():
        info = (model_map.get("models") or {}).get(model) or {}
        platform = str(info.get("platform") or "").strip()
        if info.get("missing"):
            errors.append(f"预期模型 {model} 标记为 missing，不适用全模型下载禁用模板")
        if platform:
            expected.append(platform)
    if not expected:
        errors.append("model_map 中没有可核对的平台模型")
    reported_expected = {
        str(value).strip() for value in discovery.get("expected_platforms") or [] if str(value).strip()
    }
    if expected and reported_expected != set(expected):
        errors.append("discover-download 的预期模型集合与 model_map 不一致")
    missing = sorted(set(expected) - row_platforms)
    if missing:
        errors.append(f"下载列表缺少平台模型：{','.join(missing)}")
    for row in rows:
        if str(row.get("platform") or "").strip() in expected and row.get("download_button_disabled") is not True:
            errors.append(f"模型 {row.get('platform')} 的下载按钮不是禁用状态")
    return errors


def model_names(model_map: dict) -> list[str]:
    names = list(model_map.get("sheet_columns") or [])
    if not names:
        names = list((model_map.get("models") or {}).keys())
    return names


def note_template(template: dict, task_id: str) -> str:
    choices = list((template.get("model") or {}).get("note_templates") or [])
    if not choices:
        raise RuntimeError("参考模板缺少 model.note_templates")
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return choices[int(digest, 16) % len(choices)]


def build_plan(task_id: str, qc: dict, model_map: dict, template: dict) -> dict:
    sheet = qc.setdefault("sheet", {})
    template_sheet = template.get("sheet") or {}
    sheet["artifact_download_unavailable"] = True
    for key in ("verifiable", "verifiable_reason", "redline_issue", "redline_note"):
        sheet[key] = template_sheet.get(key, "")

    models = sheet.setdefault("models", {})
    template_model = template.get("model") or {}
    note = note_template(template, task_id)
    applied = []
    for name in model_names(model_map):
        info = (model_map.get("models") or {}).get(name) or {}
        process_score, artifact_score = evaluation_scores(
            REPO_ROOT / "tasks" / task_id / "ark_g1",
            info.get("task_model_run_id") or info.get("run_id"),
            str(info.get("platform") or ""),
        )
        data = models.setdefault(name, {})
        data.pop("audit_reason", None)
        data.update({
            "rating": template_model["rating"],
            "execution_process_score": process_score,
            "execution_artifact_score": artifact_score,
            "note": note.format(
                process_score=process_score,
                artifact_score=artifact_score,
            ),
            "platform_audit_reason": template_model["platform_audit_reason"],
            "dirty_tag": template_model["dirty_tag"],
            "dirty_tag_reason": template_model["dirty_tag_reason"],
        })
        applied.append({
            "sheet": name,
            "platform": info.get("platform"),
            "process_score": process_score,
            "artifact_score": artifact_score,
        })
    return {"qc": qc, "models": applied}


def install_evidence(task_id: str, names: list[str], source: Path) -> tuple[list[str], str]:
    delivery_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    prior = []
    for name in names:
        prior.extend(delivery_dir.glob(f"{name}_*.png"))
    prior = sorted(set(prior))
    backup_text = ""
    if prior:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = REPO_ROOT / "tasks" / task_id / "screenshots_before_download_unavailable" / stamp
        backup.mkdir(parents=True, exist_ok=False)
        for path in prior:
            path.replace(backup / path.name)
        backup_text = str(backup.relative_to(REPO_ROOT))

    written = []
    for name in names:
        numbered = delivery_dir / f"{name}_01_download_blocker.png"
        verify = delivery_dir / f"{name}_verify.png"
        shutil.copy2(source, numbered)
        shutil.copy2(source, verify)
        written.extend([str(numbered.relative_to(REPO_ROOT)), str(verify.relative_to(REPO_ROOT))])
    return written, backup_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--apply", action="store_true", help="写入 qc_cells.json 并安装截图")
    args = parser.parse_args()
    task_id = validate_task_id(args.task_id)

    task_dir = REPO_ROOT / "tasks" / task_id
    ark_dir = task_dir / "ark_g1"
    discovery_path = ark_dir / "download_list_discover.json"
    qc_path = task_dir / "qc_cells.json"
    map_path = task_dir / "model_map.json"
    required = [TEMPLATE_PATH, discovery_path, qc_path, map_path]
    missing = [str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"缺少文件：{', '.join(missing)}")

    template = load_json(TEMPLATE_PATH)
    discovery = load_json(discovery_path)
    qc = load_json(qc_path)
    model_map = load_json(map_path)
    errors = validate_discovery(discovery, model_map, task_id)
    if errors:
        raise SystemExit("不满足产物不可下载模板条件：\n- " + "\n- ".join(errors))
    source = resolve_evidence_screenshot(discovery, ark_dir)
    plan = build_plan(task_id, qc, model_map, template)

    if not args.apply:
        print(f"[OK] {task_id}: 全部预期模型下载按钮均禁用")
        print(f"[dry-run] evidence={source.relative_to(REPO_ROOT)}")
        for item in plan["models"]:
            print(
                f"[dry-run] {item['sheet']} / {item['platform']}: "
                f"过程 {item['process_score']} 分，产物 {item['artifact_score']} 分"
            )
        print("重新运行并加 --apply 才会更新本地质检文件。")
        return 0

    atomic_write_json(qc_path, plan["qc"])
    screenshots, backup = install_evidence(task_id, model_names(model_map), source)
    result = {
        "task_id": task_id,
        "scenario": template["scenario"],
        "template": str(TEMPLATE_PATH.relative_to(REPO_ROOT)),
        "discovery": str(discovery_path.relative_to(REPO_ROOT)),
        "evidence_source": str(source.relative_to(REPO_ROOT)),
        "screenshots": screenshots,
        "backup": backup,
        "models": plan["models"],
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    }
    result_path = task_dir / "artifact_download_unavailable_apply.json"
    atomic_write_json(result_path, result)
    print(f"[OK] {task_id}: 已套用产物不可下载模板")
    print(f"     qc={qc_path.relative_to(REPO_ROOT)}")
    print(f"     result={result_path.relative_to(REPO_ROOT)}")
    if backup:
        print(f"     prior screenshots moved to {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
