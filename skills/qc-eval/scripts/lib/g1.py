"""G1-new period constants: local source xlsx, Ark project, Feishu target, models."""

from __future__ import annotations

import json
from pathlib import Path

from .paths import REPO_ROOT, SKILL_DIR

CONFIG_PATH = SKILL_DIR / "config" / "g1.json"
PERIOD = "G1-new"
PROJECT_ID = 277
PROJECT_URL = (
    "https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/277?tab=review"
)
AUDIT_URL_TEMPLATE = (
    "https://ark.volcengine.com/autocase/region:cn-beijing/crowdtest/projects/"
    "277/review/{taskModelRunId}?mode=audit"
)
AUDIT_FORM_TEMPLATE = SKILL_DIR / "config" / "g1_audit_form.json"
SOURCE_XLSX = REPO_ROOT / "docs" / "G1-new.xlsx"
SOURCE_SHEET = "Sheet1"
FEISHU_WIKI = "https://bytedance.larkoffice.com/wiki/OY1Dw0dcailCxTk3UGOcykVznAf?sheet=cHr9N5"
FEISHU_SHEET_ID = "cHr9N5"
OUTPUT_SUBDIR = "ark_g1"
DEFAULT_DIRTY_TAG = "非脏数据"

# sheet header prefix → platform codeName
SHEET_TO_PLATFORM = {
    "【G1】S347": "harrier",
    "【G1】S20": "grotto",
    "【G1】S53": "ferrite",
    "【G1】S60": "estuary",
    "【G1】S1075": "dendrite",
}
CODE_TO_PLATFORM = {
    "S347": "harrier",
    "S20": "grotto",
    "S53": "ferrite",
    "S60": "estuary",
    "S1075": "dendrite",
}
PLATFORM_TO_SHEET = {v: k for k, v in SHEET_TO_PLATFORM.items()}
PLATFORM_TO_CODE = {v: k for k, v in CODE_TO_PLATFORM.items()}
SHEET_MODELS = list(SHEET_TO_PLATFORM.keys())
PLATFORM_CODES = list(CODE_TO_PLATFORM.values())


def load_g1_config() -> dict:
    """Return the on-disk G1-new config, falling back to the in-module constants."""
    if not CONFIG_PATH.exists():
        return {
            "period": PERIOD,
            "project_id": PROJECT_ID,
            "project_url": PROJECT_URL,
            "source_xlsx": str(SOURCE_XLSX),
            "source_sheet": SOURCE_SHEET,
            "feishu_wiki": FEISHU_WIKI,
            "feishu_sheet_id": FEISHU_SHEET_ID,
            "output_subdir": OUTPUT_SUBDIR,
            "models": [
                {"sheet": sheet, "code": PLATFORM_TO_CODE[platform], "platform": platform}
                for sheet, platform in SHEET_TO_PLATFORM.items()
            ],
        }
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def sheet_model_label(sheet_name: str) -> str:
    """Return the Feishu audit-reason label with the Ark platform codeName.

    Example: ``【G1】S347`` -> ``【G1】S347（harrier）``. Unknown sheet names
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
    """Map an Ark platform codeName (harrier/grotto/...) to the G1 sheet model header."""
    key = str(code_name or "").strip().lower()
    for platform, sheet in PLATFORM_TO_SHEET.items():
        if platform.lower() == key:
            return sheet
    return None
