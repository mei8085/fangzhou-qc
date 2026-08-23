#!/usr/bin/env python3
"""End-to-end orchestrator for QC tasks assigned to a reviewer.

Usage
-----
    run.py <REVIEWER> [TASK_ID ...]
        [--source <repo>/data/众测质检38.xlsx] [--sheet 38期coding质检]
        [--prep-only | --emit-only] [--dry-run] [--list]

Two ways to choose tasks:

1. **No TASK_ID** — scan the source xlsx for rows where 质检人 == REVIEWER
   and 任务质量（题目质量）is empty; those are the pending tasks for that
   reviewer. Already-filled rows are listed but skipped.
2. **Explicit TASK_ID(s)** — only those tasks are processed, regardless of
   whether they're done. Useful for re-running or for cross-reviewer overrides.

Pipeline per task
-----------------
Stage A — "prep" (always safe, fully automatic):
    1. 38期不自动猜 Ark 平台任务 ID；先用 fetch_38_platform.js 按任务名或
       平台任务 ID 采集材料。
    2. run.py 可用于按质检人列出待做任务，以及在 qc_cells.json 写好后
       生成 delivery。

(human/AI checkpoint) — read source/feedback/extracted, write your QC
verdict to tasks/<ID>/qc_cells.json. Pipeline halts here if the file is
missing.

Stage B — "emit" (runs when qc_cells.json exists):
    6. compose_cli.py (CLI task) or screenshot_vue.js (Vue task)
    7. compose.py → screenshots/<COL>_verify.png
    8. blank/evidence/style guards
    9. push_xlsx.py → delivery/<ID>/<ID>.xlsx
    10. selfcheck.py 校验写作口径

Safety / scope
--------------
This orchestrator never writes to Feishu or the 方舟众测平台. Every API
call it makes is a GET; every output lands under tasks/<ID>/ or delivery/<ID>/.
Submitting the xlsx back to the 正式作业表 and filling in the 反馈质检 tab
on the platform are explicit human actions.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.paths import REPO_ROOT, default_source_xlsx  # noqa: E402

TASKS_DIR = REPO_ROOT / "tasks"

DEFAULT_SOURCE = default_source_xlsx()
DEFAULT_SHEET = "38期coding质检"
ALLOWED_SHEETS = {DEFAULT_SHEET}
PLATFORM_PERIODS = set()
PLATFORM_QC_PERIODS = set()
LOCAL_TASK_HTML_PERIODS = set()
TASK_HTML_SCREENSHOT_PERIODS = set()
DEFAULT_PORTAL_URL = ""


# ---------- period detection ----------

_PERIOD_RE = re.compile(r"^(\d+期)")


def sheet_to_period(sheet: str) -> str:
    """Return e.g. '29期' from '29期coding质检'; raise otherwise."""
    m = _PERIOD_RE.match(sheet.strip())
    if not m:
        raise RuntimeError(f"无法从 sheet 名推断期数: {sheet!r} (期望前缀形如 '29期')")
    return m.group(1)


# ---------- subprocess helpers ----------

def banner(s: str) -> None:
    print("\n" + "=" * 64 + f"\n  {s}\n" + "=" * 64, flush=True)


def run_cmd(cmd: list[str], *, cwd: Path = REPO_ROOT, dry: bool = False) -> int:
    print(f"  $ {' '.join(cmd)}", flush=True)
    if dry:
        return 0
    r = subprocess.run(cmd, cwd=cwd)
    return r.returncode


def run_node(rel: str, *args: str, dry: bool = False) -> int:
    return run_cmd(["node", f"skills/qc-eval/scripts/{rel}", *args], dry=dry)


def run_py(rel: str, *args: str, dry: bool = False) -> int:
    return run_cmd([sys.executable, f"skills/qc-eval/scripts/{rel}", *args], dry=dry)


def pushed_to_current_b_sheet(task_id: str) -> bool:
    """Only a successful uBlwx4 upload should block local regeneration."""
    sentinel = REPO_ROOT / "delivery" / task_id / ".pushed"
    if not sentinel.exists():
        return False
    try:
        text = sentinel.read_text(encoding="utf-8")
    except Exception:
        return False
    return "sheet_id=uBlwx4" in text


# ---------- xlsx parsing ----------

def locate_header_row(ws) -> int:
    for r in (2, 1, 3):
        for c in range(1, ws.max_column + 1):
            if str(ws.cell(r, c).value or "").strip() == "任务ID":
                return r
    raise RuntimeError("could not locate header row")


def find_header_columns(ws, header_row: int) -> dict[str, int]:
    out = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if isinstance(v, str) and v.strip():
            out[v.strip()] = c
    return out


def extract_portal_url(source: Path, sheet: str) -> Path:
    """Save tasks/_portal.json from the source xlsx.

    Legacy exports put the portal URL in A1. 38期 puts it in the long
    "产物链接\n<URL>" header, so scan the first few rows/cells.
    """
    wb = openpyxl.load_workbook(source, data_only=True)
    ws = wb[sheet]
    m = None
    for r in range(1, min(ws.max_row, 3) + 1):
        for c in range(1, ws.max_column + 1):
            text = str(ws.cell(r, c).value or "")
            m = re.search(r"https?://\S+", text)
            if m:
                break
        if m:
            break
    if m:
        portal_url = m.group(0)
    elif DEFAULT_PORTAL_URL:
        portal_url = DEFAULT_PORTAL_URL
        print("  [warn] source xlsx 未找到产物链接，使用内置对象存储链接")
    else:
        raise RuntimeError("portal URL not found in the first 3 rows of source xlsx")
    out = {"portal_url": portal_url, "sheet": sheet}
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    p = TASKS_DIR / "_portal.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def header_by_alias(headers: dict[str, int], aliases: list[str], prefixes: list[str] | None = None) -> int | None:
    for h in aliases:
        if h in headers:
            return headers[h]
    for prefix in prefixes or []:
        for h, c in headers.items():
            if h.startswith(prefix):
                return c
    return None


def scan_assignments(source: Path, sheet: str, reviewer: str) -> tuple[list[dict], list[dict]]:
    """Return (pending, done) lists for rows where 质检人 == reviewer."""
    wb = openpyxl.load_workbook(source, data_only=True)
    ws = wb[sheet]
    header_row = locate_header_row(ws)
    headers = find_header_columns(ws, header_row)
    # 38期表头第 3 列形如“产物链接\n<URL>”，但单元格值实际是任务标题；
    # 第 4 列无表头但单元格值是用户。其它期数仍优先按明确表头取值。
    title_col = header_by_alias(headers, ["任务", "任务title", "标题"], prefixes=["产物链接"])
    id_col = headers.get("任务ID")
    reviewer_col = headers.get("质检人")
    quality_col = headers.get("任务质量（题目质量）")
    user_col = header_by_alias(headers, ["用户", "提交用户", "任务用户"])
    if not user_col and title_col:
        user_col = title_col + 1
    required = {
        "任务ID": id_col,
        "任务标题": title_col,
        "质检人": reviewer_col,
        "任务质量（题目质量）": quality_col,
    }
    for h, col in required.items():
        if not col:
            raise RuntimeError(f"required header missing: {h!r}")
    pending: list[dict] = []
    done: list[dict] = []
    for r in range(header_row + 1, ws.max_row + 1):
        rev = str(ws.cell(r, reviewer_col).value or "").strip()
        if rev != reviewer:
            continue
        raw_task_id = str(ws.cell(r, id_col).value or "").strip()
        if not raw_task_id:
            print(f"  [warn] 行 {r} 缺少任务ID，跳过；38期必须用任务ID作为本地目录名")
            continue
        rec = {
            "task_id": raw_task_id,
            "title": str(ws.cell(r, title_col).value or "").strip(),
            "user": str(ws.cell(r, user_col).value or "").strip() if user_col else "",
            "row": r,
            "quality": ws.cell(r, quality_col).value,
        }
        if rec["quality"] and str(rec["quality"]).strip():
            done.append(rec)
        else:
            pending.append(rec)
    return pending, done


# ---------- task-type detection ----------

def task_kind(task_id: str) -> str:
    """Return 'cli' | 'vue' | 'unknown' based on extracted/source layout."""
    src = TASKS_DIR / task_id / "extracted" / "source"
    if not src.exists():
        # 38期 source may be a docx unpack, while model dirs contain runnable
        # frontend projects. Fall through to model_map based detection below.
        pass
    # A monorepo may have vite.config.ts at root without being a directly
    # runnable Vite app. screenshot_vue.js expects package.json + index.html.
    if src.exists() and ((src / "vite.config.js").exists() or (src / "vite.config.ts").exists()) and (src / "index.html").exists():
        return "vue"
    if src.exists() and (src / "go.mod").exists():
        return "cli"
    pkg = src / "package.json"
    if src.exists() and pkg.exists():
        try:
            j = json.loads(pkg.read_text(encoding="utf-8"))
            if "test" in j.get("scripts", {}):
                return "cli"
        except Exception:
            pass
    map_path = TASKS_DIR / task_id / "model_map.json"
    if map_path.exists():
        try:
            mm = json.loads(map_path.read_text(encoding="utf-8-sig"))
            for info in mm.get("models", {}).values():
                code = info.get("code")
                entry = info.get("entry") or "."
                if code and (TASKS_DIR / task_id / "extracted" / code / entry / "package.json").exists():
                    return "vue"
        except Exception:
            pass
    return "unknown"


# ---------- per-task stages ----------

def prep_one(task_id: str, dry: bool, *, period: str) -> bool:
    banner(f"prep  {task_id}  ({period})")
    if period == "38期":
        print(
            "  38期 Ark 平台任务 ID 需要按任务名或平台任务 ID 明确采集；"
            "请先运行 fetch_38_platform.js collect --task-title/--task-id --sheet-task-id <任务ID>，"
            "并把质检结论写到 tasks/<ID>/qc_cells.json。"
        )
        return True
    if period in LOCAL_TASK_HTML_PERIODS:
        # Local-attachment periods: fetch artifacts from object storage and local bundles.
        print("  [err] local attachment prep is disabled in the 38期 workflow")
        return False
    elif period in PLATFORM_PERIODS:
        # 33/34 期：模型产物和原始项目都从方舟平台下载 zip；轨迹与
        # 标注人反馈也走平台。下载 zip 先跑，后续 platform.js map 才能探测 entry。
        rcode = run_node("fetch_platform_artifacts.js", task_id, "--keep-existing", dry=dry)
        if rcode != 0:
            return False
        rcode = run_py("extract_platform_artifacts.py", task_id, dry=dry)
        if rcode != 0:
            return False
        rcode = run_node("platform.js", "map", "--task", task_id, dry=dry)
        if rcode != 0:
            return False
        rcode = run_node("fetch_platform_context.js", task_id, dry=dry)
        if rcode != 0:
            return False
        rcode = run_node("fetch_feedback.js", task_id, dry=dry)
        if rcode != 0:
            return False
    else:
        portal = TASKS_DIR / "_portal.json"
        rcode = run_node("fetch_portal.js",
                         "--portal", str(portal),
                         "--out", "tasks",
                         "--keep-existing",
                         task_id, dry=dry)
        if rcode != 0:
            print(f"  [err] fetch_portal failed for {task_id}")
            return False
        rcode = run_py("extract_portal.py", task_id, dry=dry)
        if rcode != 0:
            return False

    if period == "29期":
        # 29 期起：轨迹与标注人反馈都在飞书 29期轨迹数据 sheet 的 HTML 附件里，
        # 不再走方舟平台。model_map.json 由 fetch_trajectory.py 生成，
        # schema 与 28 期一致，下游 compose*.py / screenshot_*.js 无需改动。
        rcode = run_py("fetch_trajectory.py", task_id, dry=dry)
        if rcode != 0:
            return False
    elif period == "26期":
        # 26 期没有轨迹数据、也没有方舟平台数据；代号↔模型名走固定映射，
        # model_map.json 只有 code / display_name / entry / 空 platform_url，
        # 下游 compose*.py / screenshot_*.js schema 兼容零改动。
        rcode = run_py("fetch_no_trajectory.py", task_id, dry=dry)
        if rcode != 0:
            return False
    elif period not in PLATFORM_PERIODS and period not in LOCAL_TASK_HTML_PERIODS:
        rcode = run_node("platform.js", "map", "--task", task_id, dry=dry)
        if rcode != 0:
            return False
        rcode = run_node("fetch_feedback.js", task_id, dry=dry)
        if rcode != 0:
            return False
    print(f"  prep OK — 现在请把质检结论写到 tasks/{task_id}/qc_cells.json")
    return True


def emit_one(task_id: str, dry: bool, *, period: str, sheet: str, source: Path) -> bool:
    banner(f"emit  {task_id}  ({period})")
    cells = TASKS_DIR / task_id / "qc_cells.json"
    if not cells.exists():
        print(f"  [skip] tasks/{task_id}/qc_cells.json 还没写，跳过 emit")
        return False
    # 已推过飞书的定稿不允许覆盖：靠 delivery/<TASK_ID>/.pushed 兜底
    if pushed_to_current_b_sheet(task_id):
        print(
            f"  [stop] delivery/{task_id}/.pushed 存在（已推过飞书）；"
            f"如需重推，先手动删除该文件"
        )
        return False
    kind = task_kind(task_id)
    try:
        _qc = json.loads(cells.read_text(encoding="utf-8-sig"))
        _verifiable = _qc.get("sheet", {}).get("verifiable", "")
    except Exception:
        _verifiable = ""
    if period in TASK_HTML_SCREENSHOT_PERIODS and kind == "unknown":
        if _verifiable == "否":
            # Do not use an attachment summary page as the only evidence for non-verifiable tasks.
            # 交付截图应展示本地解压产物中的代码、日志或轨迹走读证据。
            if run_py("screenshot_static_walkthrough.py", task_id, dry=dry) != 0:
                return False
        else:
            print("  [err] attachment-page screenshot fallback is disabled in the 38期 workflow")
            return False
        if run_py("blank_guard.py", task_id, dry=dry) != 0:
            return False
        if run_py("evidence_guard.py", task_id, dry=dry) != 0:
            return False
        if run_py("screenshot_style_guard.py", task_id, dry=dry) != 0:
            return False
        if run_py("push_xlsx.py", task_id, "--source", str(source), "--sheet", sheet, dry=dry) != 0:
            return False
        rc = run_py("selfcheck.py", task_id, dry=dry)
        if rc != 0:
            print(f"  emit 完成但 selfcheck 命中：请改 qc_cells.json 后重跑 emit")
            return False
        shot_note = "static evidence screenshots" if _verifiable == "?" else "attachment fallback screenshots"
        print(f"  emit OK — 38期交付物在 delivery/{task_id}/（xlsx + {shot_note}；不生成 platform_qc.md）")
        return True
    # verifiable=是 且 verify_routes.json 就位：按 SKILL.md「复测启动与截图」走 u03l 全栈验证
    if _verifiable == "是" and (TASKS_DIR / task_id / "verify_routes.json").exists():
        banner(f"verify  {task_id}")
        rc = run_py("verify_fullstack.py", task_id, dry=dry)
        if rc == 2:
            print(f"  [stop] u03l 不可达；开机后重跑 emit。")
            return False
        if rc == 4:
            print(f"  [stop] verify 前置条件缺失（见提示）；补齐后重跑 emit。")
            return False
        if rc != 0:
            print(
                f"  [warn] verify 局部失败；见 tasks/{task_id}/logs/，"
                f"继续 emit（部分模型可能缺 verify 截图）"
            )
    elif _verifiable == "是":
        print(
            f"  [info] verifiable=是 但缺 verify_routes.json；"
            f"跳过全栈验证，仍走原有截图路径"
        )
    print(f"  题型识别：{kind}")
    if kind == "cli":
        if run_py("compose_cli.py", task_id, dry=dry) != 0:
            return False
    elif kind == "vue":
        rc = run_node("screenshot_vue.js", task_id, dry=dry)
        if rc != 0:
            print(f"  [warn] 自动截图失败，切到手动指引模式")
            run_node("screenshot_vue.js", task_id, "--print-steps", dry=dry)
            return False
        if run_py("compose.py", task_id, dry=dry) != 0:
            return False
    elif _verifiable == "否":
        if run_py("screenshot_static_walkthrough.py", task_id, dry=dry) != 0:
            return False
    else:
        tail = " + make_platform_qc" if period in PLATFORM_QC_PERIODS else ""
        print(f"  [warn] 题型识别不出来；请手动跑截图后再来跑 push_xlsx{tail}")
        return False
    # 空白截图卡点：跑不通的场景必须换成报错终端 / console / 出错源码，
    # 不能把白屏当证据。见 SKILL.md「复测启动与截图」。
    if run_py("blank_guard.py", task_id, dry=dry) != 0:
        print(
            f"  emit 中止：某张截图接近纯色。请补一张报错终端或出错源码文件的截图，"
            f"删掉空白帧后重跑 compose.py + emit。"
        )
        return False
    if run_py("evidence_guard.py", task_id, dry=dry) != 0:
        print(
            f"  emit 中止：verifiable=是 时不能只交代码/静态走读截图。"
            f"请补实际页面、CLI、API、构建/运行报错证据；"
            f"若环境确实不可复现，改 verifiable=否 并写清不可验证原因。"
        )
        return False
    if run_py("screenshot_style_guard.py", task_id, dry=dry) != 0:
        print(
            f"  emit 中止：验证截图含合成背景、边框或单图未直接复用原图。"
            f"请重跑 compose.py/compose_cli.py，不要加黑底、header、label 或 padding。"
        )
        return False
    if run_py("push_xlsx.py", task_id, "--source", str(source), "--sheet", sheet, dry=dry) != 0:
        return False
    if period in PLATFORM_QC_PERIODS:
        # 28/33/34 期需要平台录入清单；26/29 期没有平台反馈质检 tab。
        if run_py("make_platform_qc.py", task_id, dry=dry) != 0:
            return False
    # 写作约束自检；命中即视为不合格，emit 算失败但文件已生成，便于改写后重跑
    rc = run_py("selfcheck.py", task_id, dry=dry)
    if rc != 0:
        print(f"  emit 完成但 selfcheck 命中：请改 qc_cells.json 后重跑 emit")
        return False
    print(f"  emit OK — 交付物在 delivery/{task_id}/")
    return True


# ---------- main ----------

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reviewer", help="质检人姓名，例如 邓全")
    p.add_argument("task_ids", nargs="*", help="可选：手动指定任务 ID；不传则按 reviewer 自动筛未做")
    p.add_argument("--source", default=str(DEFAULT_SOURCE))
    p.add_argument("--sheet", default=DEFAULT_SHEET)
    p.add_argument("--prep-only", action="store_true", help="只做下载/解压/映射/反馈，不出交付物")
    p.add_argument("--emit-only", action="store_true", help="跳过下载与映射，仅生成交付物")
    p.add_argument("--dry-run", action="store_true", help="打印将执行的命令，不实际跑")
    p.add_argument("--list", action="store_true", help="只列待处理任务，不执行")
    args = p.parse_args()

    if args.prep_only and args.emit_only:
        print("错误：--prep-only 与 --emit-only 互斥", file=sys.stderr)
        return 2
    if args.sheet not in ALLOWED_SHEETS:
        print(f"错误：本工程只允许 38期 sheet={DEFAULT_SHEET!r}，拒绝 sheet={args.sheet!r}", file=sys.stderr)
        return 2

    source = Path(args.source)
    if not source.exists():
        print(f"错误：源 xlsx 不存在：{source}", file=sys.stderr)
        return 2

    try:
        period = sheet_to_period(args.sheet)
    except RuntimeError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 2

    banner(f"reviewer = {args.reviewer}   source = {source.name}   sheet = {args.sheet}   period = {period}")

    # 1. 选任务
    if args.task_ids:
        targets = list(args.task_ids)
        print(f"手动指定 {len(targets)} 个任务：{targets}")
    else:
        pending, done = scan_assignments(source, args.sheet, args.reviewer)
        print(f"{args.reviewer} 名下：{len(pending)} 个待做、{len(done)} 个已做")
        for r in done:
            print(f"  [已做] {r['task_id']} ({r['user']}) — 任务质量：{r['quality']}")
        for r in pending:
            tid = r["task_id"]
            local_bits = []
            if (TASKS_DIR / tid / "extracted").exists():
                local_bits.append("已下载")
            if (TASKS_DIR / tid / "qc_cells.json").exists():
                local_bits.append("有 qc_cells")
            if (REPO_ROOT / "delivery" / tid / f"{tid}.xlsx").exists():
                local_bits.append("有 delivery")
            local = "本地：" + "，".join(local_bits) if local_bits else "本地：空"
            print(f"  [待做] {tid} ({r['user']}) — {r['title']}  (行 {r['row']}；{local})")
        targets = [r["task_id"] for r in pending]
        if not targets:
            print("\n无待做任务，退出。")
            return 0

    if args.list:
        return 0

    # 2. 一次性把附件分享页 URL 提出来
    if not args.emit_only and period not in PLATFORM_PERIODS:
        portal_path = extract_portal_url(source, args.sheet)
        print(f"  附件分享页 URL 已写入 {portal_path.relative_to(REPO_ROOT)}")

    # 3. 逐任务跑 prep 与 emit
    summary = []
    for tid in targets:
        prep_ok = True
        if not args.emit_only:
            prep_ok = prep_one(tid, dry=args.dry_run, period=period)
        emit_ok = True
        if prep_ok and not args.prep_only:
            emit_ok = emit_one(tid, dry=args.dry_run, period=period, sheet=args.sheet, source=source)
        summary.append((tid, prep_ok, emit_ok))

    # 4. 汇总
    banner("汇总")
    for tid, p_ok, e_ok in summary:
        s_prep = "skip" if args.emit_only else ("ok" if p_ok else "FAIL")
        s_emit = "skip" if args.prep_only else ("ok" if e_ok else ("FAIL/待写 qc_cells.json"))
        print(f"  {tid}   prep={s_prep}   emit={s_emit}")

    print()
    if period in LOCAL_TASK_HTML_PERIODS:
        # Platform periods can request artifact packaging, but the current workflow does not use this branch.
        print(f"本流程只在本地生成 tasks/<ID>/ 与 delivery/<ID>/；不会写飞书。{period} 会向方舟平台请求产物打包/下载，但不修改任务或反馈。")
    else:
        print("本流程只在本地生成 tasks/<ID>/ 与 delivery/<ID>/，不会写飞书、不会写方舟众测平台。")
    print("交付物：")
    for tid, _, e_ok in summary:
        if e_ok and not args.prep_only:
            if period in TASK_HTML_SCREENSHOT_PERIODS:
                print(f"  delivery/{tid}/{tid}.xlsx + screenshots/")
            else:
                tail = " + platform_qc.md" if period in PLATFORM_QC_PERIODS else ""
                print(f"  delivery/{tid}/{tid}.xlsx + screenshots/{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

