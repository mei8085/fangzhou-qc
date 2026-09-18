"""Validate that verification screenshots match the verifiable flag.

This guard complements blank_guard.py. blank_guard only catches empty or
duplicate frames; this file catches a different failure mode: marking a task
as verifiable while every attached image is only code/static inspection.

It also requires a `<模型>_NN_test.png` when a quality note claims a test
failure that the labeler did not record, or that disagrees with the labeler.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.prompt_cheat import is_prompt_cheat_task  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]

CODE_ONLY_TOKENS = {
    "code",
    "editor",
    "snippet",
    "static",
    "grep",
    "rg",
    "source",
    "walkthrough",
    "transform",
    "operator",
    "table_config",
    "frontend_highlight",
    "highlight",
    "expectation",
    "clickhouse",
    "utils",
}

RUNTIME_TOKENS = {
    "api",
    "author_modules",
    "blocker",
    "build",
    "capsule",
    "cli",
    "dashboard",
    "dialog",
    "edit",
    "error",
    "evaluation_redline",
    "filter",
    "initial",
    "login",
    "missing_model",
    "npm",
    "page",
    "pytest",
    "request",
    "response",
    "result",
    "runtime",
    "terminal",
    "test",
    "ui",
    "workspace",
    "write_draft",
}

STATIC_REVIEW_TOKENS = CODE_ONLY_TOKENS | {
    "log",
    "logs",
    "trace",
    "trajectory",
    "walkthrough",
    "build_error",
    "blocker",
    "prompt",
    "cheat",
    "missing_model",
}

ENV_BLOCKER_TERMS = (
    "gpu",
    "cuda",
    "密钥",
    "账号",
    "凭据",
    "硬件",
    "外设",
    "sdk",
    "云平台",
    "线上",
    "样本",
    "授权",
    "source",
    "源码",
    "跑不起来",
    "构建失败",
    "依赖冲突",
    "u03l",
    "docker",
    "工作机",
    "测试机",
)

U03L_SERVICE_TERMS = (
    "clickhouse",
    "postgres",
    "postgresql",
    "redis",
    "mysql",
    "mongodb",
    "mongo",
    "rabbitmq",
    "kafka",
    "minio",
    "celery",
    "docker",
    "docker-compose",
    "compose",
    "spring boot",
    "springboot",
    "maven",
    "gradle",
    "jdk",
    "java",
    "mysql8",
)

LOCAL_ENV_ONLY_TERMS = (
    "本机缺",
    "本地缺",
    "未安装",
    "没有安装",
    "找不到",
    "command not found",
    "unable to locate a java runtime",
    "cannot connect to the docker daemon",
    "docker daemon",
    "mvn not found",
    "maven not found",
    "java runtime",
    "jdk",
    "maven",
    "mysql",
    "docker",
)


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def model_screenshot_tag(name: str) -> str:
    """Match compose.py tags: only spaces become underscores."""
    return str(name).replace(" ", "_")


def iter_model_names(model_map: dict) -> list[str]:
    """Prefer sheet_columns, then models key order."""
    cols = model_map.get("sheet_columns")
    if cols:
        return list(cols)
    return list((model_map.get("models") or {}).keys())


def filename_tokens(path: Path) -> set[str]:
    stem = path.stem.lower()
    parts = re.split(r"[^0-9a-z]+", stem)
    tokens = {p for p in parts if p}
    # Keep multi-word phrases that are meaningful for this guard.
    for phrase in ("code_editor", "table_config", "frontend_highlight", "prompt_cheat", "missing_model", "evaluation_redline"):
        if phrase in stem:
            tokens.add(phrase)
    return tokens


def is_code_only(path: Path) -> bool:
    tokens = filename_tokens(path)
    return bool(tokens & CODE_ONLY_TOKENS) and not bool(tokens & RUNTIME_TOKENS)


def has_runtime_signal(path: Path) -> bool:
    tokens = filename_tokens(path)
    return bool(tokens & RUNTIME_TOKENS) and not bool(tokens & {"expectation"})


def labeler_images(task_id: str) -> list[Path]:
    """Return labeler evidence images extracted from platform feedback.

    Local 24/27 bundles store them under tasks/<ID>/images/<CODE>/img_N.png.
    Newer platform bundles may store comment images elsewhere, but this path is
    enough to prevent the known regression: labeler had real page screenshots
    while reviewer submitted only code snippets.
    """

    img_dir = REPO_ROOT / "tasks" / task_id / "images"
    if not img_dir.exists():
        return []
    return sorted(
        p for p in img_dir.glob("*/*")
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )


def task_text(task_id: str) -> str:
    parts: list[str] = []
    prompt_md = REPO_ROOT / "tasks" / task_id / "prompt.md"
    if prompt_md.exists():
        parts.append(prompt_md.read_text(encoding="utf-8", errors="replace"))
    ark_task = REPO_ROOT / "tasks" / task_id / "ark_g1" / "task.json"
    if ark_task.exists():
        try:
            data = load_json(ark_task)
            parts.append(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass
    raw_dir = REPO_ROOT / "tasks" / task_id / "raw" / task_id
    task_json = raw_dir / "task_manager_task.json"
    if task_json.exists():
        try:
            data = load_json(task_json)
            parts.append("\n".join(str(data.get(k) or "") for k in ("title", "prompt")))
        except Exception:
            pass
    return "\n".join(parts)


def extracted_stack_text(task_id: str) -> str:
    """Inspect lightweight project metadata for backend/service-stack signals."""
    extracted = REPO_ROOT / "tasks" / task_id / "extracted"
    if not extracted.exists():
        return ""
    names = {
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
        "Dockerfile",
        "application.yml",
        "application.yaml",
        "application-dev.yml",
        "application-dev.yaml",
        "README.md",
    }
    chunks: list[str] = []
    for path in extracted.rglob("*"):
        if not path.is_file() or path.name not in names:
            continue
        try:
            rel = path.relative_to(extracted)
            text = path.read_text(encoding="utf-8", errors="replace")[:8000]
            chunks.append(f"\n## {rel}\n{text}")
        except Exception:
            continue
    return "\n".join(chunks)


def mentions_service_stack(task_id: str) -> bool:
    text = (task_text(task_id) + "\n" + extracted_stack_text(task_id)).lower()
    return any(term in text for term in U03L_SERVICE_TERMS)


def reason_has_specific_blocker(reason: str) -> bool:
    lower = reason.lower()
    return any(term in lower for term in ENV_BLOCKER_TERMS)


def reason_is_local_env_only(reason: str) -> bool:
    lower = reason.lower()
    return any(term in lower for term in LOCAL_ENV_ONLY_TERMS)


def reason_mentions_remote_attempt(reason: str) -> bool:
    lower = reason.lower()
    return "u03l" in lower or "工作机" in reason or "测试机" in reason or "远端" in reason


def check_task(task_id: str) -> list[str]:
    task_dir = REPO_ROOT / "tasks" / task_id
    delivery_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    qc_path = task_dir / "qc_cells.json"
    map_path = task_dir / "model_map.json"
    errors: list[str] = []

    if not qc_path.exists():
        return [f"{task_id}: missing tasks/{task_id}/qc_cells.json"]
    if not map_path.exists():
        return [f"{task_id}: missing tasks/{task_id}/model_map.json"]

    qc = load_json(qc_path)
    model_map = load_json(map_path)
    sheet = qc.get("sheet", {})
    verifiable = sheet.get("verifiable")
    reason = (sheet.get("verifiable_reason") or "").strip()
    names = iter_model_names(model_map)
    prompt_cheat = is_prompt_cheat_task(task_dir, qc)
    has_labeler_runtime_hint = bool(labeler_images(task_id))
    needs_u03l_check = mentions_service_stack(task_id)

    if prompt_cheat:
        if not delivery_dir.exists():
            return [f"{task_id}: prompt-cheat but delivery/{task_id}/screenshots is missing"]
        for model_name in names:
            tag = model_screenshot_tag(model_name)
            frames = sorted(delivery_dir.glob(f"{tag}_??_*.png"))
            verify = delivery_dir / f"{tag}_verify.png"
            if not frames:
                errors.append(f"{task_id}/{model_name}: prompt-cheat but no prompt screenshots")
                continue
            if not verify.exists():
                errors.append(f"{task_id}/{model_name}: missing {tag}_verify.png")
            if not any("prompt_cheat" in filename_tokens(p) or "cheat" in filename_tokens(p) for p in frames):
                shown = ", ".join(p.name for p in frames)
                errors.append(
                    f"{task_id}/{model_name}: prompt-cheat screenshots must be "
                    f"<模型>_NN_prompt_cheat.png ({shown})"
                )
        return errors

    if verifiable == "否" and not reason:
        errors.append(f"{task_id}: verifiable=否 but 不可验证原因 is empty")
    if verifiable == "否" and has_labeler_runtime_hint and not reason_has_specific_blocker(reason):
        errors.append(
            f"{task_id}: labeler feedback contains screenshots, so falling back to 不可验证 "
            "requires a concrete blocker such as missing credentials/hardware/source failure; "
            "generic static review is not enough"
        )
    if verifiable == "否" and needs_u03l_check and not reason_mentions_remote_attempt(reason):
        errors.append(
            f"{task_id}: task mentions Docker/service dependencies; before marking 不可验证, "
            "the reason must say why u03l/工作机 Docker verification is not feasible"
        )
    if verifiable == "否" and reason_is_local_env_only(reason) and not reason_mentions_remote_attempt(reason):
        errors.append(
            f"{task_id}: 不可验证原因只说明本机环境缺失；必须先尝试 u03l/工作机 Docker "
            "或在原因中写明为什么远端环境也不可行"
        )

    if verifiable == "否":
        if not delivery_dir.exists():
            errors.append(f"{task_id}: verifiable=否 but delivery/{task_id}/screenshots is missing")
            return errors
        for model_name in names:
            tag = model_screenshot_tag(model_name)
            frames = sorted(delivery_dir.glob(f"{tag}_??_*.png"))
            verify = delivery_dir / f"{tag}_verify.png"
            model_info = (model_map.get("models") or {}).get(model_name) or {}
            if model_info.get("missing"):
                if not frames or not any("missing_model" in filename_tokens(p) for p in frames):
                    errors.append(f"{task_id}/{model_name}: missing not-submitted model evidence")
                if not verify.exists():
                    errors.append(f"{task_id}/{model_name}: missing {tag}_verify.png")
                continue
            if not frames:
                errors.append(f"{task_id}/{model_name}: verifiable=否 but no static-review screenshots")
                continue
            if not verify.exists():
                errors.append(f"{task_id}/{model_name}: missing {tag}_verify.png")
            if not any(filename_tokens(p) & STATIC_REVIEW_TOKENS for p in frames):
                shown = ", ".join(p.name for p in frames)
                errors.append(
                    f"{task_id}/{model_name}: 不可验证截图 should be code/log/trace/static-review evidence "
                    f"instead of a generic page capture ({shown})"
                )
        return errors

    if verifiable != "是":
        return errors

    if not delivery_dir.exists():
        return [f"{task_id}: verifiable=是 but delivery/{task_id}/screenshots is missing"]

    for model_name in names:
        tag = model_screenshot_tag(model_name)
        frames = sorted(delivery_dir.glob(f"{tag}_??_*.png"))
        verify = delivery_dir / f"{tag}_verify.png"
        model_info = (model_map.get("models") or {}).get(model_name) or {}
        if model_info.get("missing"):
            if not frames or not any("missing_model" in filename_tokens(p) for p in frames):
                errors.append(f"{task_id}/{model_name}: missing not-submitted model evidence")
            if not verify.exists():
                errors.append(f"{task_id}/{model_name}: missing {tag}_verify.png")
            continue
        if not frames:
            errors.append(f"{task_id}/{model_name}: verifiable=是 but no per-step screenshots")
            continue
        if not verify.exists():
            errors.append(f"{task_id}/{model_name}: missing {tag}_verify.png")
        if all(is_code_only(p) for p in frames):
            shown = ", ".join(p.name for p in frames)
            hint = "; labeler screenshots exist, so rerun actual product unless a concrete blocker is documented" if has_labeler_runtime_hint else ""
            errors.append(
                f"{task_id}/{model_name}: screenshots look code/static-only ({shown}); "
                f"use real page/CLI/API/error evidence or mark verifiable=否 with reason{hint}"
            )
        if not any(has_runtime_signal(p) for p in frames):
            shown = ", ".join(p.name for p in frames)
            errors.append(
                f"{task_id}/{model_name}: no runtime evidence filename found ({shown}); "
                "expected page/API/CLI/build/error/dialog/filter/etc."
            )
        note = str((sheet.get("models") or {}).get(model_name, {}).get("note") or "")
        mismatch = bool(re.search(r"未记录|与实际情况不符|与实际不符", note))
        test_claim = bool(re.search(r"测试失败|集成测试", note))
        if mismatch and test_claim:
            tokens = set()
            for p in frames:
                tokens |= filename_tokens(p)
            if "test" not in tokens:
                shown = ", ".join(p.name for p in frames)
                errors.append(
                    f"{task_id}/{model_name}: 备注写了与标注不一致的测试失败，"
                    f"但没有测试截图（需要 <模型>_NN_test.png；现有 {shown}）"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="+")
    args = parser.parse_args()

    all_errors: list[str] = []
    for task_id in args.task_ids:
        errors = check_task(task_id)
        if errors:
            print(f"  [FAIL] {task_id}")
            for err in errors:
                print(f"    - {err}")
            all_errors.extend(errors)
        else:
            print(f"  [OK]  {task_id}")

    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
