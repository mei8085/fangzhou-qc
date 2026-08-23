"""Shared QC writing-style helpers: banned jargon, note variety, audit templates.

Style source of truth for agents is SKILL.md plus docs/描述语言参考.xlsx.
This module only encodes the machine-checkable bits used by selfcheck and
the delivery scripts. Colloquial replacements live in writing_style.json
``preferred_replacements`` (说得通→合理, 对得上→相符/一致, 写重了→描述偏重,
抬上去了→得益于).
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
    """Return the on-disk writing-style config, or a safe empty fallback."""
    if not CONFIG_PATH.exists():
        return {
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
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _compiled_banned_regex(cfg: dict | None = None) -> list[re.Pattern[str]]:
    cfg = cfg or load_writing_style()
    return [re.compile(p) for p in cfg.get("banned_regex") or [] if p]


def scan_banned_style(text: str, cfg: dict | None = None) -> list[str]:
    """Return style issue tokens for banned QC jargon in ``text``."""
    cfg = cfg or load_writing_style()
    issues: list[str] = []
    seen: set[str] = set()
    for phrase in cfg.get("banned_phrases") or []:
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
