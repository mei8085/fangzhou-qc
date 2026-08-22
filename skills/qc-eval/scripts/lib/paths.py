"""Cross-platform repo paths and 38-period source xlsx resolution."""

from __future__ import annotations

import os
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = LIB_DIR.parent
SKILL_DIR = SCRIPTS_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent

SOURCE_XLSX_NAME = "众测质检38.xlsx"
WINDOWS_LEGACY_SOURCE = Path("D:/fz/fangzhou") / SOURCE_XLSX_NAME


def default_source_xlsx() -> Path:
    """Return the local 38-period source workbook path.

    Resolution order:
    1. ``QC_SOURCE_XLSX`` environment variable, if set
    2. Windows legacy path ``D:/fz/fangzhou/众测质检38.xlsx``, if it exists
    3. Repo-local ``data/众测质检38.xlsx`` (default write location on macOS/Linux)
    """
    env = os.environ.get("QC_SOURCE_XLSX", "").strip()
    if env:
        return Path(env).expanduser()
    if WINDOWS_LEGACY_SOURCE.exists():
        return WINDOWS_LEGACY_SOURCE
    return REPO_ROOT / "data" / SOURCE_XLSX_NAME
