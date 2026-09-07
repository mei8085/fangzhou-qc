"""Detect prompt-side tool-round quota cheating.

The client scores trajectory tool-call rounds itself. QC must not count rounds.
QC only checks whether the prompt tells the model to reach a round quota
(e.g. "工具轮次达到 450"). A hit makes the task unqualified and stops product
retest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PROMPT_KEYS = (
    "prompt",
    "userPrompt",
    "user_prompt",
    "taskPrompt",
    "task_prompt",
    "requirement",
    "requirementText",
    "requirement_text",
    "description",
    "content",
    "question",
    "userMessage",
    "user_message",
    "提示词",
    "题目",
)

SKIP_KEYS = {
    "evaluation",
    "audit",
    "trajectory",
    "workspace",
    "attachments",
    "cookies",
    "headers",
    "token",
}

ROUND_NOUN = (
    r"(?:工具(?:调用)?(?:轮次|次数)|调用轮次|交互轮次|"
    r"tool[- ]?calls?|function[- ]?calls?|tool[- ]?rounds?|"
    r"tool[- ]?use(?:s|d)?(?:\s+rounds?)?)"
)

QUOTA_VERB = (
    r"(?:达到|不少于|不低于|至少|超过|多于|高于|必须|要求|保证|确保|"
    r"做到|拉到|凑到|刷到|堆到|大于|不小于|最少|最低|"
    r"must(?:\s+be)?|at\s+least|no\s+less\s+than|more\s+than|greater\s+than|"
    r"minimum|min(?:imum)?)"
)

NUMBER = (
    r"(?:\d{2,}|"
    r"(?:十[一二三四五六七八九]?|[一二三四五六七八九两]十[一二三四五六七八九]?|"
    r"[一二三四五六七八九两]百[一二三四五六七八九十百千两]*|"
    r"[一二三四五六七八九两]千[一二三四五六七八九十百千两]*))"
)

NEG_PAD = re.compile(
    r"(?:不要|别|禁止|切勿|不得|无需|不要求|不要为了|避免).{0,20}"
    r"(?:凑|刷|灌|堆|撑|达到|要求).{0,12}(?:轮次|次数|tool[- ]?call)",
    re.I,
)

NEG_ADD_QUOTA = re.compile(
    r"(?:不要|别|禁止|切勿|不得).{0,16}(?:自行)?追加.{0,80}"
    r"(?:轮次|次数|tool[- ]?calls?|xx\s*次|\d+\s*次)",
    re.I,
)

HIT_PATTERNS = [
    re.compile(ROUND_NOUN + r".{0,24}" + QUOTA_VERB + r".{0,16}" + NUMBER, re.I),
    re.compile(QUOTA_VERB + r".{0,16}" + NUMBER + r".{0,12}" + ROUND_NOUN, re.I),
    re.compile(
        r"(?:凑|刷|灌|堆|撑)(?:够|满|到)?(?:工具)?(?:调用)?(?:轮次|次数)",
        re.I,
    ),
    re.compile(
        r"(?:即使|哪怕|就算).{0,16}(?:完成|做完|结束).{0,24}"
        r"(?:继续|反复|不停).{0,20}(?:调用|轮次)",
        re.I,
    ),
    re.compile(
        r"(?:完成|做完|结束后?).{0,12}(?:也要|仍要|继续).{0,16}"
        r"(?:调用工具|工具调用|凑|刷).{0,12}(?:轮次|次数)",
        re.I,
    ),
    re.compile(
        r"(?:pad|padding|inflate|farm)\s+(?:tool[- ]?calls?|rounds?)",
        re.I,
    ),
    re.compile(
        r"(?:min(?:imum)?|required)[-_ ]?(?:tool[-_ ]?calls?|rounds?)\s*[=:]\s*"
        + NUMBER,
        re.I,
    ),
    re.compile(
        ROUND_NOUN + r"\s*(?:>=|≥|>|＞|大于|超过)\s*" + NUMBER,
        re.I,
    ),
    re.compile(
        r"(?:至少|不少于|不低于|必须|要求).{0,12}调用工具.{0,12}" + NUMBER + r"\s*次",
        re.I,
    ),
    re.compile(
        r"调用工具.{0,12}(?:至少|不少于|不低于|必须).{0,12}" + NUMBER + r"\s*次",
        re.I,
    ),
]


def _as_text(value: Any) -> str:
    """Flatten nested prompt payloads into a single readable string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_as_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        preferred = []
        for key in ("text", "content", "prompt", "value", "message"):
            if key in value:
                preferred.append(_as_text(value.get(key)))
        if preferred:
            return "\n".join(part for part in preferred if part)
        return "\n".join(
            _as_text(item)
            for key, item in value.items()
            if str(key).lower() not in SKIP_KEYS
        )
    return str(value)


