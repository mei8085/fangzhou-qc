"""Parse annotator attribution tags and flag tag/remark contradictions.

G1 evaluation pages show 执行过程 / 产物质量 tags next to dimension remarks.
QC treats selected tags as part of the annotator's feedback. A selected tag
does not need to be repeated in the remark; only explicit contradictions
between the tag and remark are flagged here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .g1 import OUTPUT_SUBDIR, SHEET_MODELS
from .paths import REPO_ROOT


PROCESS_DIM = 15
ARTIFACT_DIM = 16
DIM_FALLBACK_NAMES = {
    PROCESS_DIM: "执行过程",
    ARTIFACT_DIM: "产物质量",
}

# Platform defect tags. Positive tags such as 模糊意图理解好 are omitted.
DEFECT_TAGS = {
    "自测不充分",
    "效率太低",
    "过度谄媚",
    "模型运行不稳定",
    "没读到 Skills",
    "模型需要反复指引",
    "不当行为",
    "模型偷懒或频繁中断",
    "用猜测补空白",
    "忽略关键约束",
    "任务跑偏",
    "过早宣称完成",
    "产物里有幻觉输出",
    "产物性能差",
    "把正常的老功能改坏",
    "新功能有 Bug、或者历史 Bug 没改好",
    "产物无法启动",
    "最终轮信息有误",
    "违背要求",
    "模型遗漏或遗忘",
}

TAG_ISSUE_IN_NOTE = re.compile(r"标签|错选")
BRACKET_TAG = re.compile(r"^【([^】]+)】")
SELFTEST_INSUFFICIENT_RE = re.compile(
    r"(?:自测|自查|测试|验证|检查).{0,12}(?:不充分|不够充分|不足|遗漏)|"
    r"(?:没有|未|没).{0,8}(?:检查|检测|测出|发现).{0,10}(?:Bug|bug|错误|问题|缺陷)"
)
NO_VISIBLE_BUG_RE = re.compile(
    r"(?:无|没有|未发现|不存在).{0,10}(?:实锤|明确|明显|可见)?.{0,6}(?:Bug|bug|缺陷|故障)|"
    r"无硬伤"
)
PREFIX_COMPATIBLE_TAGS = {
    "任务跑偏": {"指令不遵循"},
}


def load_json(path: Path) -> Any:
    """Load UTF-8 JSON, accepting a leading BOM."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _dim_name(dim_id: int, dictionaries: dict) -> str:
    """Return the page dimension name for a dimension id."""
    for item in dictionaries.get("dimensions") or []:
        if item.get("id") == dim_id:
            return str(item.get("name") or DIM_FALLBACK_NAMES.get(dim_id) or dim_id)
    return DIM_FALLBACK_NAMES.get(dim_id) or str(dim_id)


def _tag_catalog(dictionaries: dict) -> dict[int, dict]:
    """Map tag id to the dictionary record."""
    return {item["id"]: item for item in dictionaries.get("tags") or [] if "id" in item}


def strip_tag_prefix(remark: str) -> str:
    """Drop the leading 【标签名】 wrapper copied onto dimension remarks."""
    text = str(remark or "").strip()
    match = BRACKET_TAG.match(text)
    if not match:
        return text
    return text[match.end():].strip()


def prefixed_tag_name(remark: str) -> str:
    """Return the 【标签名】 prefix on a remark, or empty string."""
    match = BRACKET_TAG.match(str(remark or "").strip())
    return match.group(1).strip() if match else ""


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    """Return True if any marker occurs in ``text``."""
    return any(marker in text for marker in markers)


def mismatch_reasons(tag_name: str, remark: str) -> list[str]:
    """Return contradiction codes for one selected defect tag versus remark.

    Empty list means the tag and remark can stand together. A remark that does
    not mention the tag is acceptable because the tag itself is part of the
    annotator's evaluation. Prefix checks are done once per dimension in
    ``parse_evaluation``.
    """
    tag = str(tag_name or "").strip()
    body = strip_tag_prefix(str(remark or "").strip())
    reasons: list[str] = []
    if tag not in DEFECT_TAGS:
        return reasons
    if tag == "自测不充分" and "充分" in body and not SELFTEST_INSUFFICIENT_RE.search(body):
        reasons.append("tag-selftest-insufficient-but-remark-sufficient")
    if tag == "模型遗漏或遗忘" and _has_any(body, ("完整", "能展示")) and not _has_any(
        body, ("遗漏", "遗忘", "缺失", "未实现", "没入口", "没有入口", "不完整", "漏判", "漏掉", "没把")
    ):
        reasons.append("tag-omission-but-remark-complete")
    if tag == "新功能有 Bug、或者历史 Bug 没改好" and NO_VISIBLE_BUG_RE.search(body):
        reasons.append("tag-bug-but-remark-denies-visible-bug")
    return reasons


