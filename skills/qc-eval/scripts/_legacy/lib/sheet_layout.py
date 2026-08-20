"""Parse Sheet2 / Sheet3 headers to discover per-model column mapping.

Sheet2 header pattern (example):
  A: 任务ID
  B: 任务
  C: Prompt
  D: 评估链接
  E: 任务质量（题目质量）
  F: 题目质量说明
  G: 题目是否可验证
  H: 不可验证原因
  I,J,K: <model>反馈质量（作业质量），<model>验证截图，<model>质量备注
  ...repeat per model...
  last: 质检人

Sheet3 header pattern:
  A..N: <model_name>           (one column per model, contains zip attachment)
  next: 原始项目
  last: 任务ID

The parser is permissive — model order is whatever the sheet declares, and
column counts adapt to however many models appear.
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass, field


def col_letter(idx0: int) -> str:
    """0-based index -> A1 column letter (0->A, 25->Z, 26->AA)."""
    s = ""
    n = idx0
    while True:
        s = string.ascii_uppercase[n % 26] + s
        n = n // 26 - 1
        if n < 0:
            break
    return s


@dataclass
class ModelColumns:
    name: str
    rating: str       # e.g. "I"
    screenshot: str   # e.g. "J"
    note: str         # e.g. "K"


@dataclass
class Sheet2Layout:
    id_col: str = "A"
    task_col: str = "B"
    prompt_col: str = "C"
    eval_col: str = "D"
    prompt_quality_col: str = "E"
    prompt_quality_note_col: str = "F"
    verifiable_col: str = "G"
    verifiable_reason_col: str = "H"
    reviewer_col: str = ""
    models: list[ModelColumns] = field(default_factory=list)

    def model(self, name: str) -> ModelColumns:
        for m in self.models:
            if m.name == name:
                return m
        raise KeyError(f"model {name!r} not in Sheet2 layout")


_RATING_SUFFIX = "反馈质量"
_SHOT_SUFFIX = "验证截图"
_NOTE_SUFFIX = "质量备注"


def parse_sheet2(header: list) -> Sheet2Layout:
    """Build a Sheet2Layout from the first row of Sheet2."""
    layout = Sheet2Layout()
    pending: dict[str, dict[str, str]] = {}

    for i, raw in enumerate(header):
        h = str(raw or "").strip()
        col = col_letter(i)
        if not h:
            continue
        if h == "任务ID":
            layout.id_col = col
        elif h == "任务":
            layout.task_col = col
        elif h == "Prompt":
            layout.prompt_col = col
        elif h == "评估链接":
            layout.eval_col = col
        elif h.startswith("任务质量"):
            layout.prompt_quality_col = col
        elif h == "题目质量说明":
            layout.prompt_quality_note_col = col
        elif h == "题目是否可验证":
            layout.verifiable_col = col
        elif h == "不可验证原因":
            layout.verifiable_reason_col = col
        elif h == "质检人":
            layout.reviewer_col = col
        else:
            # model-scoped: "<model><suffix>" — match the longest suffix first
            for suffix, kind in ((_RATING_SUFFIX, "rating"),
                                  (_SHOT_SUFFIX, "screenshot"),
                                  (_NOTE_SUFFIX, "note")):
                idx = h.find(suffix)
                if idx > 0:
                    model_name = h[:idx]
                    pending.setdefault(model_name, {})[kind] = col
                    break

    for name, cols in pending.items():
        if {"rating", "screenshot", "note"} <= cols.keys():
            layout.models.append(ModelColumns(
                name=name,
                rating=cols["rating"],
                screenshot=cols["screenshot"],
                note=cols["note"],
            ))
    return layout


@dataclass
class Sheet3Layout:
    id_col: str = ""
    source_col: str = ""
    models: dict[str, str] = field(default_factory=dict)  # model_name -> col_letter


def parse_sheet3(header: list) -> Sheet3Layout:
    """Build a Sheet3Layout. Anything that isn't '任务ID' or '原始项目' is a model column."""
    layout = Sheet3Layout()
    for i, raw in enumerate(header):
        h = str(raw or "").strip()
        col = col_letter(i)
        if not h:
            continue
        if h == "任务ID":
            layout.id_col = col
        elif h == "原始项目":
            layout.source_col = col
        else:
            layout.models[h] = col
    return layout


def find_row_by_id(values: list[list], col_idx0: int, task_id: str) -> int | None:
    """Search the column at col_idx0 for task_id, return 1-based row number, or None."""
    for i, row in enumerate(values):
        if i == 0:
            continue  # skip header
        if len(row) > col_idx0 and str(row[col_idx0] or "").strip() == task_id:
            return i + 1
    return None


def col_letter_to_idx0(letter: str) -> int:
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch.upper()) - ord("A") + 1)
    return n - 1
