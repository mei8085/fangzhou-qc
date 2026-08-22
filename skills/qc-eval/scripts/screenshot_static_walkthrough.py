#!/usr/bin/env python3
"""Render static-review evidence screenshots for non-verifiable tasks.

The normal evidence path should show a running product. When qc_cells.json marks
the task as not verifiable, this script renders relevant code/log/trajectory
snippets instead. It supports an optional tasks/<TASK_ID>/static_evidence.json
for hand-picked files and line ranges; otherwise it chooses likely code files
from the model output and highlights lines related to the QC note.

Example static_evidence.json:
{
  "models": {
    "60B-0614C-OPD": [
      {"path": "main/max31856.cpp", "start": 15, "end": 70,
       "highlight": [[21, 45]]}
    ]
  }
}
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.fonts import FONT_CANDIDATES, load_font as _load_font  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent
TASKS_DIR = REPO_ROOT / "tasks"
DELIVERY_DIR = REPO_ROOT / "delivery"

TEXT_EXTS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".log",
    ".md",
    ".py",
    ".rs",
    ".ts",
    ".tsx",
    ".txt",
    ".vue",
    ".xml",
    ".yaml",
    ".yml",
}
IMPORTANT_NAMES = {"CMakeLists.txt", "Makefile", "Dockerfile"}
MAX_FILE_BYTES = 512 * 1024

BG = (13, 17, 23)
PANEL = (22, 27, 34)
TEXT = (230, 237, 243)
MUTED = (139, 148, 158)
LINENO = (125, 133, 144)
ACCENT = (248, 81, 73)


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(name).strip())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font(FONT_CANDIDATES, size)


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def is_text_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name in IMPORTANT_NAMES:
        return True
    if path.suffix.lower() not in TEXT_EXTS:
        return False
    try:
        return path.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def note_keywords(note: str) -> set[str]:
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", note))
    if "寄存器" in note or "读写" in note or "读" in note or "写" in note:
        words.update({"reg", "register", "read", "write", "0x80"})
    if "编译" in note or "构建" in note:
        words.update({"CMakeLists", "include", "error"})
    if "MAX31856" in note.upper():
        words.add("max31856")
    if "MAX31855" in note.upper():
        words.add("max31855")
    return {w.lower() for w in words}


def issue_keywords(note: str) -> set[str]:
    """Keywords used to place the viewport and red boxes.

    Keep this narrower than note_keywords(), which is also used for file
    selection. Otherwise common tokens such as MAX31856 would highlight nearly
    every line in embedded-driver files.
    """

    low = note.lower()
    out: set[str] = set()
    if any(s in note for s in ("寄存器", "读写", "读", "写")) or "register" in low:
        out.update({"0x80", "0x7f", "read_reg", "write_reg", "reg_read", "reg_write"})
    if any(s in note for s in ("编译", "构建")) or "build" in low or "compile" in low:
        out.update({"error", "include", "cmake", "missing"})
    return out


def score_file(path: Path, keywords: set[str]) -> int:
    rel = path.as_posix().lower()
    score = 0
    for kw in keywords:
        if kw and kw in rel:
            score += 8
    if path.name in IMPORTANT_NAMES:
        score += 2
    if path.suffix.lower() in {".c", ".cpp", ".h", ".hpp", ".py", ".js", ".ts", ".vue"}:
        score += 2
    if path.suffix.lower() in {".c", ".cpp", ".py", ".js", ".ts", ".vue", ".go", ".java", ".cs"}:
        score += 3
    try:
        head = read_text(path)[:12000].lower()
        for kw in keywords:
            if kw and kw in head:
                score += 1
    except Exception:
        pass
    return score


def line_hits(lines: list[str], keywords: set[str]) -> list[int]:
    strict = {"0x80", "0x7f", "0x00", "0xff"}
    strict_hits = [
        i for i, line in enumerate(lines, start=1)
        if any(kw in line.lower() for kw in strict if kw in keywords)
    ]
    if strict_hits:
        return strict_hits
    hits: list[int] = []
    for i, line in enumerate(lines, start=1):
        low = line.lower()
        if any(kw and kw in low for kw in keywords):
            hits.append(i)
    return hits


def choose_window(lines: list[str], keywords: set[str], radius: int = 24) -> tuple[int, int, list[tuple[int, int]]]:
    hits = line_hits(lines, keywords)
    if not hits:
        end = min(len(lines), 70)
        return 1, end, []
    center = hits[0]
    start = max(1, center - radius)
    end = min(len(lines), center + radius)

    # Keep nearby hits as separate red boxes. This highlights the concrete
    # lines without adding reviewer-authored explanation text to the image.
    spans: list[tuple[int, int]] = []
    for h in hits:
        if start <= h <= end:
            if spans and h <= spans[-1][1] + 1:
                spans[-1] = (spans[-1][0], h)
            else:
                spans.append((h, h))
    return start, end, spans[:4]


def resolve_evidence_path(task_id: str, model_code: str, item: dict[str, Any]) -> Path:
    raw = str(item.get("path") or item.get("file") or "").strip()
    if not raw:
        raise ValueError("evidence item missing path")
    p = Path(raw)
    if p.is_absolute():
        return p
    base = str(item.get("base") or "model").lower()
    if base == "source":
        return TASKS_DIR / task_id / "extracted" / "source" / p
    if base in {"task", "task_dir"}:
        return TASKS_DIR / task_id / p
    if base in {"delivery", "screenshots"}:
        return DELIVERY_DIR / task_id / "screenshots" / p
    return TASKS_DIR / task_id / "extracted" / model_code / p


def render_snippet(
    source: Path,
    out: Path,
    *,
    display_path: str,
    start: int,
    end: int,
    highlights: list[tuple[int, int]],
) -> None:
    raw_lines = read_text(source).splitlines() or [""]
    start = max(1, min(start, len(raw_lines)))
    end = max(start, min(end, len(raw_lines)))
    selected = raw_lines[start - 1 : end]

    code_font = font(18)
    title_font = font(16)
    line_h = 25
    pad_x = 26
    pad_y = 20
    gutter = 70
    title_h = 34
    max_chars = 118

    rendered: list[tuple[int, str, bool]] = []
    for idx, line in enumerate(selected, start=start):
        chunks = textwrap.wrap(
            line.expandtabs(4),
            width=max_chars,
            replace_whitespace=False,
            drop_whitespace=False,
        ) or [""]
        for j, chunk in enumerate(chunks[:5]):
            rendered.append((idx if j == 0 else 0, chunk, j == 0))

    width = 1320
    height = max(360, title_h + pad_y * 2 + line_h * len(rendered))
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, width, title_h), fill=PANEL)
    title = display_path
    if len(title) > 150:
        title = "..." + title[-147:]
    draw.text((pad_x, 8), title, font=title_font, fill=MUTED)

    y = title_h + pad_y
    line_y: dict[int, list[int]] = {}
    for lineno, text, first in rendered:
        if first and lineno:
            draw.text((pad_x, y), f"{lineno:>4}", font=code_font, fill=LINENO)
            line_y.setdefault(lineno, []).append(y)
        draw.text((pad_x + gutter, y), text, font=code_font, fill=TEXT)
        y += line_h

    for h_start, h_end in highlights:
        ys: list[int] = []
        for ln in range(h_start, h_end + 1):
            ys.extend(line_y.get(ln, []))
        if not ys:
            continue
        top = min(ys) - 4
        bottom = max(ys) + line_h + 2
        draw.rounded_rectangle(
            (pad_x + gutter - 8, top, width - pad_x, bottom),
            radius=8,
            outline=ACCENT,
            width=4,
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)


def configured_items(task_id: str, model: str, model_code: str) -> list[dict[str, Any]]:
    cfg_path = TASKS_DIR / task_id / "static_evidence.json"
    if not cfg_path.exists():
        return []
    cfg = load_json(cfg_path)
    models = cfg.get("models", {})
    raw_items = models.get(model) or models.get(model_code) or []
    return list(raw_items) if isinstance(raw_items, list) else []


def auto_items(task_id: str, model: str, model_code: str, qc: dict[str, Any]) -> list[dict[str, Any]]:
    root = TASKS_DIR / task_id / "extracted" / model_code
    if not root.exists():
        return []
    note = (((qc.get("sheet") or {}).get("models") or {}).get(model) or {}).get("note") or ""
    keywords = note_keywords(str(note))
    files = [p for p in root.rglob("*") if is_text_file(p)]
    if not files:
        return []
    line_keywords = issue_keywords(str(note)) or keywords
    if line_keywords:
        impl_files = [p for p in files if p.suffix.lower() in {".c", ".cc", ".cpp", ".py", ".js", ".ts", ".vue", ".go", ".java", ".cs"}]
        if impl_files:
            files = impl_files
    ranked = sorted(
        files,
        key=lambda p: (
            score_file(p, keywords),
            0 if p.suffix.lower() in {".h", ".hpp"} else 1,
            -len(p.parts),
            p.as_posix(),
        ),
        reverse=True,
    )
    chosen = [p for p in ranked if score_file(p, keywords) > 0][:1] or ranked[:1]
    items: list[dict[str, Any]] = []
    for p in chosen:
        rel = p.relative_to(root).as_posix()
        lines = read_text(p).splitlines() or [""]
        start, end, highlights = choose_window(lines, line_keywords)
        items.append({"path": rel, "start": start, "end": end, "highlight": highlights})
    return items


def render_model(task_id: str, model: str, info: dict[str, Any], qc: dict[str, Any]) -> int:
    code = str(info.get("code") or "")
    if not code:
        print(f"  [skip] {model}: missing code")
        return 0
    out_dir = DELIVERY_DIR / task_id / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = safe_tag(model)
    for old in out_dir.glob(f"{tag}_*.png"):
        old.unlink()

    items = configured_items(task_id, model, code) or auto_items(task_id, model, code, qc)
    if not items:
        print(f"  [fail] {model}: no static evidence candidate")
        return 1

    count = 0
    for item in items:
        try:
            src = resolve_evidence_path(task_id, code, item)
            if not src.exists():
                print(f"  [warn] {model}: missing {src}")
                continue
            lines = read_text(src).splitlines() or [""]
            start = int(item.get("start") or 1)
            end = int(item.get("end") or min(len(lines), start + 70))
            raw_h = item.get("highlight") or item.get("highlights") or []
            highlights = [(int(a), int(b)) for a, b in raw_h if isinstance(a, int) or str(a).isdigit()]
            if not highlights:
                _, _, highlights = choose_window(lines, note_keywords(str(item.get("keywords") or "")))
            count += 1
            out = out_dir / f"{tag}_{count:02d}_static_walkthrough.png"
            display_path = src.relative_to(TASKS_DIR / task_id).as_posix() if src.is_relative_to(TASKS_DIR / task_id) else src.as_posix()
            render_snippet(src, out, display_path=display_path, start=start, end=end, highlights=highlights)
            print(f"  {model}: {out.relative_to(REPO_ROOT)}")
        except Exception as exc:
            print(f"  [warn] {model}: failed to render item: {exc}")

    if count == 0:
        return 1
    return 0


def compose_verify(task_id: str) -> int:
    sys.stdout.flush()
    return __import__("subprocess").run(
        [sys.executable, "skills/qc-eval/scripts/compose.py", task_id, "--wrap-cols", "1"],
        cwd=REPO_ROOT,
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="+")
    parser.add_argument("--no-compose", action="store_true", help="只生成单张证据，不合成 verify 图")
    args = parser.parse_args()

    failed = False
    for raw in args.task_ids:
        task_id = raw.upper()
        print(f"==> {task_id}")
        task_dir = TASKS_DIR / task_id
        qc_path = task_dir / "qc_cells.json"
        map_path = task_dir / "model_map.json"
        if not qc_path.exists() or not map_path.exists():
            print(f"  [fail] missing qc_cells.json or model_map.json")
            failed = True
            continue
        qc = load_json(qc_path)
        model_map = load_json(map_path)
        for model in model_map.get("sheet_columns", list((model_map.get("models") or {}).keys())):
            info = (model_map.get("models") or {}).get(model) or {}
            if render_model(task_id, model, info, qc) != 0:
                failed = True
        if not args.no_compose and not failed:
            if compose_verify(task_id) != 0:
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
