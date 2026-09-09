"""Dynamic AI trajectory-QC accuracy column discovery."""

from __future__ import annotations

import re

AI_ACCURACY_HEADER_RE = re.compile(
    r"^模型(?P<position>[1-9]\d*)(?P<kind>质检结论是否准确|判断原因)$"
)
MODEL_RATING_SUFFIX = "反馈质量（作业质量）"


def _model_count_from_headers(headers: dict[str, int]) -> int:
    """Count model feedback columns in the source table."""
    return sum(
        1 for header in headers
        if str(header).endswith(MODEL_RATING_SUFFIX)
    )


def inspect_ai_accuracy_headers(
    headers: dict[str, int],
    expected_model_count: int | None = None,
) -> dict:
    """Inspect dynamic ``模型N`` accuracy columns.

    The source table exposes one model feedback-quality column per model. That
    count is the expected model count. AI accuracy columns never determine the
    model count by themselves, because that would allow a stale delivery file
    to add or preserve fields that the source table does not own.
    """
    found: dict[int, dict[str, str]] = {}
    for header in headers:
        match = AI_ACCURACY_HEADER_RE.fullmatch(str(header).strip())
        if not match:
            continue
        position = int(match.group("position"))
        kind = match.group("kind")
        found.setdefault(position, {})[kind] = str(header).strip()

    if not found:
        return {
            "enabled": False,
            "model_count": 0,
            "positions": [],
            "pairs": {},
            "headers": [],
            "errors": [],
        }

    detected_model_count = _model_count_from_headers(headers)
    model_count = (
        expected_model_count
        if expected_model_count is not None
        else detected_model_count
    )
    expected_positions = set(range(1, model_count + 1))
    actual_positions = set(found)
    errors: list[str] = []

    if model_count == 0:
        errors.append("源表未检测到模型反馈质量列，无法确定模型数量")
    if (
        expected_model_count is not None
        and detected_model_count
        and detected_model_count != expected_model_count
    ):
        errors.append(
            "模型反馈质量列数量不一致："
            f"检测到 {detected_model_count} 个，应为 {expected_model_count} 个"
        )

    missing_positions = sorted(expected_positions - actual_positions)
    extra_positions = sorted(actual_positions - expected_positions)
    if missing_positions:
        errors.append(
            "缺少模型位置：" + "、".join(f"模型{position}" for position in missing_positions)
        )
    if extra_positions:
        errors.append(
            "存在超出模型数量的字段：" +
            "、".join(f"模型{position}" for position in extra_positions)
        )

    pairs: dict[int, dict[str, str]] = {}
    for position in sorted(expected_positions):
        pair = found.get(position, {})
        missing_kinds = [
            kind for kind in ("质检结论是否准确", "判断原因")
            if kind not in pair
        ]
        if missing_kinds:
            errors.append(
                f"模型{position}缺少：" + "、".join(
                    f"模型{position}{kind}" for kind in missing_kinds
                )
            )
        else:
            pairs[position] = {
                "accuracy": pair["质检结论是否准确"],
                "reason": pair["判断原因"],
            }

    ordered_headers = [
        header
        for header, _ in sorted(headers.items(), key=lambda item: item[1])
        if AI_ACCURACY_HEADER_RE.fullmatch(str(header).strip())
    ]
    return {
        "enabled": True,
        "model_count": model_count,
        "positions": sorted(expected_positions),
        "pairs": pairs,
        "headers": ordered_headers,
        "errors": errors,
    }


def inspect_ai_accuracy_schema(
    source_headers: dict[str, int],
    target_headers: dict[str, int],
) -> dict:
    """Compare a delivery/remote header set with the source-owned schema."""
    source = inspect_ai_accuracy_headers(source_headers)
    target = inspect_ai_accuracy_headers(
        target_headers,
        source["model_count"] if source["enabled"] and not source["errors"] else None,
    )
    errors: list[str] = []

    if not source["enabled"]:
        # The local query table is authoritative. A stale target workbook or
        # remote sheet may still carry legacy columns, but they are ignored
        # when the source table does not enable this feature.
        return {
            "enabled": False,
            "model_count": 0,
            "source": source,
            "target": target,
            "errors": errors,
        }

    if source["errors"]:
        errors.extend("源表：" + error for error in source["errors"])
        return {
            "enabled": True,
            "model_count": source["model_count"],
            "source": source,
            "target": target,
            "errors": errors,
        }

    if not target["enabled"]:
        errors.append(
            f"目标表缺少 AI 准确性字段：应有 {source['model_count'] * 2} 个字段"
        )
    else:
        if target["model_count"] != source["model_count"]:
            errors.append(
                "目标表模型数量与源表不一致："
                f"源表 {source['model_count']} 个，目标表 {target['model_count']} 个"
            )
        errors.extend("目标表：" + error for error in target["errors"])

    return {
        "enabled": True,
        "model_count": source["model_count"],
        "source": source,
        "target": target,
        "errors": errors,
    }


def validate_ai_accuracy_headers(headers: dict[str, int]) -> dict:
    """Return dynamic field metadata or raise on a partial/mismatched set."""
    info = inspect_ai_accuracy_headers(headers)
    if info["enabled"] and info["errors"]:
        expected = info["model_count"] * 2
        actual = len(info.get("headers") or [])
        raise RuntimeError(
            "AI准确性字段不完整："
            f"按表中检测到 {info['model_count']} 个模型，应有 {expected} 个字段，"
            f"当前找到 {actual} 个；" + "；".join(info["errors"])
        )
    return info


def ordered_ai_accuracy_headers(headers: dict[str, int]) -> list[str]:
    """Return all dynamic AI accuracy headers in source column order."""
    info = validate_ai_accuracy_headers(headers)
    return info.get("headers") or []
