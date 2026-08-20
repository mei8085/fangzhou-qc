#!/usr/bin/env python3
"""Download and parse 29 期 trajectory HTMLs from the Feishu spreadsheet.

Each row of the `29期轨迹数据` sheet (sheet_id `SASoYv`) is a single HTML
attachment whose filename encodes the task ID (`task_html_29/<TASK_ID>.html`).
The HTML contains everything that 28 期 previously pulled from the 方舟众测
platform:

  * task info (title, prompt, source_type, requirement_type)
  * per-model code ↔ display name mapping (e.g. 5SIDV ↔ 30B-0616E-OPD)
  * per-model 方舟平台 URL, run id, status, event count
  * labeler feedback: score + comment + screenshot alt text
  * full execution trajectory text

Outputs (both under `tasks/<TASK_ID>/`):

  * `trajectory/<TASK_ID>.html`   raw file
  * `model_map.json`              **schema-compatible with 28 期**, so the
                                  existing `compose*.py`, `screenshot_*.js`
                                  can read it without any change
  * `trajectory_meta.json`        extracted structured summary for the QC
                                  agent to read (task info + labeler
                                  feedback per model)

Usage::

    fetch_trajectory.py <TASK_ID> [<TASK_ID> ...]
        [--wiki-url URL] [--sheet-id SASoYv] [--profile quan]
        [--tasks-dir tasks] [--force]

Preconditions:
  * `lark-cli` with the `quan` profile authorized against the target wiki
  * network to `open-apis` reachable
  * every call goes through `LARK_CLI_NO_PROXY=1` (bypasses local HTTP proxy)
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Reuse the wiki/lark plumbing from push_feishu (same profile, same wiki).
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from push_feishu import (  # noqa: E402
    lark, lark_exe, read_range, cell_to_text, resolve_spreadsheet_token,
)

REPO_ROOT = HERE.parent.parent.parent

DEFAULT_WIKI = "https://bytedance.larkoffice.com/wiki/OY1Dw0dcailCxTk3UGOcykVznAf"
DEFAULT_SHEET_ID = "SASoYv"
DEFAULT_PROFILE = "quan"
TRAJECTORY_ROW_COUNT = 260  # sheet has ~252 rows; scan a bit past to be safe


# ---------- Feishu sheet → task_id ↔ file_token index ----------

_ATTACHMENT_FILENAME = re.compile(r"([A-Z0-9]{6,12})\.html\s*$", re.IGNORECASE)


def build_task_index(spreadsheet_token: str, sheet_id: str, profile: str) -> dict[str, str]:
    """Return {TASK_ID: fileToken} by reading column A of the trajectory sheet.

    Each cell is a list like `[{"fileToken": "...", "text": "task_html_29/<ID>.html",
    "type": "attachment"}]` when read with `FormattedValue`.
    """
    rows = read_range(
        spreadsheet_token, sheet_id, f"A1:A{TRAJECTORY_ROW_COUNT}",
        profile, value_render="FormattedValue",
    )
    idx: dict[str, str] = {}
    for r in rows:
        if not r:
            continue
        cell = r[0]
        if not isinstance(cell, list):
            continue
        for att in cell:
            if not isinstance(att, dict) or att.get("type") != "attachment":
                continue
            text = att.get("text") or ""
            tok = att.get("fileToken")
            if not tok:
                continue
            m = _ATTACHMENT_FILENAME.search(text)
            if not m:
                continue
            idx[m.group(1).upper()] = tok
    return idx


# ---------- download one HTML ----------

def download_attachment(file_token: str, spreadsheet_token: str,
                        out_dir: Path, out_name: str, profile: str) -> Path:
    """Call the media-download OpenAPI and save the HTML into out_dir/out_name.

    The API refuses absolute output paths, so we cd into out_dir and pass a
    relative name. The endpoint responds with a save-path JSON on stdout when
    the response is binary; we relocate the saved file into our chosen name.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    extra = json.dumps({"bizType": "sheet", "fileToken": spreadsheet_token})
    env = os.environ.copy()
    env["LARK_CLI_NO_PROXY"] = "1"
    cmd = [
        *lark_exe(), "--profile", profile, "api", "GET",
        f"/open-apis/drive/v1/medias/{file_token}/download",
        "--params", json.dumps({"extra": extra}),
    ]
    r = subprocess.run(cmd, capture_output=True, env=env, cwd=str(out_dir))
    if r.returncode != 0:
        raise RuntimeError(
            f"medias download failed (rc={r.returncode}):\n"
            f"stderr: {r.stderr.decode('utf-8', errors='replace')[:400]}\n"
            f"stdout: {r.stdout.decode('utf-8', errors='replace')[:400]}"
        )
    # The endpoint reports the actual saved path in stdout as JSON.
    try:
        info = json.loads(r.stdout.decode("utf-8", errors="replace"))
        saved = Path(info["saved_path"])
    except Exception:
        # Fallback: assume it landed at the standard `task_html_29/<...>` layout.
        # Find the newest .html under out_dir and use that.
        candidates = sorted(out_dir.rglob("*.html"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise RuntimeError("medias download succeeded but no HTML file appeared")
        saved = candidates[-1]
    target = out_dir / out_name
    if saved.resolve() != target.resolve():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        saved.replace(target)
        # Clean up empty `task_html_29/` subdir the API may have created.
        try:
            saved.parent.rmdir()
        except OSError:
            pass
    return target


# ---------- HTML parsing ----------

# The generator embeds meta grids as `<div class="meta-grid"><div><strong>Key</strong>
# Value</div>...`. Model tabs are `<section id="<CODE>" class="model-section">`.

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(fragment: str) -> str:
    fragment = re.sub(r"<script[\s\S]*?</script>", "", fragment)
    fragment = re.sub(r"<style[\s\S]*?</style>", "", fragment)
    txt = _TAG.sub(" ", fragment)
    txt = html.unescape(txt)
    txt = _WS.sub(" ", txt).strip()
    return txt


def _extract_meta_grid(fragment: str) -> dict[str, str]:
    """Parse a `<div class="meta-grid">…</div>` block into {key: value}."""
    out: dict[str, str] = {}
    for cell in re.finditer(r"<div>\s*<strong>([^<]+)</strong>([\s\S]*?)</div>", fragment):
        key = html.unescape(cell.group(1)).strip().rstrip(":：")
        val = strip_html(cell.group(2))
        out[key] = val
    return out


def _extract_prompt(html_text: str) -> str:
    """The Prompt appears inside `<section class="card"><h2>题目信息</h2>...<pre>...</pre>`.
    Fall back to the meta-grid value if `<pre>` isn't found.
    """
    m = re.search(
        r"<h2[^>]*>\s*题目信息[\s\S]*?<pre[^>]*>([\s\S]*?)</pre>",
        html_text,
    )
    if m:
        return html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
    # Fallback: extract everything between the "Prompt" strong tag and the next
    # </div> in the meta-grid.
    m = re.search(
        r"<strong>\s*Prompt\s*</strong>([\s\S]*?)</div>",
        html_text,
    )
    if m:
        return strip_html(m.group(1))
    return ""


def parse_trajectory_html(html_text: str) -> dict:
    """Return a structured dict:
    {
      "task_info": {"task_id","title","source_type","requirement_type","prompt","source_note"},
      "models": [{"code","name","platform_url","run_id","status","events",
                  "labeler_score","labeler_comment","feedback_screenshot_notes",
                  "trajectory_excerpt"}],
      "view_user": "<int>",
    }
    """
    result: dict = {"task_info": {}, "models": [], "view_user": None}

    # 1. view_user + evaluation task
    m = re.search(r"用户：(\d+)", html_text)
    if m:
        result["view_user"] = m.group(1)

    # 2. Task info card
    ti_m = re.search(
        r'<section class="card">[\s\S]*?<h2[^>]*>\s*题目信息[\s\S]*?</section>',
        html_text,
    )
    if ti_m:
        meta = _extract_meta_grid(ti_m.group(0))
        result["task_info"] = {
            "task_id": meta.get("Task ID", "").strip(),
            "title": meta.get("标题", "").strip(),
            "source_type": meta.get("来源类型", "").strip(),
            "requirement_type": meta.get("需求类型", "").strip(),
            "source_note": meta.get("题目来源/背景说明", "").strip(),
            "prompt": _extract_prompt(html_text),
        }

    # 3. Iterate model sections
    for sect in re.finditer(
        r'<section id="([A-Z0-9]+)" class="model-section">([\s\S]*?)(?=<section id="|</main>)',
        html_text,
    ):
        code = sect.group(1)
        body = sect.group(2)

        # Section header contains "<CODE> / <NAME>"; use the plain-text version.
        header_m = re.search(r"<h2[^>]*>([\s\S]*?)</h2>", body)
        name = ""
        if header_m:
            plain = strip_html(header_m.group(1))
            if "/" in plain:
                name = plain.split("/", 1)[1].strip()

        meta = _extract_meta_grid(body)
        platform_url = meta.get("URL", "").strip()
        run_id = meta.get("Run ID", "").strip()
        status = meta.get("Status", "").strip()
        events = meta.get("Events", "").strip()

        # 评分反馈 → score + comment (标题 h3 或 h4 都见过)
        labeler_score = None
        labeler_comment = ""
        fb = re.search(
            r"<h[34][^>]*>\s*评分反馈[\s\S]*?<table[^>]*>([\s\S]*?)</table>",
            body,
        )
        if fb:
            row_m = re.search(
                r"<tr>\s*<td[^>]*>\s*完成质量\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>\s*<td[^>]*>([\s\S]*?)</td>",
                fb.group(1),
            )
            if row_m:
                try:
                    labeler_score = float(row_m.group(1))
                except ValueError:
                    labeler_score = None
                labeler_comment = strip_html(row_m.group(2))

        # 主动反馈 / 截图 — collect image captions and free-text
        fb_notes: list[str] = []
        af = re.search(
            r"<h[34][^>]*>\s*主动反馈\s*/\s*截图\s*</h[34]>([\s\S]*?)(?=<h[34]|<section id=|</section>)",
            body,
        )
        if af:
            block = af.group(1)
            for para in re.finditer(r"<p[^>]*>([\s\S]*?)</p>", block):
                t = strip_html(para.group(1))
                if t:
                    fb_notes.append(t)
            for cap in re.finditer(r"<figcaption[^>]*>([\s\S]*?)</figcaption>", block):
                t = strip_html(cap.group(1))
                if t:
                    fb_notes.append(t)

        # 执行轨迹 — keep just a short excerpt (first 4 KB of plain text) for
        # the meta file. The full trajectory stays in the raw HTML.
        traj_excerpt = ""
        tr = re.search(
            r"<h[34][^>]*>\s*执行轨迹\s*</h[34]>([\s\S]*?)(?=<section id=|</section>)",
            body,
        )
        if tr:
            traj_excerpt = strip_html(tr.group(1))[:4096]

        result["models"].append({
            "code": code,
            "name": name,
            "platform_url": platform_url,
            "run_id": run_id,
            "status": status,
            "events": events,
            "labeler_score": labeler_score,
            "labeler_comment": labeler_comment,
            "feedback_screenshot_notes": fb_notes,
            "trajectory_excerpt": traj_excerpt,
        })
    return result


# ---------- vite entry detection (py port of platform.js::detectViteEntry) ----------

def _is_vite_project(d: Path) -> bool:
    return d.is_dir() and any(
        (d / n).exists() for n in ("vite.config.js", "vite.config.ts", "vite.config.mjs")
    ) and (d / "package.json").exists()


def _router_looks_like_ordering(router_file: Path) -> bool | None:
    """Return True if the root router routes '/' to ordering; False if it routes
    to something obviously else (FormBuilder/dashboard etc.); None if unknown.
    Mirrors platform.js::routerLooksLikeOrdering as a minimum viable check.
    """
    try:
        txt = router_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    lo = txt.lower()
    hits_ordering = any(k in lo for k in ("ordering", "menu", "cart", "restaurant", "checkout"))
    hits_non_ordering = any(k in lo for k in ("formbuilder", "dashboard", "reportviewer", "admin"))
    if hits_ordering:
        return True
    if hits_non_ordering:
        return False
    return None


_ENTRY_SKIP_DIRS = {"node_modules", "src", "public", "dist", "reports", "build", ".git"}


def detect_vite_entry(model_root: Path) -> str:
    """Return an entry directory (relative to model_root, or '.') suitable for
    `npm run dev`. Falls back to '.' whenever detection is inconclusive.
    """
    if not model_root.is_dir():
        return "."
    if not _is_vite_project(model_root):
        candidates = []
        for pkg in model_root.rglob("package.json"):
            rel_parts = pkg.relative_to(model_root).parts
            if any(part in _ENTRY_SKIP_DIRS for part in rel_parts[:-1]):
                continue
            d = pkg.parent
            if _is_vite_project(d):
                candidates.append(d)
        if candidates:
            candidates.sort(key=lambda p: (len(p.relative_to(model_root).parts), str(p.relative_to(model_root)).lower()))
            return str(candidates[0].relative_to(model_root)).replace("\\", "/")
        return "."
    for cand in (
        model_root / "src" / "router.js",
        model_root / "src" / "router.ts",
        model_root / "src" / "router" / "index.js",
        model_root / "src" / "router" / "index.ts",
    ):
        if cand.exists():
            verdict = _router_looks_like_ordering(cand)
            if verdict is False:
                for sub in sorted(p for p in model_root.iterdir() if p.is_dir()):
                    if sub.name in _ENTRY_SKIP_DIRS:
                        continue
                    if _is_vite_project(sub):
                        return sub.name
            break
    return "."


# ---------- write model_map.json + trajectory_meta.json ----------

def build_model_map(task_id: str, parsed: dict, extracted_dir: Path) -> dict:
    """Assemble a model_map.json compatible with the 28 期 schema so
    downstream scripts (screenshot_vue.js, compose.py, ...) need no change.
    """
    models: dict[str, dict] = {}
    for m in parsed["models"]:
        code = m["code"]
        entry = "."
        if extracted_dir.exists():
            entry = detect_vite_entry(extracted_dir / code)
        models[m["name"]] = {
            "code": code,
            "display_name": m["name"],
            "platform_url": m["platform_url"],
            "comment_pngs": [],  # 29 期 trajectory 内嵌截图，不像 28 期在 extracted/comments/
            "entry": entry,
            "run_id": m["run_id"],
            "status": m["status"],
            "events": m["events"],
        }
    extracted_codes: list[str] = []
    if extracted_dir.exists():
        extracted_codes = sorted(
            p.name for p in extracted_dir.iterdir()
            if p.is_dir() and p.name not in ("comments", "logs", "source")
        )
    declared = {m["code"] for m in parsed["models"]}
    extra = [c for c in extracted_codes if c not in declared]
    missing = sorted(declared - set(extracted_codes))
    return {
        "task_id": task_id,
        "view_user": parsed.get("view_user"),
        "sheet_columns": [m["name"] for m in parsed["models"]],
        "models": models,
        "extracted_codes": extracted_codes,
        "extra_extracted_codes": extra,
        "missing_from_extracted": missing,
        "source": "29期轨迹数据 sheet (Feishu SASoYv HTML attachment)",
    }


def build_trajectory_meta(task_id: str, parsed: dict) -> dict:
    return {
        "task_id": task_id,
        "task_info": parsed["task_info"],
        "view_user": parsed.get("view_user"),
        "models": [
            {
                "code": m["code"],
                "name": m["name"],
                "platform_url": m["platform_url"],
                "run_id": m["run_id"],
                "status": m["status"],
                "events": m["events"],
                "labeler_score": m["labeler_score"],
                "labeler_comment": m["labeler_comment"],
                "feedback_screenshot_notes": m["feedback_screenshot_notes"],
                "trajectory_excerpt": m["trajectory_excerpt"],
            }
            for m in parsed["models"]
        ],
    }


# ---------- per-task main ----------

def process_one(task_id: str, task_index: dict[str, str], spreadsheet_token: str,
                tasks_dir: Path, profile: str, force: bool) -> bool:
    task_id = task_id.upper()
    print(f"\n==> {task_id}")
    file_token = task_index.get(task_id)
    if not file_token:
        print(f"  [err] 任务 {task_id} 不在 29期轨迹数据 sheet 里")
        return False
    task_dir = tasks_dir / task_id
    traj_dir = task_dir / "trajectory"
    html_path = traj_dir / f"{task_id}.html"
    if html_path.exists() and not force:
        print(f"  [keep] {html_path.relative_to(REPO_ROOT)} 已存在 (--force 覆盖)")
    else:
        print(f"  下载轨迹 HTML → {html_path.relative_to(REPO_ROOT)}")
        download_attachment(file_token, spreadsheet_token, traj_dir, f"{task_id}.html", profile)
    raw = html_path.read_text("utf-8", errors="replace")
    parsed = parse_trajectory_html(raw)
    if not parsed["models"]:
        print(f"  [warn] 解析到 0 个模型段，HTML 可能格式变了")
    else:
        print(f"  解析 {len(parsed['models'])} 个模型: "
              + ", ".join(f"{m['code']}={m['name']}" for m in parsed["models"]))
    mm = build_model_map(task_id, parsed, task_dir / "extracted")
    (task_dir / "model_map.json").write_text(
        json.dumps(mm, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  写入 model_map.json ({len(mm['models'])} 模型, entry={{"
          + ", ".join(f"{k}:{v['entry']}" for k, v in mm['models'].items()) + "})")
    meta = build_trajectory_meta(task_id, parsed)
    (task_dir / "trajectory_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    scores = [m["labeler_score"] for m in parsed["models"] if m["labeler_score"] is not None]
    if scores:
        print(f"  标注人打分（完成质量）: "
              + ", ".join(f"{m['name']}={m['labeler_score']}" for m in parsed["models"]))
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_ids", nargs="+", help="一个或多个任务 ID")
    p.add_argument("--wiki-url", default=DEFAULT_WIKI)
    p.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    p.add_argument("--profile", default=DEFAULT_PROFILE)
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--force", action="store_true",
                   help="即使 HTML 已存在也重新下载")
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)

    print(f"==> 解析 spreadsheet token via wiki: {args.wiki_url}")
    spreadsheet_token = resolve_spreadsheet_token(args.wiki_url, args.profile)
    print(f"    spreadsheet_token = {spreadsheet_token}")

    print(f"==> 扫 sheet {args.sheet_id} 建 task_id → fileToken 索引")
    task_index = build_task_index(spreadsheet_token, args.sheet_id, args.profile)
    print(f"    索引里 {len(task_index)} 条轨迹")

    n_ok = 0
    for tid in args.task_ids:
        if process_one(tid, task_index, spreadsheet_token, tasks_dir, args.profile, args.force):
            n_ok += 1

    print(f"\n完成 {n_ok}/{len(args.task_ids)} 个任务")
    return 0 if n_ok == len(args.task_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