def parse_evaluation(payload: dict) -> list[dict]:
    """Return process/artifact rows with selected tags and remarks."""
    evaluation = payload.get("evaluation") or payload
    dictionaries = payload.get("dictionaries") or {}
    catalog = _tag_catalog(dictionaries)
    dim_results = {
        item.get("dimensionId"): item
        for item in evaluation.get("dimensionResults") or []
        if isinstance(item, dict)
    }
    tags_by_dim: dict[int, list[str]] = {}
    for item in evaluation.get("tagMaps") or []:
        if not isinstance(item, dict):
            continue
        dim_id = item.get("dimensionId")
        tag = catalog.get(item.get("tagId")) or {}
        name = str(tag.get("name") or "").strip()
        if dim_id is None or not name:
            continue
        tags_by_dim.setdefault(int(dim_id), []).append(name)

    rows: list[dict] = []
    for dim_id in (PROCESS_DIM, ARTIFACT_DIM):
        result = dim_results.get(dim_id) or {}
        tags = tags_by_dim.get(dim_id) or []
        remark = str(result.get("remark") or "").strip()
        overall = str(evaluation.get("remark") or "").strip()
        prefix = prefixed_tag_name(remark)
        issues: list[str] = []
        if prefix and not tags:
            issues.append("remark-has-tag-prefix-but-no-selected-tag")
        elif prefix and prefix not in tags and not (PREFIX_COMPATIBLE_TAGS.get(prefix, set()) & set(tags)):
            issues.append(f"remark-prefix-is-{prefix}-not-selected")
        for tag in tags:
            for item in mismatch_reasons(tag, remark):
                if item not in issues:
                    issues.append(item)
        rows.append({
            "dimension_id": dim_id,
            "dimension": _dim_name(dim_id, dictionaries),
            "score": result.get("score"),
            "tags": tags,
            "remark": remark,
            "overall_remark": overall,
            "mismatches": issues,
        })
    return rows


def evaluation_path_for_model(task_dir: Path, sheet: str, info: dict) -> Path | None:
    """Locate evaluation.json for one sheet model."""
    ark = task_dir / OUTPUT_SUBDIR
    run_id = info.get("task_model_run_id") or info.get("taskModelRunId")
    platform = str(info.get("platform") or "").strip()
    if run_id and platform:
        candidate = ark / f"{run_id}__{platform}" / "evaluation.json"
        if candidate.exists():
            return candidate
    if platform:
        matches = sorted(ark.glob(f"*__{platform}/evaluation.json"))
        if len(matches) == 1:
            return matches[0]
    if run_id:
        matches = sorted(ark.glob(f"{run_id}__*/evaluation.json"))
        if len(matches) == 1:
            return matches[0]
    return None


def iter_model_evaluations(task_id: str) -> list[dict]:
    """Load tag/remark rows for every model that has an evaluation.json."""
    task_dir = REPO_ROOT / "tasks" / str(task_id)
    map_path = task_dir / "model_map.json"
    models = {}
    if map_path.exists():
        payload = load_json(map_path)
        models = payload.get("models") or {}
    ordered = [name for name in SHEET_MODELS if name in models]
    ordered.extend(name for name in models if name not in ordered)

    out: list[dict] = []
    for sheet in ordered:
        info = models.get(sheet) or {}
        path = evaluation_path_for_model(task_dir, sheet, info)
        if path is None:
            continue
        try:
            evaluation = load_json(path)
        except Exception:
            continue
        rows = parse_evaluation(evaluation)
        mismatches = [item for row in rows for item in row["mismatches"]]
        out.append({
            "sheet": sheet,
            "code": info.get("code") or "",
            "platform": info.get("platform") or "",
            "evaluation_path": str(path),
            "dimensions": rows,
            "mismatches": mismatches,
        })
    return out


def note_mentions_tag_issue(note: str, audit: str = "") -> bool:
    """Return True if the QC note names the tag/remark problem."""
    blob = f"{note or ''} {audit or ''}"
    return bool(TAG_ISSUE_IN_NOTE.search(blob))


def qc_coverage_issues(model_row: dict, rating: str, note: str, audit: str = "") -> list[str]:
    """Return selfcheck codes when QC text does not cover a tag mismatch."""
    mismatches = model_row.get("mismatches") or []
    if not mismatches:
        return []
    rating = str(rating or "").strip()
    if rating == "高质量":
        return ["annotator-tag-mismatch-cannot-be-high-quality"]
    if not note_mentions_tag_issue(note, audit):
        return ["annotator-tag-mismatch-unmentioned"]
    return []


