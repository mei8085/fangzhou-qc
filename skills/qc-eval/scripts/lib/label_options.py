"""Current-period task label options and lightweight label inference."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import REPO_ROOT, SKILL_DIR

CONFIG_PATH = SKILL_DIR / "config" / "g1_label_options.json"
LABEL_HEADER = "label"
LABEL_KEYS = ("label", "task_label", "category_label")


def load_label_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {"options": [], "default": ""}


def label_options() -> list[str]:
    return [str(item) for item in load_label_config().get("options") or []]


def _clean(value) -> str:
    return str(value or "").strip()


def read_label_from_sheet(sheet: dict | None) -> str:
    sheet = sheet or {}
    for key in LABEL_KEYS:
        value = _clean(sheet.get(key))
        if value:
            return value
    return ""


def validate_label(value: str) -> str:
    label = _clean(value)
    if not label:
        return ""
    opts = label_options()
    if label in opts:
        return label
    raise ValueError(
        f"invalid label {label!r}; allowed options: {', '.join(opts)}"
    )


def _read_prompt_text(task_id: str) -> str:
    if not task_id:
        return ""
    for path in (
        REPO_ROOT / "tasks" / task_id / "prompt.md",
        REPO_ROOT / "tasks" / task_id / "ark_g1" / "task.json",
    ):
        if path.exists():
            try:
                return path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
    return ""


def infer_task_label(task_title: str = "", prompt_text: str = "") -> str:
    cfg = load_label_config()
    text = f"{task_title}\n{prompt_text}".lower()
    for rule in cfg.get("heuristics") or []:
        label = validate_label(rule.get("label"))
        for keyword in rule.get("keywords") or []:
            pattern = str(keyword).lower()
            if not pattern:
                continue
            if re.search(pattern, text, flags=re.IGNORECASE):
                return label
    return validate_label(cfg.get("default"))


def resolve_task_label(
    *,
    existing_label: str = "",
    sheet: dict | None = None,
    task_title: str = "",
    task_id: str = "",
) -> str:
    """Return the label to use when the source/remote label cell is blank.

    Existing non-empty sheet values are left untouched by callers. When the
    source label is blank, prefer an explicit qc_cells sheet label, then infer
    from the task title and prompt using the configured 41期 option list.
    """
    existing = _clean(existing_label)
    if existing:
        return validate_label(existing)
    explicit = read_label_from_sheet(sheet)
    if explicit:
        return validate_label(explicit)
    return infer_task_label(task_title, _read_prompt_text(str(task_id)))
