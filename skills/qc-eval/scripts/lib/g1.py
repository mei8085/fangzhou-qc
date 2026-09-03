"""Current-period constants: local source xlsx, Ark project, Feishu target, models."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .paths import REPO_ROOT, SKILL_DIR, default_g1_source_xlsx

CONFIG_PATH = SKILL_DIR / "config" / "g1.json"
_FALLBACK_CONFIG = {
    "period": "43期",
    "project_id": 315,
    "project_url": "https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/myprojects/315/task/6936",
    "audit_url_template": "https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/315/review/{taskModelRunId}?mode=audit",
    "audit_form_template": "skills/qc-eval/config/g1_audit_form.json",
    "source_xlsx": "docs/43.xlsx",
    "source_sheet": "Sheet1",
    "feishu_wiki": "https://bytedance.larkoffice.com/wiki/OY1Dw0dcailCxTk3UGOcykVznAf?sheet=nH0hX0",
    "feishu_sheet_id": "nH0hX0",
    "output_subdir": "ark_g1",
    "models": [
        {"sheet": "0819K-256K", "code": "0819K-256K", "platform": "drawbridge"},
        {"sheet": "0819K-1M", "code": "0819K-1M", "platform": "caldera"},
        {"sheet": "0819K-keepall-256K", "code": "0819K-keepall-256K", "platform": "bramble"},
        {"sheet": "0819K-keepall-1M", "code": "0819K-keepall-1M", "platform": "abacus"},
    ],
}


def load_g1_config() -> dict:
    """Return the current-period config with safe defaults for missing keys."""
    config = dict(_FALLBACK_CONFIG)
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    return config


_CONFIG = load_g1_config()
PERIOD = str(_CONFIG["period"])
PROJECT_ID = int(_CONFIG["project_id"])
PROJECT_URL = str(_CONFIG["project_url"])
AUDIT_URL_TEMPLATE = str(_CONFIG["audit_url_template"])
_audit_template = Path(str(_CONFIG["audit_form_template"]))
AUDIT_FORM_TEMPLATE = _audit_template if _audit_template.is_absolute() else REPO_ROOT / _audit_template
SOURCE_XLSX = default_g1_source_xlsx()
SOURCE_SHEET = str(_CONFIG.get("source_sheet") or "Sheet1")
FEISHU_WIKI = str(_CONFIG["feishu_wiki"])
FEISHU_SHEET_ID = str(_CONFIG["feishu_sheet_id"])
OUTPUT_SUBDIR = str(_CONFIG.get("output_subdir") or "ark_g1")
DEFAULT_DIRTY_TAG = "非脏数据"

# Feishu current-period dirty-tag dropdown. Non-dirty data stays blank.
FEISHU_DIRTY_TAG_OPTIONS = _CONFIG.get("feishu_dirty_tag_options") or [
    "模型资源问题:API请求超时/轨迹大量error",
    "OpenClaw/Hermes框架问题",
    "用户问题:低质量任务",
    "用户问题:敷衍恶意打分",
    "用户问题:AI打分/AI评价",
    "用户问题:用户切换模型错误",
    "用户问题:LLM任务测试VLM能力",
    "其他",
]
FEISHU_DIRTY_TAG_EMPTY = {"", "非脏数据", "不选", "无"}
_FEISHU_DIRTY_ALIAS = {
    "api请求超时/轨迹大量error": FEISHU_DIRTY_TAG_OPTIONS[0],
    "模型资源问题：api 请求超时 / 轨迹大量 error": FEISHU_DIRTY_TAG_OPTIONS[0],
    "openclaw / hermes 框架问题": FEISHU_DIRTY_TAG_OPTIONS[1],
    "低质量任务": FEISHU_DIRTY_TAG_OPTIONS[2],
    "敷衍恶意打分": FEISHU_DIRTY_TAG_OPTIONS[3],
    "完全敷衍": FEISHU_DIRTY_TAG_OPTIONS[3],
    "虚假反馈": FEISHU_DIRTY_TAG_OPTIONS[3],
    "trace和反馈结果明显不一致": FEISHU_DIRTY_TAG_OPTIONS[3],
    "ai 打分 / ai 评价": FEISHU_DIRTY_TAG_OPTIONS[4],
    "用户切换模型错误": FEISHU_DIRTY_TAG_OPTIONS[5],
    "llm任务测试vlm能力": FEISHU_DIRTY_TAG_OPTIONS[6],
    "题目红线（prompt 简单 / vlm 错配）": FEISHU_DIRTY_TAG_OPTIONS[6],
    "提示词轮次作弊": FEISHU_DIRTY_TAG_OPTIONS[2],
    "轮次作弊": FEISHU_DIRTY_TAG_OPTIONS[2],
}

# Sheet header/code → Ark platform codeName. Keep this sourced from g1.json.
_MODELS = _CONFIG.get("models") or _FALLBACK_CONFIG["models"]
SHEET_TO_PLATFORM = {
    str(item["sheet"]): str(item["platform"])
    for item in _MODELS
    if item.get("sheet") and item.get("platform")
}
CODE_TO_PLATFORM = {
    str(item.get("code") or item["sheet"]): str(item["platform"])
    for item in _MODELS
    if item.get("sheet") and item.get("platform")
}
PLATFORM_TO_SHEET = {v: k for k, v in SHEET_TO_PLATFORM.items()}
PLATFORM_TO_CODE = {v: k for k, v in CODE_TO_PLATFORM.items()}
SHEET_MODELS = list(SHEET_TO_PLATFORM.keys())
PLATFORM_CODES = list(CODE_TO_PLATFORM.values())
def sheet_model_label(sheet_name: str) -> str:
    """Return the Feishu audit-reason label with the Ark platform codeName.

    Example: ``0819K-256K`` -> ``0819K-256K（drawbridge）``. Unknown sheet names
    are returned unchanged so other periods keep their original prefixes.
    """
    name = str(sheet_name or "").strip()
    platform = SHEET_TO_PLATFORM.get(name)
    if not platform:
        return name
    return f"{name}（{platform}）"


def audit_url_for_run(task_model_run_id, config: dict | None = None) -> str:
    """Return the Ark QC form URL for one model run."""
    cfg = config or load_g1_config()
    template = str(cfg.get("audit_url_template") or AUDIT_URL_TEMPLATE)
    return template.format(taskModelRunId=task_model_run_id)


def sheet_model_for_platform(code_name: str) -> str | None:
    """Map an Ark platform codeName to the current sheet model header."""
    key = str(code_name or "").strip().lower()
    for platform, sheet in PLATFORM_TO_SHEET.items():
        if platform.lower() == key:
            return sheet
    return None


def is_feishu_dirty_tag_header(header: str) -> bool:
    """Return True for per-model dirty-tag columns, not the reason columns."""
    name = str(header or "").strip()
    return name.endswith("脏数据标签") and not name.endswith("脏数据标签理由")


def is_feishu_dirty_tag_reason_header(header: str) -> bool:
    """Return True for per-model dirty-tag reason columns."""
    return str(header or "").strip().endswith("脏数据标签理由")


def is_feishu_dirty_tag_related_header(header: str) -> bool:
    """Return True for dirty-tag dropdowns and their reason columns."""
    return is_feishu_dirty_tag_header(header) or is_feishu_dirty_tag_reason_header(header)


def _normalize_dirty_tag(value: str) -> str:
    text = str(value or "").strip().replace("：", ":")
    text = re.sub(r"\s+", "", text)
    return text.lower()


def is_empty_feishu_dirty_tag(value) -> bool:
    """Return True when the Feishu dirty-tag cell should stay blank."""
    if value is None:
        return True
    if isinstance(value, list):
        return all(is_empty_feishu_dirty_tag(item) for item in value)
    text = str(value).strip()
    if text in FEISHU_DIRTY_TAG_EMPTY:
        return True
    return _normalize_dirty_tag(text) in {_normalize_dirty_tag(item) for item in FEISHU_DIRTY_TAG_EMPTY}


def to_feishu_dirty_tag(value) -> str:
    """Map qc_cells dirty_tag values onto exact Feishu dropdown options.

    Non-dirty values become ``""``. Multiple tags are joined with顿号.
    Unrecognized names fall through to ``其他``.
    """
    if is_empty_feishu_dirty_tag(value):
        return ""
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
    else:
        parts = [part.strip() for part in re.split(r"[、,，;|]+", str(value)) if part.strip()]
    option_by_norm = {_normalize_dirty_tag(opt): opt for opt in FEISHU_DIRTY_TAG_OPTIONS}
    alias_by_norm = {_normalize_dirty_tag(key): target for key, target in _FEISHU_DIRTY_ALIAS.items()}
    mapped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if is_empty_feishu_dirty_tag(part):
            continue
        norm = _normalize_dirty_tag(part)
        option = option_by_norm.get(norm) or alias_by_norm.get(norm)
        if not option:
            option = "其他"
        if option not in seen:
            seen.add(option)
            mapped.append(option)
    return "、".join(mapped)
