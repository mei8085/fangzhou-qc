#!/usr/bin/env python3
"""For CLI / bug-fix tasks, render per-model verification PNGs from actual
CLI/runtime output whenever possible, with test/report output as supporting
evidence.

Outputs (under delivery/<TASK_ID>/screenshots/):
    <COL>_01_cli.png        — actual CLI command output, or existing CLI log
    <COL>_02_test.png       — terminal output of the project test command
    <COL>_03_report.png     — head of generated reports/*.md or *.txt
    <COL>_verify.png        — direct copy for one panel, otherwise side-by-side composite

The composite is the file referenced by xlsx 验证截图; the individual PNGs
preserve each evidence panel separately as the user requested. Composite images
do not add labels, captions, borders, or reviewer-authored explanation text.
When extra numbered screenshots already exist for the same model, they are
included in the verify composite.

Terminal panels render ASCII with ``MONO_FONT_CANDIDATES`` (Menlo / Consolas /
DejaVu Sans Mono) and use CJK fallback only for non-ASCII glyphs. This keeps
digits readable while preserving Chinese paths and logs.

If a quality note claims a mismatch the CLI panel does not show (test failure,
unrecorded product issue), do not rerun this script for the whole task: it
overwrites every model's `_01_cli.png`. Render an extra numbered PNG with
`render_extra_command_png`, then run `compose.py`.

If the annotator attached browser/page screenshots and the extracted artifact
contains a runnable frontend, this script first asks screenshot_vue.js to capture
the model's own page. The final verify composite then includes both live web UI
evidence and terminal/test evidence.

Usage:
    compose_cli.py <TASK_ID> [--report-file reports/rollout-risk.md]
    compose_cli.py <TASK_ID> --no-web-from-attachments
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.fonts import (  # noqa: E402
    CJK_FONT_CANDIDATES,
    FONT_CANDIDATES,
    MONO_FONT_CANDIDATES,
    load_font,
)
from PIL import Image, ImageDraw, ImageChops

REPO_ROOT = HERE.parent.parent.parent
MAX_TERMINAL_PANEL_WIDTH = int(os.environ.get("QC_TERMINAL_PANEL_MAX_WIDTH", "1280"))

# CLI evidence is ASCII-heavy. CJK proportional faces (PingFang etc.) make
# digits such as 4 lose the crossbar; use Menlo/Consolas for terminal panels.
_FONT_CANDIDATES = MONO_FONT_CANDIDATES
_LABEL_FONT_CANDIDATES = CJK_FONT_CANDIDATES


def _font_width(font, text: str) -> float:
    if hasattr(font, "getlength"):
        return font.getlength(text)
    return len(text) * 8


def _mixed_text_width(text: str, mono_font, cjk_font) -> float:
    total = 0.0
    for ch in text:
        total += _font_width(cjk_font if ord(ch) > 127 else mono_font, ch)
    return total


def _draw_mixed_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, mono_font, cjk_font) -> None:
    x, y = xy
    buf = ""
    active_font = None
    for ch in text:
        ch_font = cjk_font if ord(ch) > 127 else mono_font
        if active_font is None:
            active_font = ch_font
        if ch_font is not active_font:
            draw.text((x, y), buf, fill="black", font=active_font)
            x += _font_width(active_font, buf)
            buf = ch
            active_font = ch_font
        else:
            buf += ch
    if buf and active_font is not None:
        draw.text((x, y), buf, fill="black", font=active_font)


def _npm_cmd() -> list[str]:
    return ["npm.cmd" if os.name == "nt" else "npm"]


def detect_test_command(model_dir: Path) -> list[str]:
    if (model_dir / "go.mod").exists():
        return ["go", "test", "./..."]
    if (model_dir / "pyproject.toml").exists() or (model_dir / "pytest.ini").exists():
        return [sys.executable, "-m", "pytest", "-q"]
    pkg = model_dir / "package.json"
    if pkg.exists():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
            if "test:run" in scripts:
                return [*_npm_cmd(), "run", "test:run"]
        except Exception:
            pass
    return [*_npm_cmd(), "test"]


def detect_cli_command(model_dir: Path) -> list[str] | None:
    """Return a safe product CLI command when one can be inferred.

    Task-specific functional commands should be run manually and saved as
    tasks/<ID>/logs/<CODE>-cli-*.log; this fallback only captures a real
    executable entrypoint, not a synthetic code screenshot.
    """
    if (model_dir / "go.mod").exists() and (model_dir / "cmd" / "main.go").exists():
        return ["go", "run", "./cmd", "--help"]
    pkg = model_dir / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            bin_field = data.get("bin")
            if isinstance(bin_field, str):
                return ["node", bin_field, "--help"]
            if isinstance(bin_field, dict) and bin_field:
                return ["node", next(iter(bin_field.values())), "--help"]
        except Exception:
            pass
    return None


def clean_terminal_text(text: str) -> str:
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    text = text.replace("\r", "\n")
    text = text.replace("\ufeff", "")
    # Some terminal progress glyphs are missing in common fonts. Normalize them
    # so evidence remains readable instead of showing tofu boxes.
    text = text.translate(str.maketrans({
        "■": "=", "□": "-", "█": "=", "▇": "=",
        "✓": "OK", "✔": "OK", "√": "OK",
        "✗": "FAIL", "✖": "FAIL", "✕": "FAIL", "✘": "FAIL",
        "▶": ">", "ℹ": "-", "»": ">", "›": ">",
    }))
    text = text.expandtabs(8)
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)


def run_command(model_dir: Path, cmd: list[str], timeout: int = 120) -> str:
    prompt = f"$ {shlex.join(cmd)}"
    env = None
    if len(cmd) >= 3 and cmd[1:3] == ["-m", "pytest"]:
        env = os.environ.copy()
        # Keep unrelated globally installed pytest plugins from breaking task-local tests.
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    try:
        use_shell = os.name == "nt" and bool(cmd) and Path(cmd[0]).name.lower().startswith("npm")
        r = subprocess.run(
            cmd, cwd=model_dir, capture_output=True, text=True,
            shell=use_shell, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        return f"{prompt}\n{out}".strip()
    except Exception as e:
        return f"{prompt}\n{e}".strip()
    out = (r.stdout or "") + (r.stderr or "")
    return f"{prompt}\n{out}".strip()


def run_test(model_dir: Path) -> str:
    return run_command(model_dir, detect_test_command(model_dir))


def read_existing_cli_log(task_id: str, code: str, sheet_label: str) -> str | None:
    logs_dir = REPO_ROOT / "tasks" / task_id / "logs"
    if not logs_dir.exists():
        return None
    safe_label = sheet_label.replace(" ", "_")
    patterns = [
        f"{code}-cli-*.log",
        f"{code}_cli_*.log",
        f"{safe_label}-cli-*.log",
        f"{safe_label}_cli_*.log",
    ]
    hits: list[Path] = []
    for pat in patterns:
        hits.extend(Path(p) for p in glob.glob(str(logs_dir / pat)))
    hits = sorted({p for p in hits if p.is_file()})
    if not hits:
        return None
    return hits[0].read_text(encoding="utf-8", errors="replace").strip()


def run_cli_or_read_log(task_id: str, code: str, sheet_label: str, model_dir: Path) -> str | None:
    existing = read_existing_cli_log(task_id, code, sheet_label)
    if existing:
        return existing
    cmd = detect_cli_command(model_dir)
    if not cmd:
        return None
    return run_command(model_dir, cmd)


def read_report(model_dir: Path, report_rel: str, max_lines: int = 64) -> str:
    p = model_dir / report_rel
    if not p.exists():
        try:
            subprocess.run(
                [*_npm_cmd(), "run", "report"],
                cwd=model_dir, capture_output=True, shell=(os.name == "nt"), timeout=120,
            )
        except Exception:
            pass
    if not p.exists():
        return f"<{report_rel} not found>"
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["", f"... (truncated, total {len(lines)} lines)"]
    return "\n".join(lines)


def strip_extracted_paths(text: str, model_dir: Path) -> str:
    """Redact local absolute workspace paths from evidence screenshots."""
    repo = REPO_ROOT.resolve().as_posix()
    text = text.replace(repo, "<repo>")
    resolved = model_dir.resolve()
    posix = resolved.as_posix()
    win = str(resolved)
    for prefix in (f"file://{posix}/", f"file://{win}/", f"{posix}/", f"{win}{os.sep}"):
        text = text.replace(prefix, "")
    return text


def render_text_png(text: str, out_path: Path, *, font_size: int = 13, max_width: int = MAX_TERMINAL_PANEL_WIDTH) -> Image.Image:
    """Render terminal text with mono ASCII and CJK fallback for Chinese logs."""
    font = load_font(_FONT_CANDIDATES, font_size)
    fallback = load_font(_LABEL_FONT_CANDIDATES, font_size)
    cleaned = clean_terminal_text(text)
    longest = max((_mixed_text_width(ln, font, fallback) for ln in cleaned.splitlines() if ln), default=800)
    # Long pytest traces and Vite asset lists used to produce 3k+ px panels.
    # Cap the panel width and rely on pixel-aware wrapping so composites stay
    # readable beside web screenshots.
    panel_w = max(800, min(max_width, int(longest) + 40))
    line_h = font.size + 4 if hasattr(font, "size") else 14
    max_w = panel_w - 32
    n_lines = sum(max(1, len(wrap_to_width(ln, font, max_w, fallback))) for ln in cleaned.splitlines()) or 1
    panel_h = 16 + n_lines * line_h + 40
    img = trim_panel(render_panel(cleaned, font, (panel_w, panel_h), fallback))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return img


def render_extra_command_png(
    model_dir: Path,
    cmd: list[str],
    out_path: Path,
    *,
    timeout: int = 60,
    font_size: int = 13,
) -> str:
    """Render one extra numbered evidence PNG from a live command.

    Does not touch `_01_cli.png`. Use this when a quality note claims a
    mismatch (test failure, unrecorded issue) that the CLI panel does not show.
    """
    text = strip_extracted_paths(
        clean_terminal_text(run_command(model_dir, cmd, timeout=timeout)),
        model_dir,
    )
    render_text_png(text, out_path, font_size=font_size)
    return text


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as f:
            header = f.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return None
        return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
    except OSError:
        return None


def _image_size(path: Path) -> tuple[int, int] | None:
    if path.suffix.lower() == ".png":
        return _png_size(path)
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def _looks_like_web_attachment(path: Path) -> bool:
    """Heuristic gate for annotator browser screenshots.

    We intentionally keep this conservative: large landscape/desktop captures
    or tall app-page captures should trigger frontend evidence, while small
    icons/log snippets should not.
    """
    size = _image_size(path)
    if not size:
        return False
    w, h = size
    if w < 900 or h < 600:
        return False
    ratio = w / max(h, 1)
    return 0.55 <= ratio <= 3.2


def annotator_has_web_screenshots(task_id: str) -> bool:
    base = REPO_ROOT / "tasks" / task_id / "ark_g1"
    if not base.exists():
        return False
    for p in base.glob("*/evaluation_attachments/*"):
        if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and _looks_like_web_attachment(p):
            return True
    return False


def _has_frontend_entry(model_dir: Path) -> bool:
    cands = [
        model_dir / "package.json",
        model_dir / "frontend" / "package.json",
        model_dir / "frontend" / "web" / "package.json",
    ]
    return any(p.exists() for p in cands)


def any_model_has_frontend(task_id: str, mm: dict) -> bool:
    task_dir = REPO_ROOT / "tasks" / task_id
    return any(_has_frontend_entry(task_dir / "extracted" / info["code"]) for info in mm["models"].values())


def maybe_capture_web_from_attachments(task_id: str, mm: dict, *, enabled: bool) -> None:
    if not enabled:
        return
    if not annotator_has_web_screenshots(task_id):
        return
    if not any_model_has_frontend(task_id, mm):
        return
    log_dir = REPO_ROOT / "tasks" / task_id / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "_frontend_from_attachments.log"
    script = HERE / "screenshot_vue.js"
    cmd = ["node", str(script), task_id, "--if-annotator-web", "--keep-existing"]
    try:
        r = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
        log_path.write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
        if r.returncode != 0:
            print(f"   [web-screenshot] failed; see {log_path.relative_to(REPO_ROOT)}", file=sys.stderr)
        else:
            print(f"   [web-screenshot] captured from annotator web-page signal")
    except Exception as e:
        log_path.write_text(f"<failed to run {' '.join(cmd)}: {e}>", encoding="utf-8")
        print(f"   [web-screenshot] failed; see {log_path.relative_to(REPO_ROOT)}", file=sys.stderr)


def wrap_to_width(line: str, font, max_w: int, fallback_font=None) -> list[str]:
    """Break ``line`` so each piece actually fits in ``max_w`` pixels.

    Character-count wrapping using the width of ``M`` is too short for CJK
    proportional faces, so ASCII CLI output wraps early and leaves a blank
    right margin.
    """
    if not line:
        return [""]
    fallback = fallback_font or load_font(_LABEL_FONT_CANDIDATES, getattr(font, "size", 13))
    def measure(s: str) -> float:
        return _mixed_text_width(s, font, fallback)
    if measure(line) <= max_w:
        return [line]
    pieces: list[str] = []
    start = 0
    n = len(line)
    while start < n:
        lo, hi = 1, n - start
        fit = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if measure(line[start : start + mid]) <= max_w:
                fit = mid
                lo = mid + 1
            else:
                hi = mid - 1
        pieces.append(line[start : start + fit])
        start += fit
    return pieces


def render_panel(text: str, font, size, fallback_font=None) -> Image.Image:
    """Plain mono-text on white, no title, no border — just the evidence."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    x, y = 16, 16
    max_w = size[0] - 2 * x
    line_h = font.size + 4 if hasattr(font, "size") else 14
    fallback = fallback_font or load_font(_LABEL_FONT_CANDIDATES, getattr(font, "size", 13))
    for raw in clean_terminal_text(text).splitlines():
        if not raw:
            y += line_h
            continue
        for piece in wrap_to_width(raw, font, max_w, fallback):
            _draw_mixed_text(d, (x, y), piece, font, fallback)
            y += line_h
            if y + line_h > size[1]:
                return img
    return img


