"""Cross-platform repo paths and current-period source xlsx resolution."""

from __future__ import annotations

import os
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = LIB_DIR.parent
SKILL_DIR = SCRIPTS_DIR.parent
REPO_ROOT = SKILL_DIR.parent.parent

SOURCE_XLSX_NAME_38 = "众测质检38.xlsx"
WINDOWS_LEGACY_SOURCE_38 = Path("D:/fz/fangzhou") / SOURCE_XLSX_NAME_38
G1_SOURCE_XLSX = REPO_ROOT / "docs" / "G1-new.xlsx"


def default_g1_source_xlsx() -> Path:
    """Return the G1-new local source workbook path.

    Resolution order:
    1. ``QC_SOURCE_XLSX`` environment variable, if set
    2. Repo-local ``docs/G1-new.xlsx``
    """
    env = os.environ.get("QC_SOURCE_XLSX", "").strip()
    if env:
        return Path(env).expanduser()
    return G1_SOURCE_XLSX


def default_38_source_xlsx() -> Path:
    """Return the legacy 38-period source workbook path."""
    env = os.environ.get("QC_SOURCE_XLSX_38", "").strip()
    if env:
        return Path(env).expanduser()
    if WINDOWS_LEGACY_SOURCE_38.exists():
        return WINDOWS_LEGACY_SOURCE_38
    return REPO_ROOT / "data" / SOURCE_XLSX_NAME_38


def default_source_xlsx() -> Path:
    """Return the current-period source workbook (G1-new)."""
    return default_g1_source_xlsx()
