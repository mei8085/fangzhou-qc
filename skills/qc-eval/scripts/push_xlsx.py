#!/usr/bin/env python3
"""Build one delivery xlsx per task — from a BLANK workbook, never by copying
the source file.

Why blank? The source workbook ships embedded verification screenshots for
hundreds of other reviewers' rows. Copying + delete_rows leaves those PNGs in
the file as orphan drawings (openpyxl tracks drawings by anchor, independent
of cell data), which would leak other reviewers' evidence into our delivery.

So the script reads the source read-only, then constructs a new workbook
containing only the header row, the single task row, the column widths, and
fresh data-validation rules pointing at row 2. Reviewer-owned cells are filled
from tasks/<TASK_ID>/qc_cells.json after the rebuild.

Usage:
    push_xlsx.py <TASK_ID> [<TASK_ID> ...]
        [--source <repo>/docs/41.xlsx]
        [--sheet Sheet1]
        [--period 41期]
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import copy
from pathlib import Path

import openpyxl
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.paths import REPO_ROOT, default_g1_source_xlsx, default_38_source_xlsx  # noqa: E402
from lib.writing_style import compose_feedback_note  # noqa: E402
from lib.g1 import to_feishu_dirty_tag  # noqa: E402
from lib.label_options import LABEL_HEADER, resolve_task_label  # noqa: E402

DEFAULT_SOURCE = default_g1_source_xlsx()
DEFAULT_SHEET = "Sheet1"
SOURCE_38 = default_38_source_xlsx()
SHEET_38 = "38期coding质检"
SOURCE_G1 = DEFAULT_SOURCE
SHEET_G1 = DEFAULT_SHEET
MACHINE_QC_HEADER = "机器质检结果是否正确"
MACHINE_QC_OPTIONS = ("正确", "部分正确可参考", "错误")
PERIOD_PRESETS = {
    "G1-new": (SOURCE_G1, SHEET_G1),
    "41期": (SOURCE_G1, SHEET_G1),
    "38期": (SOURCE_38, SHEET_38),
}

# Header ↔ qc_cells.json key map. 保留 28 期字段（diff_pattern / score_*）；
# 29 期表头没有这几列，fill_one 在缺列时**静默跳过**，不再警告。
HEADER_MAP_SHEET = {
    "任务质量（题目质量）": "prompt_quality",
    "题目质量说明": "prompt_quality_note",
    "题目是否可验": "verifiable",
    "题目是否可验证": "verifiable",
    "不可验证原因": "verifiable_reason",
    "分类是否正确": ("category_correct", "is_category_correct", "分类是否正确"),
    "0614C对比GLM 5.2 模型差异（轨迹/产物）pattern简述": "diff_pattern",
    "红线问题": ("redline_issue", "redline_problem", "red_flag_issue"),
    "题目红线问题": ("redline_issue", "redline_problem", "red_flag_issue"),
    "题目红线备注": ("redline_note", "redline_remark", "题目红线备注"),
    "一次质检平台审核理由（按模型）": ("platform_audit_reasons", "audit_reasons", "一次质检平台审核理由（按模型）"),
    "0614C完成质量实际打分": "score_0614C",
    "GLM5.2完成质量打分": "score_GLM5_2",
    "机器质检结果是否正确": ("machine_qc_correct", "machine_result_correct", "machine_correct"),
    "错误原因": ("machine_qc_reason", "machine_result_reason", "machine_error_reason"),
}
# 期数相关字段：期数换了这些列直接不存在于表头，push 时静默跳过。
_PERIOD_OPTIONAL_KEYS = {"diff_pattern", "score_0614C", "score_GLM5_2"}
_PERIOD_OPTIONAL_HEADERS = {
    "红线问题",
    "题目红线问题",
    "题目红线备注",
    "题目是否可验证",
    "是否正常题目",
    "机器质检结果是否正确",
    "错误原因",
    "0614C对比GLM 5.2 模型差异（轨迹/产物）pattern简述",
    "0614C完成质量实际打分",
    "GLM5.2完成质量打分",
}

PER_MODEL_SUFFIXES = {
    "反馈质量（作业质量）": "rating",
    # "验证截图": "screenshot",  # 截图列保留空白，截图文件在 delivery/<ID>/screenshots/ 自查
    "质量备注": "note",
    "脏数据标签": "dirty_tag",
    "脏数据标签理由": "dirty_tag_reason",
}

# 29 期表头示例：
#   '30B-0616E-OPD反馈质量（作业质量）', '30B-Merge-0618B-AA反馈质量（作业质量）', ...
# 28 期表头示例：
#   '0614C反馈质量（作业质量）', 'GLM 5.2反馈质量（作业质量）', ...
# 一律从表头动态抽模型名，不再硬编码 4 个或 5 个。
_MODEL_SUFFIX_KEY = "反馈质量（作业质量）"
# These cells are managed in the shared Feishu sheet by humans / dispatch.
# Keep them out of generated delivery files so upload scripts cannot overwrite
# manually assigned ownership fields.
READ_ONLY_HEADERS = {"是否结算", "质检人", "所属商", "所述商"}
HIGH_QUALITY_TASK_HEADER = "是否是高质量题目"
NORMAL_TASK_HEADER = "是否正常题目"
HIGH_QUALITY_PROMPT_VALUE = "高质量"
ABNORMAL_PROMPT_VALUES = {"红线", "不可用"}


def derive_high_quality_task(sheet: dict):
    """Return 是/否 for the sheet's high-quality-task flag.

    The 38期 sheet has a separate yes/no column next to task quality, but it is
    not a duplicate of 任务质量（题目质量）. It follows the overall model-feedback
    quality: all model feedback high-quality => 是; any 合格/不合格 => 否.
    """
    for key in ("is_high_quality_task", "high_quality_task", "是否是高质量题目"):
        value = sheet.get(key)
        if value is not None and str(value).strip():
            return value
    model_ratings = [
        str(m.get("rating") or "").strip()
        for m in (sheet.get("models") or {}).values()
        if str(m.get("rating") or "").strip()
    ]
    if model_ratings:
        return "是" if all(r == HIGH_QUALITY_PROMPT_VALUE for r in model_ratings) else "否"
    return None


def derive_normal_task(sheet: dict):
    """Return 是/否 for the sheet's normal-task flag.

    Allow an explicit qc_cells override. Without an override, only clear
    redline/unusable task evidence marks the task abnormal; other reviewed tasks
    default to normal.
    """
    for key in ("is_normal_task", "normal_task", "是否正常题目"):
        value = sheet.get(key)
        if value is not None and str(value).strip():
            return value
    prompt_quality = str(sheet.get("prompt_quality") or "").strip()
    redline_issue = str(sheet.get("redline_issue") or sheet.get("redline_problem") or sheet.get("red_flag_issue") or "").strip()
    if redline_issue or prompt_quality in ABNORMAL_PROMPT_VALUES:
        return "否"
    return "是"


def extract_model_names(headers: dict[str, int]) -> list[str]:
    """Scan headers, return the model names (unique, order preserved by column).

    A header like `<MODEL>反馈质量（作业质量）` yields `<MODEL>`. We use
    reverse-sort by column index only to reconstruct the natural left-to-right
    order of the sheet's model columns.
    """
    hits = [(col, h[:-len(_MODEL_SUFFIX_KEY)])
            for h, col in headers.items() if h.endswith(_MODEL_SUFFIX_KEY)]
    hits.sort(key=lambda t: t[0])
    return [name for _, name in hits]


def find_header_columns(ws, header_row: int) -> dict[str, int]:
    out = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if isinstance(v, str) and v.strip():
            out[v.strip()] = c
    return out


def locate_header_row(ws) -> int:
    """Detect the header row by looking for `任务ID`."""
    for r in (2, 1, 3):
        for c in range(1, ws.max_column + 1):
            if str(ws.cell(r, c).value or "").strip() == "任务ID":
                return r
    raise RuntimeError("could not locate header row containing '任务ID'")


def find_task_row(ws, task_id: str, id_col: int, start: int) -> int | None:
    for r in range(start, ws.max_row + 1):
        v = ws.cell(r, id_col).value
        if str(v).strip() == task_id:
            return r
    return None


def write_value(ws, row: int, col: int, value):
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    ws.cell(row, col).value = value


def refresh_machine_qc_validation(ws, headers: dict[str, int]) -> None:
    col = headers.get(MACHINE_QC_HEADER)
    if not col:
        return
    coord = f"{get_column_letter(col)}2"
    ws.data_validations.dataValidation = [
        dv for dv in ws.data_validations.dataValidation
        if coord not in dv.cells
    ]
    dv = DataValidation(
        type="list",
        formula1=f'"{",".join(MACHINE_QC_OPTIONS)}"',
        allow_blank=True,
    )
    dv.add(ws[coord])
    ws.add_data_validation(dv)


def read_sheet_value(sheet: dict, key_or_aliases):
    aliases = key_or_aliases if isinstance(key_or_aliases, tuple) else (key_or_aliases,)
    for key in aliases:
        if key in sheet:
            return sheet[key]
    return None


def has_sheet_key(sheet: dict, key_or_aliases) -> bool:
    aliases = key_or_aliases if isinstance(key_or_aliases, tuple) else (key_or_aliases,)
    return any(key in sheet for key in aliases)


def compose_platform_audit_reasons(sheet: dict, model_names: list[str]) -> str:
    from lib.g1 import sheet_model_label  # noqa: E402

    models = sheet.get("models", {})
    lines = []
    for model in model_names:
        data = models.get(model, {})
        reason = str(data.get("platform_audit_reason") or data.get("audit_reason") or "").strip()
        if reason:
            lines.append(f"{sheet_model_label(model)}：{reason}")
    return "\n".join(lines)


def copy_cell(src, dst) -> None:
    """Copy value + visible style attributes from src cell to dst cell."""
    dst.value = src.value
    if src.has_style:
        dst.font = copy(src.font)
        dst.fill = copy(src.fill)
        dst.alignment = copy(src.alignment)
        dst.border = copy(src.border)
        dst.number_format = src.number_format
        dst.protection = copy(src.protection)


def remap_sqref(orig_sqref: str, header_row: int, task_row: int, new_row: int) -> list[str]:
    """Convert a source data-validation sqref like 'G3:G358 ...' into a list of
    single-cell refs targeting `new_row` for the columns that originally
    covered the task row."""
    out = []
    for part in str(orig_sqref).split():
        # Each part is like "G3:G358" or "G3" — extract column letters.
        if ":" in part:
            a, b = part.split(":", 1)
            col_a = "".join(ch for ch in a if ch.isalpha())
            col_b = "".join(ch for ch in b if ch.isalpha())
            row_a = int("".join(ch for ch in a if ch.isdigit()))
            row_b = int("".join(ch for ch in b if ch.isdigit()))
            if col_a != col_b or not (row_a <= task_row <= row_b):
                continue
            out.append(f"{col_a}{new_row}")
        else:
            col = "".join(ch for ch in part if ch.isalpha())
            row = int("".join(ch for ch in part if ch.isdigit()))
            if row == task_row:
                out.append(f"{col}{new_row}")
    return out


def build_delivery_ws(src_ws, sheet_name: str, header_row: int, task_row: int, out_wb: Workbook):
    """Create a fresh sheet on out_wb mirroring just header + task row of src_ws.
    Returns the new worksheet plus headers map."""
    # Remove default sheet if it's the only one and untouched.
    out_ws = out_wb.create_sheet(sheet_name)

    n_cols = src_ws.max_column
    # Row 1 := source header row; Row 2 := source task row
    for c in range(1, n_cols + 1):
        copy_cell(src_ws.cell(header_row, c), out_ws.cell(1, c))
    if not str(out_ws.cell(1, 1).value or "").strip() and str(out_ws.cell(1, 2).value or "").strip() == "任务ID":
        # 38期源表有时把首列表头导出为空；该列实际是任务标题列。
        out_ws.cell(1, 1).value = "任务"
    for c in range(1, n_cols + 1):
        copy_cell(src_ws.cell(task_row, c), out_ws.cell(2, c))
        header = str(src_ws.cell(header_row, c).value or "").strip()
        if header in READ_ONLY_HEADERS:
            # Feishu owns these formula/calculated columns; local delivery must
            # not carry a stale source-row formula/value that could be uploaded.
            out_ws.cell(2, c).value = None

    # Column widths
    for col_letter, dim in src_ws.column_dimensions.items():
        if dim.width:
            out_ws.column_dimensions[col_letter].width = dim.width

    # Row heights for the two rows
    if src_ws.row_dimensions[header_row].height:
        out_ws.row_dimensions[1].height = src_ws.row_dimensions[header_row].height
    if src_ws.row_dimensions[task_row].height:
        out_ws.row_dimensions[2].height = src_ws.row_dimensions[task_row].height

    # Re-add data validations restricted to the task row (now row 2)
    for dv in src_ws.data_validations.dataValidation:
        targets = remap_sqref(dv.sqref, header_row, task_row, new_row=2)
        if not targets:
            continue
        new_dv = DataValidation(
            type=dv.type,
            formula1=dv.formula1,
            formula2=dv.formula2,
            allow_blank=dv.allowBlank,
            showErrorMessage=dv.showErrorMessage,
            errorTitle=dv.errorTitle,
            error=dv.error,
            showInputMessage=dv.showInputMessage,
            promptTitle=dv.promptTitle,
            prompt=dv.prompt,
            operator=dv.operator,
        )
        for ref in targets:
            new_dv.add(ref)
        out_ws.add_data_validation(new_dv)

    # Freeze the header row for usability
    out_ws.freeze_panes = "A2"
    return out_ws


def fill_one(ws, headers: dict[str, int], task_id: str, qc: dict, row: int) -> None:
    sheet = qc.get("sheet", {})
    for header, key_or_aliases in HEADER_MAP_SHEET.items():
        if header in READ_ONLY_HEADERS:
            continue
        col = headers.get(header)
        if not col:
            if key_or_aliases == "supplier":
                continue
            # 29 期表头没有 diff_pattern / score_*，不算错，静默跳过。
            if key_or_aliases in _PERIOD_OPTIONAL_KEYS or header in _PERIOD_OPTIONAL_HEADERS:
                continue
            print(f"     [warn] header missing: {header!r}")
            continue
        if has_sheet_key(sheet, key_or_aliases):
            write_value(ws, row, col, read_sheet_value(sheet, key_or_aliases))
    label_col = headers.get(LABEL_HEADER)
    if label_col:
        current_label = str(ws.cell(row, label_col).value or "").strip()
        if not current_label:
            task_col = headers.get("任务")
            task_title = str(ws.cell(row, task_col).value or "").strip() if task_col else ""
            write_value(
                ws,
                row,
                label_col,
                resolve_task_label(
                    existing_label=current_label,
                    sheet=sheet,
                    task_title=task_title,
                    task_id=task_id,
                ),
            )
    high_quality_col = headers.get(HIGH_QUALITY_TASK_HEADER)
    if high_quality_col:
        write_value(ws, row, high_quality_col, derive_high_quality_task(sheet))
    normal_task_col = headers.get(NORMAL_TASK_HEADER)
    if normal_task_col:
        write_value(ws, row, normal_task_col, derive_normal_task(sheet))
    redline_header = "题目红线问题" if headers.get("题目红线问题") else "红线问题"
    if headers.get(redline_header) and not has_sheet_key(sheet, HEADER_MAP_SHEET.get(redline_header, "redline_issue")):
        ratings = [sheet.get("prompt_quality"), *(m.get("rating") for m in sheet.get("models", {}).values())]
        if any("红线" in str(v or "") for v in ratings):
            print("     [warn] 存在不可用（红线）评级，但 qc_cells.sheet 未填写 redline_issue")
    models = sheet.get("models", {})
    model_names = extract_model_names(headers)
    audit_reasons_col = headers.get("一次质检平台审核理由（按模型）")
    if audit_reasons_col and not has_sheet_key(sheet, HEADER_MAP_SHEET["一次质检平台审核理由（按模型）"]):
        write_value(ws, row, audit_reasons_col, compose_platform_audit_reasons(sheet, model_names))
    for model in model_names:
        mdata = models.get(model, {})
        for suffix, mkey in PER_MODEL_SUFFIXES.items():
            header = f"{model}{suffix}"
            col = headers.get(header)
            if not col:
                print(f"     [warn] header missing: {header!r}")
                continue
            ws.cell(row, col).value = None
            if not mdata:
                continue
            if mkey in mdata or mkey == "dirty_tag":
                value = mdata.get(mkey)
                if mkey == "note":
                    value = compose_feedback_note(mdata)
                if mkey == "dirty_tag":
                    value = to_feishu_dirty_tag(value)
                write_value(ws, row, col, value)
        if not mdata:
            print(f"     [warn] qc_cells.sheet.models 里没有 {model!r}")


def push_one(task_id: str, source: Path, sheet_name: str, tasks_dir: Path) -> bool:
    cells_path = tasks_dir / task_id / "qc_cells.json"
    if not cells_path.exists():
        print(f"  [skip] {task_id}: {cells_path} not found")
        return False
    qc = json.loads(cells_path.read_text(encoding="utf-8-sig"))

    src_wb = openpyxl.load_workbook(source, data_only=False)
    if sheet_name not in src_wb.sheetnames:
        if len(src_wb.sheetnames) == 1:
            sheet_name = src_wb.sheetnames[0]
        elif sheet_name == SHEET_38:
            candidates = [s for s in src_wb.sheetnames if s.startswith("38期")]
            if candidates:
                sheet_name = candidates[0]
            else:
                print(f"  ERROR: sheet {sheet_name!r} not in source", file=sys.stderr)
                return False
        else:
            print(f"  ERROR: sheet {sheet_name!r} not in source {src_wb.sheetnames}", file=sys.stderr)
            return False
    src_ws = src_wb[sheet_name]
    header_row = locate_header_row(src_ws)
    src_headers = find_header_columns(src_ws, header_row)
    if "任务ID" not in src_headers:
        print(f"  ERROR: 任务ID column not found", file=sys.stderr)
        return False
    task_row = find_task_row(src_ws, task_id, src_headers["任务ID"], header_row + 1)
    if not task_row:
        print(f"  [skip] {task_id}: not in sheet")
        return False

    delivery_dir = REPO_ROOT / "delivery" / task_id
    delivery_dir.mkdir(parents=True, exist_ok=True)
    out_xlsx = delivery_dir / f"{task_id}.xlsx"

    # Build a blank workbook with just our two rows.
    out_wb = Workbook()
    # Drop the default sheet that Workbook() creates.
    out_wb.remove(out_wb.active)
    out_ws = build_delivery_ws(src_ws, sheet_name, header_row, task_row, out_wb)
    headers = find_header_columns(out_ws, 1)
    refresh_machine_qc_validation(out_ws, headers)
    fill_one(out_ws, headers, task_id, qc, 2)

    try:
        out_wb.save(out_xlsx)
    except PermissionError:
        print(f"  ERROR: 无法写入 {out_xlsx}；请先关闭已打开的交付 xlsx 后重跑", file=sys.stderr)
        return False
    print(f"  ==> {task_id}: rebuilt → {out_xlsx} (header_row={header_row} task_row={task_row}, no images)")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_ids", nargs="+")
    p.add_argument("--period", choices=sorted(PERIOD_PRESETS),
                   help="使用内置期数配置；41期使用源表「任务ID」作为本地目录名")
    p.add_argument("--source", default=None)
    p.add_argument("--sheet", default=None)
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    if args.period:
        preset_source, preset_sheet = PERIOD_PRESETS[args.period]
    else:
        preset_source, preset_sheet = DEFAULT_SOURCE, DEFAULT_SHEET

    source = Path(args.source) if args.source else preset_source
    sheet = args.sheet or preset_sheet
    if sheet not in {DEFAULT_SHEET, SHEET_G1, SHEET_38}:
        print(f"ERROR: 不支持的交付 sheet={sheet!r}", file=sys.stderr)
        return 2
    if not source.exists():
        print(f"ERROR: source xlsx not found: {source}", file=sys.stderr)
        return 2

    tasks_dir = Path(args.tasks_dir)
    ok = 0
    for tid in args.task_ids:
        if push_one(tid, source, sheet, tasks_dir):
            ok += 1
    print(f"==> {ok}/{len(args.task_ids)} task xlsx(s) written under delivery/<TASK_ID>/")
    return 0 if ok == len(args.task_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
