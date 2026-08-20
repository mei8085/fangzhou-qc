#!/usr/bin/env python3
"""Self-check reviewer-owned cells in delivery/<TASK_ID>/<TASK_ID>.xlsx.

38期反馈质量评的是标注人的打分、备注、佐证与 trace 是否可信，不是直接评
模型作业本身。命中任一项即视为不合格，调用方负责改写后重跑 push_xlsx.py。

Exit code: 0=clean, 1=has issues.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

# ---------- 表头 → reviewer 列定位 ----------

_TEXT_HEADER_KEYS = [
    "题目质量说明",
    "不可验证原因",
    "0614C对比GLM 5.2 模型差异（轨迹/产物）pattern简述",
    "红线问题",
    "质检人",
    "所属商",
    "所述商",
    "机器质检结果是否正确",
    "错误原因",
]
_MODEL_NOTE_SUFFIX = "质量备注"
_MODEL_RATING_SUFFIX = "反馈质量（作业质量）"
_HIGH_QUALITY_TASK_HEADER = "是否是高质量题目"
_NORMAL_TASK_HEADER = "是否正常题目"
_CATEGORY_CORRECT_HEADER = "分类是否正确"
_TASK_RATING_HEADER = "任务质量（题目质量）"
_REDLINE_HEADER = "红线问题"
_MACHINE_QC_HEADER = "机器质检结果是否正确"
_MACHINE_QC_REASON_HEADER = "错误原因"
_PLATFORM_AUDIT_HEADER = "一次质检平台审核理由（按模型）"
_PROMPT_QUALITY_NOTE_HEADER = "题目质量说明"
_HIGH_QUALITY_FEEDBACK_VALUE = "高质量"

TASK_REDLINE_OPTIONS = {
    "毫无意义的题目",
    "非代码题",
    "题目不合理",
    "非本人场景",
    "静态展示性页面",
}
FEEDBACK_REDLINE_OPTIONS = {
    "任务质量（题目质量）触及红线",
    "虚假反馈",
    "trace和反馈结果明显不一致",
    "完全敷衍",
}
REDLINE_OPTIONS = TASK_REDLINE_OPTIONS | FEEDBACK_REDLINE_OPTIONS
REDLINE_ALIAS_MAP = {
    "任务质量触及红线": "任务质量（题目质量）触及红线",
    "trace 和反馈结果明显不一致": "trace和反馈结果明显不一致",
}


def find_headers(ws) -> dict[str, int]:
    """delivery xlsx 的表头在第 1 行（rebuild 后固定）。"""
    return {
        str(ws.cell(1, c).value).strip(): c
        for c in range(1, ws.max_column + 1)
        if isinstance(ws.cell(1, c).value, str) and ws.cell(1, c).value.strip()
    }


def detect_period(headers: dict[str, int]) -> str:
    return "38期"


def reviewer_columns(headers: dict[str, int]) -> tuple[list[int], set[int]]:
    """Return (all_reviewer_cols, model_note_cols).

    Model-note columns are those ending with `质量备注` (每个模型一列).
    """
    cols: list[int] = []
    model_note_cols: set[int] = set()
    for h, c in headers.items():
        if h in _TEXT_HEADER_KEYS:
            cols.append(c)
        elif h.endswith(_MODEL_NOTE_SUFFIX):
            cols.append(c)
            model_note_cols.add(c)
    return sorted(cols), model_note_cols


# ---------- 规则 ----------

# 38期反馈质量评的是标注人对模型产出结果的打分与备注。
# 模型备注必须出现下面任一关键词，说明这段在评"标注人评价是否准确"。
ANNOTATOR_REF = re.compile(
    r"标注人|打分|备注|分值|定档|偏(?:高|低)?\s*一?档|方向(?:对|错|准确|有偏差|抓)|"
    r"识别(?:到|出|准确)|判断(?:准确|对|错|有偏差)|落档|佐证"
)
FORBIDDEN_WORDS = [
    "自动化", "脚本", "pipeline", "compose", "screenshot_vue",
    "按 spec", "spec 维度", "spec 第", "稽核", "实测属实",
    "SKILL.md", "qc_cells", "model_map",
    "——", "—",
    "【", "】", "「", "」", "『", "』",
    # 把模型称作"这家"/"四家"是口语错觉（像在评供应商）。规范统一写作
    # "这个模型"/"该模型"/"4 个模型"。
    "这家", "那家", "几家", "两家", "三家", "四家", "五家",
    # "封顶"是方舟平台打分时的内部勾选项名，对题面下游 reviewer 不通用，
    # 备注里要翻译成"认为核心功能不可用 / 严重问题"这种白话。
    "封顶",
    # 当前反馈质量只判断打分是否准确、备注是否清楚、证据是否支撑结论；
    # 不再评价"打分格式规范"，避免把旧模板句误写进交付备注。
    "打分及打分备注均未按照打分格式规范进行",
    "未按照打分格式规范",
    "打分格式规范",
    "按评分项规范填写",
]

# 交付描述里不要出现 AI 腔短评和生硬程度词。这里单独列出，便于和工程/符号
# 禁用词区分；推荐改写见 SKILL.md 的写作约束。
UNNATURAL_STYLE_WORDS = [
    "更稳", "方向到位", "观察到位", "覆盖到位", "佐证到位",
    "定性正确", "抓得准", "判断落点", "描述属实", "贴合",
    "属实", "靠谱", "偏薄", "兜底",
]
UNNATURAL_STYLE_RE = re.compile(
    r"(?:很|挺|蛮|够|更|比较|较|不太|不够)准(?!确)|"
    r"(?:判断|识别|方向)准(?!确)|抓得(?:很)?准(?!确)|"
    r"(?:判断|识别)?落点"
)

FORBIDDEN_SYM = re.compile(r"[*#]|`")

# 句首或紧跟标点 / 空白后的"我"。
FIRST_PERSON = re.compile(r"(?:^|[，。、；！？\s])我(?![们国方司家])")

# 单元格内代码引用过多
CODE_REF = re.compile(r"\.[a-z]{1,5}(?=\b|[　-鿿])|src/|第\s*\d+\s*行")

# 备注末尾不要重复定档
TRAILING_VERDICT = re.compile(r"(?:给|定|定档为?|评)\s*[高中低](?![分级数等数])")

MAX_LEN = 220
MAX_CODE_REFS = 3

# 题目质量说明是给表格 reviewer 看的判断依据，只说明题目本身的完整性、
# 经济价值、评测价值、可复核性和未达高质量原因；不要写页面没有展示的
# 4 模型总分，也不要把“是否是高质量题目”这个表字段的填写动作写进去。
TASK_NOTE_FORBIDDEN_PATTERNS = [
    (re.compile(r"4\s*个模型总分"), "task-note-no-4-model-total-score"),
    (re.compile(r"模型总分为"), "task-note-no-model-total-score"),
    (re.compile(r"是否是高质量题目.{0,20}填"), "task-note-no-high-quality-field-self-description"),
    (re.compile(r"填[“\"]?[是否][”\"]?"), "task-note-no-field-fill-instruction"),
]

# 红线必须有明确证据；出现这类模糊措辞时按"疑罪从无"拦下。
VAGUE_REDLINE_EVIDENCE = re.compile(
    r"疑似|可能|不确定|不好说|无法确认|猜测|推测|大概|也许|似乎|像是|感觉"
)
MIN_REDLINE_EVIDENCE_LEN = 20


def scan_style_only(s: str) -> list[str]:
    issues: list[str] = []
    for w in UNNATURAL_STYLE_WORDS:
        if w in s:
            issues.append(f"style:{w}")
    for m in UNNATURAL_STYLE_RE.findall(s):
        issues.append(f"style:{m}")
    return issues


def scan_cell(s: str, *, col: int, model_note_cols: set[int], period: str) -> list[str]:
    issues = []
    for w in FORBIDDEN_WORDS:
        if w in s:
            issues.append(f"word:{w}")
    issues.extend(scan_style_only(s))
    if FORBIDDEN_SYM.search(s):
        issues.append("forbidden-sym")
    if FIRST_PERSON.search(s):
        issues.append("first-person:我")
    if len(s) > MAX_LEN:
        issues.append(f"too-long:{len(s)}")
    if len(CODE_REF.findall(s)) > MAX_CODE_REFS:
        issues.append("too-many-code-refs")
    if TRAILING_VERDICT.search(s):
        issues.append("trailing-verdict")
    if col in model_note_cols:
        if not ANNOTATOR_REF.search(s):
            issues.append("not-evaluating-annotator")
    return issues


def scan_task_quality_note(s: str) -> list[str]:
    issues: list[str] = []
    for pattern, issue in TASK_NOTE_FORBIDDEN_PATTERNS:
        if pattern.search(s):
            issues.append(issue)
    return issues


def check_platform_qc_md(md_path: Path) -> list[str]:
    if not md_path.exists():
        return []
    issues: list[str] = []
    for idx, line in enumerate(md_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        found = scan_style_only(line)
        if found:
            issues.append(f"line {idx}: {found}")
    return issues


def split_redline_options(s: str) -> list[str]:
    return [p.strip() for p in re.split(r"[，,；;\n]+", s) if p.strip()]


def canonical_redline_option(s: str) -> str | None:
    if s in REDLINE_OPTIONS:
        return s
    if s in REDLINE_ALIAS_MAP:
        return REDLINE_ALIAS_MAP[s]
    compact = re.sub(r"\s+", "", s)
    if compact in REDLINE_OPTIONS:
        return compact
    if compact in REDLINE_ALIAS_MAP:
        return REDLINE_ALIAS_MAP[compact]
    return None


def cell_text(ws, col: int | None) -> str:
    if not col:
        return ""
    return str(ws.cell(2, col).value or "").strip()


def is_redline_rating(ws, col: int | None) -> bool:
    return "红线" in cell_text(ws, col)


def can_carry_feedback_redline(ws, col: int | None) -> bool:
    """38期模型反馈质量下拉只有 高质量/合格/不合格。

    反馈红线标签放在「红线问题」列；对应模型反馈质量应为「不合格」。
    兼容历史本地文件里曾出现的「红线」值。
    """
    value = cell_text(ws, col)
    return "红线" in value or value == "不合格"


def model_rating_note_cols(headers: dict[str, int]) -> list[tuple[str, int, int | None]]:
    out = []
    for h, rating_col in headers.items():
        if not h.endswith(_MODEL_RATING_SUFFIX):
            continue
        model = h[:-len(_MODEL_RATING_SUFFIX)]
        out.append((model, rating_col, headers.get(f"{model}{_MODEL_NOTE_SUFFIX}")))
    return out


def evidence_too_thin(texts: list[str]) -> bool:
    concrete = [t for t in texts if t.strip()]
    if not concrete:
        return True
    return sum(len(t.strip()) for t in concrete) < MIN_REDLINE_EVIDENCE_LEN


def redline_consistency_issues(ws, headers: dict[str, int]) -> list[str]:
    """Check 红线问题 options, category match, and minimum evidence discipline."""
    redline_col = headers.get(_REDLINE_HEADER)
    if not redline_col:
        return []

    selected = str(ws.cell(2, redline_col).value or "").strip()
    raw_options = split_redline_options(selected)
    canonical_options = [canonical_redline_option(v) for v in raw_options]
    valid_options = [v for v in canonical_options if v]

    task_rating_redline = is_redline_rating(ws, headers.get(_TASK_RATING_HEADER))
    task_note = cell_text(ws, headers.get("题目质量说明"))
    redline_model_notes = [
        cell_text(ws, note_col)
        for _model, rating_col, note_col in model_rating_note_cols(headers)
        if can_carry_feedback_redline(ws, rating_col)
    ]
    has_model_redline = bool(redline_model_notes)
    has_redline_rating = task_rating_redline or has_model_redline

    issues: list[str] = []
    if has_redline_rating and not selected:
        issues.append("redline-rating-missing-红线问题")
    if selected:
        invalid = [raw for raw, canon in zip(raw_options, canonical_options) if not canon]
        if invalid:
            issues.append(f"invalid-红线问题:{'，'.join(invalid)}")
        if not has_redline_rating:
            issues.append("红线问题-without-redline-rating")
        if VAGUE_REDLINE_EVIDENCE.search(selected):
            issues.append("redline-evidence-vague")

    selected_set = set(valid_options)
    has_task_tag = bool(selected_set & TASK_REDLINE_OPTIONS)
    has_feedback_tag = bool(selected_set & FEEDBACK_REDLINE_OPTIONS)
    if task_rating_redline and selected and not has_task_tag:
        issues.append("task-redline-missing-task-tag")
    if has_model_redline and selected and not has_feedback_tag:
        issues.append("feedback-redline-missing-feedback-tag")

    for opt in selected_set:
        if opt in TASK_REDLINE_OPTIONS and not task_rating_redline:
            issues.append(f"task-redline-tag-without-task-redline-rating:{opt}")
        elif opt == "任务质量（题目质量）触及红线" and not task_rating_redline:
            issues.append("feedback-task-quality-tag-without-task-redline")
        elif opt in FEEDBACK_REDLINE_OPTIONS and opt != "任务质量（题目质量）触及红线" and not has_model_redline:
            issues.append(f"feedback-redline-tag-without-model-redline-rating:{opt}")

    if has_task_tag:
        if evidence_too_thin([task_note]):
            issues.append("task-redline-evidence-too-thin")
        elif VAGUE_REDLINE_EVIDENCE.search(task_note):
            issues.append("task-redline-evidence-vague")
    feedback_tags_needing_model_evidence = selected_set & (
        FEEDBACK_REDLINE_OPTIONS - {"任务质量（题目质量）触及红线"}
    )
    if feedback_tags_needing_model_evidence:
        if evidence_too_thin(redline_model_notes):
            issues.append("feedback-redline-evidence-too-thin")
        elif VAGUE_REDLINE_EVIDENCE.search("\n".join(redline_model_notes)):
            issues.append("feedback-redline-evidence-vague")
    if "任务质量（题目质量）触及红线" in selected_set:
        if evidence_too_thin([task_note]):
            issues.append("task-quality-trigger-redline-evidence-too-thin")
        elif VAGUE_REDLINE_EVIDENCE.search(task_note):
            issues.append("task-quality-trigger-redline-evidence-vague")
    return issues


def machine_qc_issues(ws, headers: dict[str, int]) -> dict[int, list[str]]:
    correct_col = headers.get(_MACHINE_QC_HEADER)
    if not correct_col:
        return {}
    reason_col = headers.get(_MACHINE_QC_REASON_HEADER)
    verdict = cell_text(ws, correct_col)
    reason = cell_text(ws, reason_col)
    bad: dict[int, list[str]] = {}
    if verdict not in {"正确", "部分正确可参考", "错误"}:
        bad.setdefault(correct_col, []).append("machine-qc-verdict-must-be-正确-部分正确可参考-or-错误")
    if verdict in {"部分正确可参考", "错误"} and len(reason) < 15:
        bad.setdefault(reason_col or correct_col, []).append("machine-qc-mismatch-reason-too-thin")
    if verdict == "正确" and not reason:
        bad.setdefault(reason_col or correct_col, []).append("machine-qc-correct-reason-missing")
    return bad


def high_quality_task_issues(ws, headers: dict[str, int]) -> dict[int, list[str]]:
    col = headers.get(_HIGH_QUALITY_TASK_HEADER)
    if not col:
        return {}
    value = str(ws.cell(2, col).value or "").strip()
    if not value:
        return {col: ["required-empty"]}
    if value not in {"是", "否"}:
        return {col: [f"invalid-option:{value}"]}
    model_ratings = [
        cell_text(ws, rating_col)
        for _model, rating_col, _note_col in model_rating_note_cols(headers)
        if cell_text(ws, rating_col)
    ]
    if model_ratings:
        expected = "是" if all(r == _HIGH_QUALITY_FEEDBACK_VALUE for r in model_ratings) else "否"
        if value != expected:
            return {
                col: [
                    f"must-match-overall-feedback-quality:{expected}",
                    f"model-ratings:{'/'.join(model_ratings)}",
                ]
            }
    return {}


def normal_task_issues(ws, headers: dict[str, int]) -> dict[int, list[str]]:
    col = headers.get(_NORMAL_TASK_HEADER)
    if not col:
        return {}
    value = str(ws.cell(2, col).value or "").strip()
    if not value:
        return {col: ["required-empty"]}
    if value not in {"是", "否"}:
        return {col: [f"invalid-option:{value}"]}
    return {}


def category_correct_issues(ws, headers: dict[str, int]) -> dict[int, list[str]]:
    col = headers.get(_CATEGORY_CORRECT_HEADER)
    if not col:
        return {}
    value = str(ws.cell(2, col).value or "").strip()
    if not value:
        return {col: ["required-empty"]}
    if value not in {"是", "否"}:
        return {col: [f"invalid-option:{value}"]}
    return {}


def check_xlsx(xlsx_path: Path) -> tuple[dict[int, list[str]], str]:
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    headers = find_headers(ws)
    period = detect_period(headers)
    cols, model_note_cols = reviewer_columns(headers)
    task_note_col = headers.get(_PROMPT_QUALITY_NOTE_HEADER)
    bad: dict[int, list[str]] = {}
    for c in cols:
        v = ws.cell(2, c).value
        if not v:
            continue
        text = str(v)
        issues = scan_cell(text, col=c, model_note_cols=model_note_cols, period=period)
        if c == task_note_col:
            issues.extend(scan_task_quality_note(text))
        if issues:
            bad[c] = issues
    platform_audit_col = headers.get(_PLATFORM_AUDIT_HEADER)
    platform_audit_text = cell_text(ws, platform_audit_col)
    if platform_audit_col and "任务质量高" in platform_audit_text:
        bad.setdefault(platform_audit_col, []).append("platform-audit-no-任务质量高")
    redline_col = headers.get(_REDLINE_HEADER)
    redline_issues = redline_consistency_issues(ws, headers)
    if redline_col and redline_issues:
        bad.setdefault(redline_col, []).extend(redline_issues)
    for col, issues in high_quality_task_issues(ws, headers).items():
        bad.setdefault(col, []).extend(issues)
    for col, issues in normal_task_issues(ws, headers).items():
        bad.setdefault(col, []).extend(issues)
    for col, issues in category_correct_issues(ws, headers).items():
        bad.setdefault(col, []).extend(issues)
    for col, issues in machine_qc_issues(ws, headers).items():
        bad.setdefault(col, []).extend(issues)
    return bad, period


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_ids", nargs="+")
    args = p.parse_args()
    total_bad = 0
    for tid in args.task_ids:
        xlsx = REPO_ROOT / "delivery" / tid / f"{tid}.xlsx"
        if not xlsx.exists():
            print(f"  [skip] {tid}: {xlsx} not found")
            continue
        bad, period = check_xlsx(xlsx)
        md_issues = check_platform_qc_md(REPO_ROOT / "delivery" / tid / "platform_qc.md")
        if bad or md_issues:
            print(f"  [BAD] {tid}  ({period})")
            for col, issues in bad.items():
                print(f"     col {col}: {issues}")
            for issue in md_issues:
                print(f"     platform_qc.md {issue}")
            total_bad += 1
        else:
            print(f"  [OK]  {tid}  ({period})")
    return 0 if total_bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