def trim_panel(img: Image.Image, pad: int = 24) -> Image.Image:
    """Crop the panel down to where the actual text ends, then pad a few px so
    the bottom isn't flush. `Image.getbbox` returns the bbox of non-zero pixels,
    which would include the white background — diff against a pure-white image
    first so we get the bbox of the rendered text only."""
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if not bbox:
        return img
    _, _, _, bottom = bbox
    new_h = min(img.height, bottom + pad)
    return img.crop((0, 0, img.width, new_h))


def compose_one(task_id: str, code: str, sheet_label: str, model_dir: Path, out_dir: Path, report_rel: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = sheet_label.replace(" ", "_")

    panels: list[tuple[str, str, Path]] = []
    cli_text = run_cli_or_read_log(task_id, code, sheet_label, model_dir)
    if cli_text:
        panels.append(("cli", cli_text, out_dir / f"{tag}_01_cli.png"))
    else:
        panels.append(("test", run_test(model_dir), out_dir / f"{tag}_01_test.png"))

    report_text = read_report(model_dir, report_rel)
    if not report_text.startswith("<") or "not found>" not in report_text:
        panels.append(("report", report_text, out_dir / f"{tag}_{len(panels)+1:02d}_report.png"))

    verify_png = out_dir / f"{tag}_verify.png"

    rendered: list[tuple[str, Path, Image.Image]] = []
    for name, text, path in panels:
        text = strip_extracted_paths(text, model_dir)
        img = render_text_png(text, path)
        rendered.append((name, path, img))

    numbered = sorted(
        p for p in out_dir.glob(f"{tag}_*.png")
        if re.match(rf"{re.escape(tag)}_\d+_.+\.png$", p.name)
    )

    if len(numbered) == 1:
        shutil.copyfile(numbered[0], verify_png)
    else:
        imgs = [(p, Image.open(p).convert("RGB")) for p in numbered]
        total_w = sum(img.width for _, img in imgs)
        total_h = max(img.height for _, img in imgs)
        composite = Image.new("RGB", (total_w, total_h), "black")
        x = 0
        for _, img in imgs:
            composite.paste(img, (x, 0))
            x += img.width
        composite.save(verify_png)

    return {name: path for name, path, _ in rendered} | {"verify": verify_png}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--report-file", default="reports/rollout-risk.md")
    p.add_argument(
        "--no-web-from-attachments",
        action="store_true",
        help="不要因标注人附件里有网页截图而额外运行前端截图",
    )
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    task_dir = tasks_dir / args.task_id
    map_path = task_dir / "model_map.json"
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(map_path.read_text(encoding="utf-8"))
    maybe_capture_web_from_attachments(args.task_id, mm, enabled=not args.no_web_from_attachments)

    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    for col, info in mm["models"].items():
        code = info["code"]
        model_dir = task_dir / "extracted" / code
        print(f"==> {col} ({code})")
        outs = compose_one(args.task_id, code, col, model_dir, out_dir, args.report_file)
        for k, v in outs.items():
            print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
