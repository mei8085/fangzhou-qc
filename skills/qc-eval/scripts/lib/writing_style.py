"""Shared QC writing-style helpers: banned jargon, note variety, audit templates.

Style source of truth for agents is SKILL.md plus docs/描述语言参考.xlsx.
This module only encodes the machine-checkable bits used by selfcheck and
the delivery scripts. Colloquial replacements live in writing_style.json
``preferred_replacements`` (说得通→合理, 对得上→相符/一致, 写重了/偏重/说得过头→与实际情况不符,
仍在→与实际情况相符, 可核/也可核/能核→和实际验证结果相符, 抬上去了→得益于, 缺口→问题/缺陷/缺失). Feishu notes name 高质量 / 合格 /
不合格; platform audit reasons name 完全可用 / 部分可用 / 完全不可用.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from .paths import SKILL_DIR

CONFIG_PATH = SKILL_DIR / "config" / "writing_style.json"
SCORE_IN_NOTE = re.compile(r"\d+\s*分")
# Curly quotes around a paraphrase look like a verbatim annotator quote.
SCARE_QUOTES = re.compile(r"[“”]")
MODEL_AUDIT_PREFIX = re.compile(
    r"^(?:【G1】S\d+(?:（[^）]+）)?|[A-Za-z0-9_-]+)[：:]\s*"
)


def load_writing_style() -> dict:
    """Return the on-disk writing-style config, or a safe empty fallback.

    ``writing_style.json`` uses ``banned_phrases`` / ``banned_regex``;
    checkers also look up ``banned_phrases`` / ``banned_regex``. Normalize
    both aliases after load so the JSON list is actually applied.
    """
    empty = {
        "banned_phrases": [],
        "banned_regex": [],
        "page_hidden_phrases": [],
        "page_hidden_regex": [],
        "score_prefix": "标注人给执行过程",
        "min_distinct_note_openings": 1,
        "note_opening_chars": 8,
        "audit_ending_chars": 10,
        "min_same_audit_ending": 4,
        "task_opening_chars": 10,
        "consecutive_task_opening_window": 3,
        "audit_clean_tails": ["", "未见脏数据。"],
        "audit_templates": {},
    }
    if not CONFIG_PATH.exists():
        return empty
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    phrases = data.get("banned_phrases") or data.get("banned_phrases") or []
    regexes = data.get("banned_regex") or data.get("banned_regex") or []
    hidden_phrases = data.get("page_hidden_phrases") or data.get("page_hidden_phrases") or []
    hidden_regex = data.get("page_hidden_regex") or data.get("page_hidden_regex") or []
    replacements = data.get("preferred_replacements") or data.get("preferred_replacements") or {}
    data["banned_phrases"] = phrases
    data["banned_phrases"] = phrases
    data["banned_regex"] = regexes
    data["banned_regex"] = regexes
    data["page_hidden_phrases"] = hidden_phrases
    data["page_hidden_phrases"] = hidden_phrases
    data["page_hidden_regex"] = hidden_regex
    data["page_hidden_regex"] = hidden_regex
    data["preferred_replacements"] = replacements
    data["preferred_replacements"] = replacements
    return data


def _compiled_banned_regex(cfg: dict | None = None) -> list[re.Pattern[str]]:
    cfg = cfg or load_writing_style()
    return [re.compile(p) for p in (cfg.get("banned_regex") or cfg.get("banned_regex") or []) if p]


def scan_banned_style(text: str, cfg: dict | None = None) -> list[str]:
    """Return style issue tokens for banned QC jargon in ``text``.

    Includes ``缺口`` from ``writing_style.json``: write 问题 / 缺陷 / 缺失
    instead of treating missing UI or incomplete coverage as a 缺口.
    Also flags a dangling ``，与备注相符`` / ``，与反馈相符`` (no subject);
    write ``实际情况与备注相符`` or name the score that matches.
    Also flags ``仍在`` and ``说得过头``; write 与实际情况相符 / 与实际情况不符.
    Also flags ``可核`` / ``也可核`` / ``能核``; write 和实际验证结果相符.
    """
    cfg = cfg or load_writing_style()
    issues: list[str] = []
    seen: set[str] = set()
    for phrase in (cfg.get("banned_phrases") or cfg.get("banned_phrases") or []):
        if phrase and phrase in text and phrase not in seen:
            seen.add(phrase)
            issues.append(f"style:{phrase}")
    for pattern in _compiled_banned_regex(cfg):
        for match in pattern.findall(text):
            token = match if isinstance(match, str) else "".join(match)
            if token and token not in seen:
                seen.add(token)
                issues.append(f"style:{token}")
    issues.extend(scan_page_hidden(text, cfg))
    issues.extend(scare_quote_issues(text))
    return issues


def scare_quote_issues(text: str) -> list[str]:
    """Flag curly quotes. Paraphrases must not look like verbatim quotes."""
    if SCARE_QUOTES.search(str(text or "")):
        return ["style:non-verbatim-quotes"]
    return []


_CAMEL_TOKEN = re.compile(r"[a-z]+[A-Z][A-Za-z0-9]*")
_OPENING_EVAL = re.compile(
    r"相符|不符|偏高|偏低|失败|打破|缺陷|缺失|问题|不完整|能开|起不来|报错|卡住|标注"
)


def dangling_opening_issues(text: str) -> list[str]:
    """Flag a first sentence that drops a CLI/field fact without judging it.

    Openings like ``graph --json 带 generatedAt。`` name a phenomenon but never
    say whether it is a defect or whether it matches the annotator.
    """
    blob = str(text or "").strip()
    if not blob:
        return []
    first = re.split(r"[。！？]", blob, maxsplit=1)[0]
    if not first:
        return []
    looks_like_field = bool(
        _CAMEL_TOKEN.search(first)
        or " --" in first
        or first.startswith("--")
    )
    if looks_like_field and not _OPENING_EVAL.search(first):
        return ["dangling-opening-fact"]
    return []


def scan_page_hidden(text: str, cfg: dict | None = None) -> list[str]:
    """Flag scores and field names that exist in the API but not on the page."""
    cfg = cfg or load_writing_style()
    issues: list[str] = []
    seen: set[str] = set()
    for phrase in cfg.get("page_hidden_phrases") or []:
        if phrase and phrase in text and phrase not in seen:
            seen.add(phrase)
            issues.append(f"page-hidden:{phrase}")
    for raw in cfg.get("page_hidden_regex") or []:
        if not raw:
            continue
        for match in re.findall(raw, text):
            token = match if isinstance(match, str) else "".join(match)
            if token and token not in seen:
                seen.add(token)
                issues.append(f"page-hidden:{token}")
    return issues


def opening_prefix(text: str, n: int) -> str:
    """Return the first ``n`` non-space characters used as an opening fingerprint."""
    compact = str(text or "").strip()
    return compact[:n] if compact else ""


def strip_audit_model_prefix(line: str) -> str:
    """Strip a model/platform prefix such as ``0825E（kayak）：``."""
    return MODEL_AUDIT_PREFIX.sub("", str(line or "").strip(), count=1).strip()


def repeated_opening_issues(texts: list[str], cfg: dict | None = None) -> list[str]:
    """Same-task model notes may share an opening. Kept as a no-op for callers."""
    return []


def majority_score_prefix_issues(texts: list[str], cfg: dict | None = None) -> list[str]:
    """Same-task notes may share the score-prefix opening. Variety is cross-task."""
    return []


def majority_annotator_opening_issues(texts: list[str], cfg: dict | None = None) -> list[str]:
    """Same-task notes may all open with 标注. Variety is cross-task."""
    return []


def consecutive_opening_issues(
    current_texts: list[str],
    recent: list[tuple[str, list[str]]],
    cfg: dict | None = None,
    *,
    kind: str = "note",
) -> list[str]:
    """Flag when this task reuses an opening from a recent consecutive task.

    ``recent`` is newest-first ``(task_id, texts)``. Same-task duplicates are allowed.
    """
    cfg = cfg or load_writing_style()
    if kind == "task":
        n_chars = int(
            cfg.get("task_opening_chars")
            or cfg.get("task_opening_chars")
            or 10
        )
    else:
        n_chars = int(
            cfg.get("note_opening_chars")
            or cfg.get("note_opening_chars")
            or 8
        )
    current = {
        opening_prefix(text, n_chars)
        for text in current_texts
        if str(text or "").strip()
    }
    current.discard("")
    if not current:
        return []
    for prev_id, prev_texts in recent:
        previous = {
            opening_prefix(text, n_chars)
            for text in prev_texts
            if str(text or "").strip()
        }
        overlap = current & previous
        overlap.discard("")
        if overlap:
            sample = sorted(overlap, key=len, reverse=True)[0]
            return [f"style-same-{kind}-opening-as-recent:{prev_id}:{sample}"]
    return []


def repeated_audit_ending_issues(text: str, cfg: dict | None = None) -> list[str]:
    """Same-task audit lines may share a grade close. Variety is cross-task."""
    return []


def score_clause(data: dict) -> str:
    """Return a short score clause, or empty if scores are missing.

    The clause is meant as a fallback at the end of a note, not a frozen
    opening. Prefer writing scores into the note in a varied position.
    """
    process = data.get("execution_process_score")
    artifact = data.get("execution_artifact_score")
    process_text = "" if process is None else str(process).strip()
    artifact_text = "" if artifact is None else str(artifact).strip()
    if process_text and artifact_text:
        return f"过程 {process_text} 分、产物质量 {artifact_text} 分。"
    if process_text:
        return f"过程 {process_text} 分。"
    if artifact_text:
        return f"产物质量 {artifact_text} 分。"
    return ""


def compose_feedback_note(data: dict) -> str:
    """Return the reviewer note, appending scores only when the text has none."""
    note = str(data.get("note") or data.get("platform_feedback_note") or "").strip()
    if data.get("suppress_score_append"):
        return note
    if SCORE_IN_NOTE.search(note):
        return note
    clause = score_clause(data)
    if not clause:
        return note
    if not note:
        return clause
    if note[-1] not in "。；;！？":
        note += "。"
    return note + clause


def _pick(items: list[str], salt: str) -> str:
    if not items:
        return ""
    digest = hashlib.md5(salt.encode("utf-8")).hexdigest()
    return items[int(digest, 16) % len(items)]


def default_audit_reason(
    feedback_quality: str,
    dirty_tag: str,
    note: str = "",
    *,
    salt: str = "",
    summary: str = "",
) -> str:
    """Build a short audit reason, rotating templates by ``salt``.

    ``feedback_quality`` uses the platform labels 完全可用 / 部分可用 / 完全不可用.
    Callers should still prefer a hand-written ``platform_audit_reason``.
    """
    cfg = load_writing_style()
    templates = cfg.get("audit_templates") or {}
    clean_tails = list(cfg.get("audit_clean_tails") or [""])
    default_dirty = "非脏数据"
    if dirty_tag in ("", default_dirty, "不选"):
        tail = _pick(clean_tails, f"{salt}:tail")
    else:
        tail = f"命中脏数据标签：{dirty_tag}。"
    if feedback_quality == "完全可用":
        family = templates.get("fully_usable") or []
    elif feedback_quality == "完全不可用":
        family = templates.get("unusable") or []
    else:
        family = templates.get("partly_usable") or []
    template = _pick(family, f"{salt}:body") or "{summary}。{tail}"
    body = template.format(summary=summary or "复核与标注可对照", tail=tail).strip()
    return re.sub(r"。{2,}", "。", body)


_RATING_VALUES = ("高质量", "合格", "不合格")
_PLATFORM_RATING = {
    "高质量": "完全可用",
    "合格": "部分可用",
    "不合格": "完全不可用",
}
_PLATFORM_WORDS = ("完全不可用", "部分可用", "完全可用")
_AUDIT_SHEET_PHRASES = (
    "故高质量",
    "故合格",
    "故不合格",
    "反馈质量为高质量",
    "反馈质量为合格",
    "反馈质量为不合格",
)
_TEMPLATE_NOTES = {
    "高质量": "标注人给执行过程 8 分、产物质量 8 分，测试模型的执行轨迹和最终产物分别与对应备注一致，评分正确，反馈质量为高质量。",
    "合格": "主页面能开和标注一致。过程 8 分相符，产物 9 分偏高，反馈质量为合格。",
    "不合格": "标注评语空泛且串图，属敷衍恶意打分，结论不可信。反馈质量为不合格。",
}
_ALIGN_RE = re.compile(r"相符|一致|打分准确|评分正确")
_QUALIFIED_GAP_RE = re.compile(
    r"偏高|偏低|不完善|不完整|缺(?:截图|步骤|证据|图)|"
    r"无法.{0,12}复核|不符|偏少|未覆盖|未测|理由偏短|佐证不足|"
    r"错选|标签与备注|归因.{0,16}不准确"
)
_PROCESS_SCORE_RE = re.compile(r"过程\s*\d+\s*分")
_ARTIFACT_SCORE_RE = re.compile(r"产物(?:质量)?\s*\d+\s*分")
_PROCESS_SCORE_VERDICT_RE = re.compile(
    r"过程\s*\d+\s*分.{0,24}(?:偏高|偏低|相符|合理)"
)
_ARTIFACT_SCORE_VERDICT_RE = re.compile(
    r"产物(?:质量)?\s*\d+\s*分.{0,24}(?:偏高|偏低|相符|合理)"
)

_PROCESS_GAP_RE = re.compile(
    r"(?:执行过程|过程)\s*\d+\s*分[^。；;，,、]{0,24}(?:偏高|偏低)|"
    r"(?:偏高|偏低)[^。；;，,、]{0,24}(?:执行过程|过程)\s*\d+\s*分"
)
_PROCESS_EVIDENCE_RE = re.compile(
    r"测试模型|模型执行|执行过程(?:中|里|实际)|运行轨迹|模型轨迹|轨迹中|"
    r"工具(?:调用)?|需求理解|规划|拆解|调试|自测|迭代|重试|恢复|"
    r"中断|卡住|报错|过早宣称|耗时|效率|token|轮次|多轮|过程标签|过程备注"
)
_REVIEWER_RECHECK_RE = re.compile(
    r"标注人(?:复测|验证|测试)|质检(?:员)?(?:复测|验证|测试)|本次(?:复测|验证|测试)|"
    r"当前环境|复测环境|隔离(?:环境|复测|测试)|清理(?:测试)?环境"
)
_UNATTRIBUTED_VALIDATION_RE = re.compile(
    r"清理.{0,12}配置|补齐(?:环境|依赖)|安装.{0,16}后|"
    r"重新(?:测试|构建|验证)|复跑|(?:测试|构建|编译)通过"
)
_MODEL_OWNED_VALIDATION_RE = re.compile(
    r"(?:测试模型|模型)(?:在轨迹中|执行过程中|运行时)?[^。；;\n]{0,32}"
    r"(?:自测|测试|构建|编译|验证|go\s+test|npm\s+(?:run\s+)?test|pytest)"
)
_PRODUCT_ONLY_CONTEXT_RE = re.compile(
    r"页面|主页面|界面|按钮|控件|路由|功能|章节|小节|主链路|业务链路|"
    r"响应式|加载|打开|可运行|能运行|能打开|白屏|遮挡|布局|交互|接口|"
    r"产物|交付物|截图"
)


def _process_score_rationale_issues(label: str, text: str) -> list[str]:
    """执行过程分偏高/偏低必须用模型执行过程证据解释。

    Product/runtime facts such as page flow or UI availability belong to the
    artifact-quality score. If a note says the execution-process score is high
    or low but the local sentence only cites product facts, reviewers cannot see
    what was wrong with the model's task-solving process.
    """
    blob = str(text or "")
    issues: list[str] = []
    # A reviewer rerun is artifact evidence unless the text explicitly ties the
    # validation action to the tested model's recorded trajectory.
    for verdict in _PROCESS_SCORE_VERDICT_RE.finditer(blob):
        start, end = verdict.span()
        left = max(
            blob.rfind("。", 0, start),
            blob.rfind("；", 0, start),
            blob.rfind(";", 0, start),
            blob.rfind("\n", 0, start),
        )
        right_candidates = [
            pos
            for pos in (
                blob.find("。", end),
                blob.find("；", end),
                blob.find(";", end),
                blob.find("\n", end),
            )
            if pos != -1
        ]
        right = min(right_candidates) if right_candidates else len(blob)
        sentence = blob[left + 1:right]
        if _REVIEWER_RECHECK_RE.search(sentence):
            issues.append(f"{label}-process-score-uses-reviewer-recheck")
        elif _UNATTRIBUTED_VALIDATION_RE.search(sentence) and not _MODEL_OWNED_VALIDATION_RE.search(sentence):
            issues.append(f"{label}-process-score-uses-unattributed-validation")
    for match in _PROCESS_GAP_RE.finditer(blob):
        start, end = match.span()
        left = max(
            blob.rfind("。", 0, start),
            blob.rfind("；", 0, start),
            blob.rfind(";", 0, start),
            blob.rfind("\n", 0, start),
        )
        right_candidates = [
            pos
            for pos in (
                blob.find("。", end),
                blob.find("；", end),
                blob.find(";", end),
                blob.find("\n", end),
            )
            if pos != -1
        ]
        right = min(right_candidates) if right_candidates else len(blob)
        sentence = blob[left + 1:right]
        context = blob[max(0, left - 80):right]
        if _PROCESS_EVIDENCE_RE.search(context):
            continue
        if _PRODUCT_ONLY_CONTEXT_RE.search(sentence) or _PRODUCT_ONLY_CONTEXT_RE.search(context):
            issues.append(f"{label}-process-score-gap-needs-model-execution-rationale")
        else:
            issues.append(f"{label}-process-score-gap-rationale-too-thin")
    return issues


def _score_clarity_issues(note: str) -> list[str]:
    """合格备注列出过程分或产物分时，必须写清偏高、偏低或相符。"""
    issues: list[str] = []
    if _PROCESS_SCORE_RE.search(note) and not _PROCESS_SCORE_VERDICT_RE.search(note):
        issues.append("note-qualified-process-score-need-high-low-or-match")
    if _ARTIFACT_SCORE_RE.search(note) and not _ARTIFACT_SCORE_VERDICT_RE.search(note):
        issues.append("note-qualified-artifact-score-need-high-low-or-match")
    return issues

_UNQUALIFIED_RE = re.compile(
    r"红线|敷衍|脏数据|不可信|串图|空评|轮次作弊|作弊|恶意打分|完全不可"
)
_DEFAULT_VAGUE = (
    "存在偏差",
    "证据不完整",
    "大体合理",
    "方向正确",
    "整体可核",
    "可核",
    "判断成立",
)
_AUDIT_ONLY_SCORE_RE = re.compile(
    r"^(?:"
    r"标注打分和产物实测情况一致，评分正确|"
    r"过程\s*\d+\s*分[、，,]\s*产物(?:质量)?\s*\d+\s*分和产物实测情况一致(?:，评分正确)?|"
    r"评分正确|"
    r"和产物实测情况一致，评分正确"
    r")，?反馈(?:完全可用|部分可用|完全不可用)。?$"
)
_AUDIT_WEAK_WORDS = ("可见", "已记录")
_AUDIT_CLOSE_RE = re.compile(r"反馈(?:完全可用|部分可用|完全不可用)")


def _cfg_rating_rationale(cfg: dict | None = None) -> dict:
    cfg = cfg or load_writing_style()
    block = cfg.get("feedback_rating_rationale") or {}
    return block if isinstance(block, dict) else {}


def _has_ambiguous_report_subject(text: str) -> bool:
    if "报告" not in text:
        return False
    if any(tag in text for tag in ("模型报告", "交付报告", "自评报告", "标注人报告")):
        return False
    return bool(re.search(r"报告(?:却)?声称|报告称|报告所[述写]|报告[里中]写", text))


def _contains_sheet_word(text: str, rating: str) -> bool:
    """Return True if the Feishu rating word appears in ``text``."""
    if rating == "合格":
        return "合格" in text.replace("不合格", "")
    return rating in text


def _sheet_words_in_text(text: str) -> list[str]:
    """Return Feishu rating words found in ``text`` (不合格 before 合格)."""
    found: list[str] = []
    if "高质量" in text:
        found.append("高质量")
    if "不合格" in text:
        found.append("不合格")
    elif "合格" in text:
        found.append("合格")
    return found


def _platform_words_in_text(text: str) -> list[str]:
    """Return platform option words found in ``text``, longest first."""
    return [word for word in _PLATFORM_WORDS if word in text]


def _audit_note_similarity_issues(note: str, audit: str) -> list[str]:
    """Flag audit reasons that are too close to the longer feedback note."""
    def compact(text: str) -> str:
        text = _AUDIT_CLOSE_RE.sub("", text)
        text = re.sub(r"\d+\s*分", "", text)
        text = re.sub(r"[，,。；;：:、\s]|标注人|评分|正确|相符|一致|反馈质量为高质量|反馈质量为合格|反馈质量为不合格", "", text)
        return text

    note_core = compact(note)
    audit_core = compact(audit)
    if len(note_core) < 24 or len(audit_core) < 16:
        return []
    if audit_core in note_core:
        return ["audit-too-similar-to-note"]
    grams = {audit_core[i : i + 2] for i in range(len(audit_core) - 1)}
    note_grams = {note_core[i : i + 2] for i in range(len(note_core) - 1)}
    if grams and len(grams & note_grams) / len(grams) >= 0.82:
        return ["audit-too-similar-to-note"]
    return []


def _shared_rationale_issues(label: str, text: str, vague: tuple[str, ...]) -> list[str]:
    """Return vague-phrase and ambiguous-subject issues for one field."""
    issues: list[str] = []
    for phrase in vague:
        if phrase and phrase in text:
            issues.append(f"{label}-vague-rating-phrase:{phrase}")
    if label == "audit" and _AUDIT_ONLY_SCORE_RE.fullmatch(text.strip()):
        issues.append("audit-only-score-consistency")
    if label == "audit":
        for phrase in _AUDIT_WEAK_WORDS:
            if phrase in text:
                issues.append(f"audit-weak-summary-word:{phrase}")
    if _has_ambiguous_report_subject(text):
        issues.append(f"{label}-ambiguous-report-subject")
    return issues


def scan_feedback_rating_rationale(
    note: str,
    audit: str,
    rating: str,
    *,
    prompt_cheat: bool = False,
    cfg: dict | None = None,
) -> list[str]:
    """Flag notes/audits that mix Feishu and platform rating words.

    ``note`` (飞书质量备注) must name 高质量 / 合格 / 不合格.
    ``audit`` (平台审核理由) must name 完全可用 / 部分可用 / 完全不可用
    and must not use the Feishu words or 故高质量 / 反馈质量为合格.
    """
    rating = str(rating or "").strip()
    note = str(note or "").strip()
    audit = str(audit or "").strip()
    if rating not in _RATING_VALUES:
        return []

    issues: list[str] = []
    block = _cfg_rating_rationale(cfg)
    vague = tuple(block.get("vague_phrases") or _DEFAULT_VAGUE)
    platform_word = _PLATFORM_RATING[rating]

    if note:
        if rating == "合格" and "不合格" in note and not _contains_sheet_word(note, rating):
            issues.append("note-rating-word-is-不合格-not-合格")
        elif not _contains_sheet_word(note, rating):
            issues.append(f"note-missing-rating-word:{rating}")
        if (
            "标注" not in note
            and not prompt_cheat
            and "轮次作弊" not in note
        ):
            issues.append("note-missing-annotator-subject")
        for word in _platform_words_in_text(note):
            issues.append(f"note-used-platform-word:{word}")
        issues.extend(_shared_rationale_issues("note", note, vague))
        issues.extend(_process_score_rationale_issues("note", note))
        issues.extend(scare_quote_issues(note))

    if not audit:
        issues.append("audit-missing-rating-rationale")
    else:
        if platform_word not in audit:
            issues.append(f"audit-missing-rating-word:{platform_word}")
        for word in _sheet_words_in_text(audit):
            issues.append(f"audit-used-sheet-word:{word}")
        for phrase in _AUDIT_SHEET_PHRASES:
            if phrase in audit:
                issues.append(f"audit-used-sheet-phrase:{phrase}")
        issues.extend(_shared_rationale_issues("audit", audit, vague))
        issues.extend(_process_score_rationale_issues("audit", audit))
        if not prompt_cheat:
            issues.extend(_audit_note_similarity_issues(note, audit))
        issues.extend(scare_quote_issues(audit))

    if rating == "高质量":
        if note and not _ALIGN_RE.search(note):
            issues.append("note-high-quality-missing-alignment")
        if _QUALIFIED_GAP_RE.search(note) and re.search(r"偏高|偏低", note):
            issues.append("note-high-quality-has-score-gap")
    elif rating == "合格" and not prompt_cheat:
        if note and not _QUALIFIED_GAP_RE.search(note):
            issues.append("note-qualified-missing-gap")
        if audit and not _QUALIFIED_GAP_RE.search(audit):
            issues.append("audit-qualified-missing-gap")
        issues.extend(_score_clarity_issues(note))
    elif rating == "不合格":
        blob = note + audit
        if blob and not _UNQUALIFIED_RE.search(blob):
            issues.append("unqualified-missing-reason")
    return issues


def opening_family_example_issues(cfg: dict | None = None) -> list[str]:
    """Every canned note/audit example must itself satisfy the split vocabulary."""
    cfg = cfg or load_writing_style()
    issues: list[str] = []
    for fam in cfg.get("opening_families") or cfg.get("opening_families") or []:
        fid = str(fam.get("id") or "unknown")
        example = str(fam.get("example") or fam.get("example") or "").strip()
        audit_example = str(
            fam.get("audit_example") or fam.get("audit_example") or ""
        ).strip()
        rating = str(fam.get("rating") or "").strip()
        if rating not in _RATING_VALUES:
            issues.append(f"template-{fid}-missing-rating-field")
            continue
        if not example:
            issues.append(f"template-{fid}-empty-example")
            continue
        if not audit_example:
            issues.append(f"template-{fid}-empty-audit-example")
            continue
        for item in scan_feedback_rating_rationale(
            example, audit_example, rating, cfg=cfg
        ):
            issues.append(f"template-{fid}:{item}")
        for item in dangling_opening_issues(example):
            issues.append(f"template-{fid}:{item}")
    for kind, rating in (
        ("fully_usable", "高质量"),
        ("partly_usable", "合格"),
        ("unusable", "不合格"),
    ):
        dummy_note = _TEMPLATE_NOTES[rating]
        for idx, template in enumerate((cfg.get("audit_templates") or {}).get(kind) or []):
            text = (
                str(template)
                .replace("{summary}", "核心页面能开")
                .replace("{tail}", "")
            )
            for item in scan_feedback_rating_rationale(
                dummy_note, text, rating, cfg=cfg
            ):
                issues.append(f"audit-template-{kind}-{idx}:{item}")
    return issues