def extract_prompt_text(payload: Any) -> str:
    """Return the longest likely prompt string from a task.json payload.

    Explicit prompt-like keys win over generic description/content fields so a
    long metadata blob does not hide the actual user prompt.
    """
    preferred: list[str] = []
    found: list[str] = []
    preferred_keys = {
        "prompt", "userprompt", "user_prompt", "taskprompt", "task_prompt", "提示词",
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_s = str(key)
                if key_s.lower() in SKIP_KEYS:
                    continue
                if key_s in PROMPT_KEYS or key_s.lower() in {k.lower() for k in PROMPT_KEYS}:
                    text = _as_text(value).strip()
                    if len(text) >= 8:
                        if key_s.lower() in preferred_keys or key_s == "提示词":
                            preferred.append(text)
                        else:
                            found.append(text)
                walk(value)
            return
        if isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    pool = preferred or found
    if not pool:
        return ""
    pool.sort(key=len, reverse=True)
    return pool[0].replace("\r\n", "\n").replace("\r", "\n")


def _line_is_negative(line: str) -> bool:
    return bool(NEG_PAD.search(line) or NEG_ADD_QUOTA.search(line))


def _line_hits(line: str) -> list[str]:
    """Return matching pattern snippets on one line, ignoring anti-pad wording."""
    text = str(line or "").strip()
    if not text or _line_is_negative(text):
        return []
    hits: list[str] = []
    for pattern in HIT_PATTERNS:
        match = pattern.search(text)
        if match:
            snippet = match.group(0).strip()
            if snippet and snippet not in hits:
                hits.append(snippet)
    return hits


def scan_round_cheat(prompt: str) -> list[dict[str, Any]]:
    """Return cheat hits with 1-based line numbers and quoted snippets.

    Adjacent lines are also joined so a quota split across two lines still hits.
    """
    lines = str(prompt or "").splitlines() or [""]
    hits: list[dict[str, Any]] = []
    seen_lines: set[int] = set()

    def add_hit(line_no: int, line: str, snippets: list[str]) -> None:
        if line_no in seen_lines:
            return
        seen_lines.add(line_no)
        hits.append({
            "line": line_no,
            "text": line.strip(),
            "snippets": snippets,
        })

    for idx, line in enumerate(lines, start=1):
        snippets = _line_hits(line)
        if snippets:
            add_hit(idx, line, snippets)

    for idx in range(len(lines) - 1):
        left = lines[idx]
        right = lines[idx + 1]
        joined = f"{left} {right}"
        snippets = _line_hits(joined)
        if not snippets:
            continue
        if _line_hits(left) or _line_hits(right):
            continue
        add_hit(idx + 1, left, snippets)
        add_hit(idx + 2, right, snippets)

    hits.sort(key=lambda item: item["line"])
    return hits


def highlight_windows(
    n_lines: int,
    hit_lines: list[int],
    radius: int = 10,
    max_windows: int = 2,
) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """Build screenshot windows around cheat lines.

    Each window is (start, end, highlight_spans) using 1-based line numbers.
    """
    if n_lines < 1:
        return [(1, 1, [])]
    unique = sorted({int(n) for n in hit_lines if 1 <= int(n) <= n_lines})
    if not unique:
        end = min(n_lines, 70)
        return [(1, end, [])]

    clusters: list[list[int]] = [[unique[0]]]
    for line_no in unique[1:]:
        if line_no <= clusters[-1][-1] + radius:
            clusters[-1].append(line_no)
        else:
            clusters.append([line_no])

    windows: list[tuple[int, int, list[tuple[int, int]]]] = []
    for cluster in clusters[:max_windows]:
        center_low = cluster[0]
        center_high = cluster[-1]
        start = max(1, center_low - radius)
        end = min(n_lines, center_high + radius)
        spans: list[tuple[int, int]] = []
        for line_no in cluster:
            if spans and line_no <= spans[-1][1] + 1:
                spans[-1] = (spans[-1][0], line_no)
            else:
                spans.append((line_no, line_no))
        windows.append((start, end, spans))
    return windows


def is_prompt_cheat_task(task_dir: Path, qc: dict | None = None) -> bool:
    """Return True when this task already failed the prompt round-quota gate."""
    sheet = (qc or {}).get("sheet") or {}
    if sheet.get("prompt_cheat") is True:
        return True
    kind = str(sheet.get("prompt_cheat_kind") or sheet.get("prompt_cheat") or "").strip()
    if "轮次作弊" in kind:
        return True
    report_path = task_dir / "prompt_cheat.json"
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except Exception:
            report = {}
        if report.get("hit") or report.get("cheating"):
            return True
    return False


def load_task_payload(path: Path) -> Any:
    """Load task.json written by fetch_g1_platform.js / fetch_36_platform.js."""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def find_task_json(task_dir: Path) -> Path | None:
    """Locate collected task.json under ark_g1 or sibling collector folders."""
    for name in ("ark_g1", "ark38", "ark36", "ark_platform"):
        candidate = task_dir / name / "task.json"
        if candidate.exists():
            return candidate
    matches = sorted(task_dir.glob("*/task.json"))
    return matches[0] if matches else None


def quote_hits(hits: list[dict[str, Any]], limit: int = 2) -> str:
    """Build a short reviewer-facing quote of the cheating clauses."""
    snippets: list[str] = []
    for hit in hits:
        for snippet in hit.get("snippets") or []:
            text = str(snippet).strip()
            if text and text not in snippets:
                snippets.append(text)
        line = str(hit.get("text") or "").strip()
        if line and line not in snippets:
            snippets.append(line)
        if len(snippets) >= limit:
            break
    if not snippets:
        return "要求模型达到指定工具轮次"
    quoted = snippets[0]
    if len(quoted) > 48:
        quoted = quoted[:45] + "…"
    return quoted


def self_test() -> list[str]:
    """Return failed assertion messages. Empty means the detector is healthy."""
    errors: list[str] = []

    def expect(name: str, text: str, should_hit: bool) -> None:
        hits = scan_round_cheat(text)
        got = bool(hits)
        if got != should_hit:
            errors.append(f"{name}: expected hit={should_hit} got={got} text={text!r}")

    expect("quota-zh", "请确保工具调用轮次达到450轮后再交付。", True)
    expect("at-least", "模型至少调用工具 100 次。", True)
    expect("pad", "如果轮次不够就刷轮次，重复调用无意义工具。", True)
    expect("keep-going", "即使任务完成也要继续调用工具直到轮次够。", True)
    expect("english", "You must make at least 450 tool calls before finishing.", True)
    expect("min-field", "min_tool_calls: 200", True)
    expect("tool-comparison", "工具调用次数 >= 450", True)
    expect("tool-comparison-split", "工具调用次数\n≥ 450", True)
    expect("business-count", "- 异常次数 > 10 次：红色标签", False)
    expect("business-retries", "重试次数 > 10 次时告警", False)
    expect("upper-bound", "工具调用次数 ≤ 100", False)
    expect("clean-task", "基于订单明细分析退款率，并输出可执行建议。", False)
    expect("complexity-no-quota", "需要多步骤规划、工具协作和验证。", False)
    expect("one-tool-call", "`sessionToolCalls` 中有至少一个工具调用（Agent 确实在工作）", False)
    expect("forbid-pad", "不要为了凑轮次而重复调用无意义工具。", False)
    expect("split-lines", "工具轮次必须\n达到 450。", True)

    nested = {"task": {"title": "demo", "prompt": "要求工具调用次数不少于120次"}}
    extracted = extract_prompt_text(nested)
    if "不少于120" not in extracted:
        errors.append(f"extract nested prompt failed: {extracted!r}")
    return errors
