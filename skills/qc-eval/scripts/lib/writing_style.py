"""Shared QC writing-style helpers: banned jargon, note variety, audit templates.

Style source of truth for agents is SKILL.md plus docs/描述语言参考.xlsx.
This module only encodes the machine-checkable bits used by selfcheck and
the delivery scripts. Colloquial replacements live in writing_style.json
``preferred_replacements`` (说得通→合理, 对得上→相符/一致, 写重了→描述偏重,
抬上去了→得益于). Feedback-quality notes must also name the rating
(高质量 / 合格 / 不合格) and the concrete reason for that band.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .paths import SKILL_DIR

CONFIG_PATH = SKILL_DIR / "config" / "writing_style.json"
SCORE_IN_NOTE = re.compile(r"\d+\s*分")
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
        "min_distinct_note_openings": 3,
        "note_opening_chars": 8,
        "audit_ending_chars": 10,
        "min_same_audit_ending": 4,
        "task_opening_chars": 10,
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
    """Return style issue tokens for banned QC jargon in ``text``."""
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
    return issues


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
    """Strip ``【G1】S347（harrier）：`` or ``summit：`` from an audit-reason line."""
    return MODEL_AUDIT_PREFIX.sub("", str(line or "").strip(), count=1).strip()


def repeated_opening_issues(texts: list[str], cfg: dict | None = None) -> list[str]:
    """Flag model notes that share the same opening clause."""
    cfg = cfg or load_writing_style()
    n_chars = int(cfg.get("note_opening_chars") or 8)
    min_distinct = int(cfg.get("min_distinct_note_openings") or 3)
    prefixes = [opening_prefix(t, n_chars) for t in texts if str(t or "").strip()]
    if len(prefixes) < min_distinct:
        return []
    distinct = {p for p in prefixes if p}
    if len(distinct) < min(min_distinct, len(prefixes)):
        top = Counter(prefixes).most_common(1)[0]
        return [f"style-same-opening:{top[0]}x{top[1]}"]
    return []


def majority_score_prefix_issues(texts: list[str], cfg: dict | None = None) -> list[str]:
    """Flag when most model notes start with the frozen score-prefix template."""
    cfg = cfg or load_writing_style()
    prefix = str(cfg.get("score_prefix") or "标注人给执行过程")
    notes = [str(t or "").strip() for t in texts if str(t or "").strip()]
    if len(notes) < 3:
        return []
    hits = sum(1 for note in notes if note.startswith(prefix))
    if hits >= 3:
        return [f"style-same-score-prefix:{hits}"]
    return []


def repeated_audit_ending_issues(text: str, cfg: dict | None = None) -> list[str]:
    """Flag when most per-model audit lines share the same closing clause."""
    cfg = cfg or load_writing_style()
    n_chars = int(cfg.get("audit_ending_chars") or 10)
    min_same = int(cfg.get("min_same_audit_ending") or 4)
    lines = [strip_audit_model_prefix(line) for line in str(text or "").splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < min_same:
        return []
    endings = [line[-n_chars:] for line in lines if len(line) >= n_chars]
    if not endings:
        return []
    top, count = Counter(endings).most_common(1)[0]
    if count >= min_same:
        return [f"style-same-audit-ending:{top}x{count}"]
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
        return f"过程 {process_text} 分、产物 {artifact_text} 分。"
    if process_text:
        return f"过程 {process_text} 分。"
    if artifact_text:
        return f"产物 {artifact_text} 分。"
    return ""


def compose_feedback_note(data: dict) -> str:
    """Return the reviewer note, appending scores only when the text has none."""
    note = str(data.get("note") or data.get("platform_feedback_note") or "").strip()
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
_ALIGN_RE = re.compile(r"相符|一致|打分准确")
_QUALIFIED_GAP_RE = re.compile(
    r"偏高|偏低|不完善|不完整|缺(?:截图|步骤|证据|图)|"
    r"无法.{0,12}复核|不符|偏重|偏少|未覆盖|未测|理由偏短|佐证不足"
)
_UNQUALIFIED_RE = re.compile(
    r"红线|敷衍|脏数据|不可信|串图|空评|轮次作弊|作弊|恶意打分|完全不可"
)
_DEFAULT_VAGUE = (
    "存在偏差",
    "证据不完整",
    "大体合理",
    "方向正确",
    "整体可核",
    "判断成立",
)


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


def scan_feedback_rating_rationale(
    note: str,
    audit: str,
    rating: str,
    *,
    prompt_cheat: bool = False,
    cfg: dict | None = None,
) -> list[str]:
    """Flag notes/audits that do not explain the feedback-quality band.

    Reviewers must see why the annotator's work is 高质量 / 合格 / 不合格.
    Describing the model product alone is not enough.
    """
    rating = str(rating or "").strip()
    note = str(note or "").strip()
    audit = str(audit or "").strip()
    if rating not in _RATING_VALUES:
        return []

    issues: list[str] = []
    block = _cfg_rating_rationale(cfg)
    vague = tuple(
        block.get("vague_phrases") or block.get("vague_phrases") or _DEFAULT_VAGUE
    )

    for label, text in (("note", note), ("audit", audit)):
        if not text:
            if label == "audit":
                issues.append("audit-missing-rating-rationale")
            continue
        if rating == "合格":
            if "不合格" in text and "合格" not in text.replace("不合格", ""):
                issues.append(f"{label}-rating-word-is-不合格-not-合格")
            elif "合格" not in text.replace("不合格", ""):
                issues.append(f"{label}-missing-rating-word:合格")
        elif rating not in text:
            issues.append(f"{label}-missing-rating-word:{rating}")
        for phrase in vague:
            if phrase and phrase in text:
                issues.append(f"{label}-vague-rating-phrase:{phrase}")
        if _has_ambiguous_report_subject(text):
            issues.append(f"{label}-ambiguous-report-subject")

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
    elif rating == "不合格":
        blob = note + audit
        if blob and not _UNQUALIFIED_RE.search(blob):
            issues.append("unqualified-missing-reason")
    return issues


def opening_family_example_issues(cfg: dict | None = None) -> list[str]:
    """Every canned example must itself satisfy the rating-rationale rules."""
    cfg = cfg or load_writing_style()
    issues: list[str] = []
    for fam in cfg.get("opening_families") or []:
        fid = str(fam.get("id") or "unknown")
        example = str(fam.get("example") or "").strip()
        rating = str(fam.get("rating") or "").strip()
        if rating not in _RATING_VALUES:
            issues.append(f"template-{fid}-missing-rating-field")
            continue
        if not example:
            issues.append(f"template-{fid}-empty-example")
            continue
        for item in scan_feedback_rating_rationale(example, example, rating, cfg=cfg):
            issues.append(f"template-{fid}:{item}")
    for kind, rating in (
        ("fully_usable", "高质量"),
        ("partly_usable", "合格"),
        ("unusable", "不合格"),
    ):
        for idx, template in enumerate((cfg.get("audit_templates") or {}).get(kind) or []):
            text = (
                str(template)
                .replace("{summary}", "核心页面能开")
                .replace("{tail}", "")
            )
            for item in scan_feedback_rating_rationale(text, text, rating, cfg=cfg):
                issues.append(f"audit-template-{kind}-{idx}:{item}")
    return issues
