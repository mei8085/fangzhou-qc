#!/usr/bin/env python3
"""Generate delivery/<ID>/platform_qc.md from qc_cells.json["platform_qc"].

This markdown is what 邓全 (the reviewer) reads off when manually filling the
反馈质检 tab on the platform — one block per task with the 3 questions and the
proposed answers, plus quick-jump links to each model's platform URL.

Dirty-tag rule source:
    spec/Coding场景脏数据标签与标准.md

Usage:
    make_platform_qc.py <TASK_ID> [<TASK_ID> ...]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

PLATFORM_QUESTIONS = [
    ("task_quality", "请选择该任务的质量", ["高", "中", "低", "不可用"]),
    ("feedback_quality", "请选择该用户的反馈质量", ["完全可用", "部分可用", "完全不可用"]),
    (
        "dirty_tag",
        "请选择脏数据标签",
        [
            "模型资源问题：API请求超时/轨迹大量error",
            "OpenClaw/Hermes框架问题",
            "用户问题：低质量任务（prompt设计）",
            "用户问题：敷衍恶意打分（用户评价）",
            "用户问题：AI打分/AI评价",
            "用户问题：用户切换模型错误",
            "用户问题：LLM任务测试VLM",
            "其它",
            "非脏数据",
        ],
    ),
]
DIRTY_TAG_RULE_SUMMARY = [
    "规则来源：spec/Coding场景脏数据标签与标准.md",
    "L1 单条运行记录（模型 × 任务）：反馈质量脏数据标签 + 平台 & 模型表现 + Harness 表现。",
    "L2 单任务（同任务多模型）：题目质量脏数据标签 + L2 粒度反馈质量脏数据标签。",
    "API 请求超时 / 轨迹大量 error：需有结构化 API 异常证据；status_code=200 的红色非流式输出不算异常。",
    "OpenClaw / Hermes 框架问题：必须同时有用户侧证据和轨迹侧证据；模型自身死循环或工具失败后无法恢复不打此标签。",
    "用户切换模型错误：模型身份与接入点不一致，且前段轨迹与他模型雷同。",
    "AI 打分 / AI 评价：仅当明确证据表明标注人员使用 AI 生成提交的评分或评价时判定。任务要求测试模型自评、自测、逐项验收或生成执行报告均不触发；图标、百分制、Markdown 或转述模型原话也不能单独作为依据。",
    "敷衍恶意打分：理由空泛、标准矛盾、结论相悖、连带扣分、评分与实际产物明显不符；L2 还包括多模型理由雷同、未测完、分数一致但实际差异明显。",
    "题目红线（prompt 简单 / VLM 错配）：prompt 过简或模糊、纯题库题、VLM 错配、纯生图、工具调用轮次 < 10、各模型 prompt 不一致、提示词轮次作弊等。",
    "低质量任务不是脏数据标签。",
]
LEGACY_MODEL_NAMES = ["0614C", "0616D", "GLM 5.2", "0616B"]
PREFERRED_33_MODEL_ORDER = [
    "60B-1M-0705B",
    "60B-1M-0705E",
    "2.1-pro-1M",
    "60B-1M-0703B",
]
PREFERRED_MODEL_ORDERS = [
    [
        "1M-0709A-0711",
        "2.1-pro-0711",
        "1M-0705E-0711",
        "1M-0703B-0711",
    ],
    PREFERRED_33_MODEL_ORDER,
]


def apply_preferred_order(names: list[str]) -> list[str]:
    for preferred in PREFERRED_MODEL_ORDERS:
        if set(preferred).issubset(names):
            return preferred + [x for x in names if x not in preferred]
    return names


def model_names_for(qc: dict, model_map: dict | None) -> list[str]:
    """Return model names to render, preserving platform/model_map order.

    28 期 used a fixed four-model platform tab order. Newer platform-backed
    periods change model names by batch, so the entry file is model_map-driven.
    """
    if model_map:
        cols = model_map.get("sheet_columns")
        if isinstance(cols, list) and cols:
            return apply_preferred_order([str(x) for x in cols])
        models = model_map.get("models")
        if isinstance(models, dict) and models:
            return apply_preferred_order(list(models.keys()))
    qc_models = qc.get("sheet", {}).get("models")
    if isinstance(qc_models, dict) and qc_models:
        return list(qc_models.keys())
    return LEGACY_MODEL_NAMES


def render(task_id: str, qc: dict, model_map: dict | None) -> str:
    p = qc.get("platform_qc", {})
    lines = []
    title = qc.get("task_title") or task_id
    lines.append(f"# 平台反馈质检填写清单 — {title} ({task_id})")
    lines.append("")
    lines.append("> 平台 URL 见每个模型块下方，登录后切到 `反馈质检` tab，按以下答案填入。")
    lines.append("")

    # task-wide question
    tq = p.get("task_quality")
    lines.append("## 1. 请选择该任务的质量（题目层级，所有模型共用）")
    lines.append("")
    lines.append(f"- **答**：{tq if tq else '（待定）'}")
    if p.get("task_quality_note"):
        lines.append(f"- **备注**：{p['task_quality_note']}")
    lines.append("")

    # per-model questions
    lines.append("## 2. 反馈质量 + 3. 脏数据标签（每模型分别填）")
    lines.append("")
    for model in model_names_for(qc, model_map):
        url = (model_map or {}).get("models", {}).get(model, {}).get("platform_url")
        lines.append(f"### {model}")
        lines.append("")
        if url:
            lines.append(f"平台链接：<{url}>")
            lines.append("")
        fq = (p.get("feedback_quality") or {}).get(model)
        lines.append(f"- **反馈质量**：{fq if fq else '（待定）'}")
        fq_note = (p.get("feedback_quality_note") or {}).get(model)
        if fq_note:
            lines.append(f"  - 备注：{fq_note}")
        dt = (p.get("dirty_tag") or {}).get(model)
        if dt is None:
            lines.append("- **脏数据标签**：（待定）")
        elif isinstance(dt, list):
            tags = "、".join(dt) if dt else "（无）"
            lines.append(f"- **脏数据标签**：{tags}")
        else:
            lines.append(f"- **脏数据标签**：{dt}")
        dt_note = (p.get("dirty_tag_note") or {}).get(model)
        if dt_note:
            lines.append(f"  - 备注：{dt_note}")
        lines.append("")

    # appendix: dropdown options for sanity-check while filling
    lines.append("---")
    lines.append("")
    lines.append("## 可选项参考（避免填错文案）")
    lines.append("")
    for key, label, opts in PLATFORM_QUESTIONS:
        lines.append(f"- **{label}**：{' / '.join(opts)}")
    lines.append("")
    lines.append("## 脏数据标签规则摘要")
    lines.append("")
    for item in DIRTY_TAG_RULE_SUMMARY:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_ids", nargs="+")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    for tid in args.task_ids:
        task_dir = tasks_dir / tid
        cells_path = task_dir / "qc_cells.json"
        if not cells_path.exists():
            print(f"[skip] {tid}: {cells_path} not found")
            continue
        qc = json.loads(cells_path.read_text(encoding="utf-8-sig"))
        map_path = task_dir / "model_map.json"
        model_map = json.loads(map_path.read_text(encoding="utf-8")) if map_path.exists() else None
        delivery_dir = REPO_ROOT / "delivery" / tid
        delivery_dir.mkdir(parents=True, exist_ok=True)
        out_path = delivery_dir / "platform_qc.md"
        out_path.write_text(render(tid, qc, model_map), encoding="utf-8")
        print(f"==> wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