def self_test() -> list[str]:
    """Return failed assertion labels. Empty list means the detector is healthy."""
    failures: list[str] = []

    praise_selftest = mismatch_reasons(
        "自测不充分",
        "【自测不充分】自测对比其他模型比较充分，且追加的能力也有自测",
    )
    if "tag-selftest-insufficient-but-remark-sufficient" not in praise_selftest:
        failures.append("missed-selftest-praise-conflict")

    mixed_selftest = mismatch_reasons(
        "自测不充分",
        "【自测不充分】首轮自测比较充分，追加的轮次自测不充分",
    )
    if mixed_selftest:
        failures.append(f"false-positive-mixed-selftest:{mixed_selftest}")

    omission_praise = mismatch_reasons(
        "模型遗漏或遗忘",
        "【模型遗漏或遗忘】整体的能力比较完整，追加的能力基本能展示入口",
    )
    if "tag-omission-but-remark-complete" not in omission_praise:
        failures.append("missed-omission-praise-conflict")

    bug_with_ack = mismatch_reasons(
        "新功能有 Bug、或者历史 Bug 没改好",
        "【新功能有 Bug、或者历史 Bug 没改好】产物功能页面还不错。"
        "优点：工作日历、账龄/SLA；缺点：状态流转日志和暂停态净 SLA 缺失。",
    )
    if bug_with_ack:
        failures.append(f"false-positive-bug-with-ack:{bug_with_ack}")

    bug_denied = mismatch_reasons(
        "新功能有 Bug、或者历史 Bug 没改好",
        "【模糊意图理解好】【新功能有 Bug、或者历史 Bug 没改好】"
        "整体任务连贯成体系、无实锤可见 Bug，扣分仅因模拟行情覆盖深度有限。",
    )
    if "tag-bug-but-remark-denies-visible-bug" not in bug_denied:
        failures.append("missed-bug-denial-conflict")

    tag_not_repeated = mismatch_reasons(
        "效率太低",
        "【效率太低】主页面能打开，核心功能有缺失。",
    )
    if tag_not_repeated:
        failures.append(f"false-positive-tag-not-repeated:{tag_not_repeated}")

    prefix_mismatch = mismatch_reasons(
        "过早宣称完成",
        "【自测不充分】产物不可用，只显示加载中",
    )
    if prefix_mismatch:
        failures.append(f"single-tag-helper-should-ignore-prefix:{prefix_mismatch}")
    prefix_row = parse_evaluation({
        "evaluation": {
            "remark": "",
            "dimensionResults": [
                {"dimensionId": 15, "score": 2, "remark": "【自测不充分】产物不可用"},
                {"dimensionId": 16, "score": 2, "remark": "【自测不充分】产物不可用"},
            ],
            "tagMaps": [
                {"dimensionId": 16, "tagId": 65},
            ],
        },
        "dictionaries": {
            "dimensions": [
                {"id": 15, "name": "执行过程"},
                {"id": 16, "name": "产物质量"},
            ],
            "tags": [
                {"id": 65, "dimensionId": 16, "name": "过早宣称完成"},
                {"id": 64, "dimensionId": 15, "name": "自测不充分"},
            ],
        },
    })
    artifact = next(item for item in prefix_row if item["dimension_id"] == 16)
    if "remark-prefix-is-自测不充分-not-selected" not in artifact["mismatches"]:
        failures.append("missed-prefix-not-in-selected-tags")

    if qc_coverage_issues({"mismatches": ["x"]}, "高质量", "过程 8 分相符，产物 8 分相符，反馈质量为高质量。"):
        pass
    else:
        failures.append("high-quality-must-fail-on-mismatch")

    mentioned = qc_coverage_issues(
        {"mismatches": ["x"]},
        "合格",
        "过程 8 分相符，产物 8 分相符，过程标签自测不充分和标注人备注比较充分不符，反馈质量为合格。",
    )
    if mentioned:
        failures.append(f"mentioned-mismatch-still-flagged:{mentioned}")

    unmentioned = qc_coverage_issues(
        {"mismatches": ["x"]},
        "合格",
        "过程 8 分相符，产物 8 分相符，反馈质量为合格。",
    )
    if "annotator-tag-mismatch-unmentioned" not in unmentioned:
        failures.append("unmentioned-mismatch-not-flagged")

    return failures
