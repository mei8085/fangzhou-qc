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

Usage:
    compose_cli.py <TASK_ID> [--report-file reports/rollout-risk.md]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageChops

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
_LABEL_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def load_font(candidates, size):
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


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
                return ["npm", "run", "test:run"]
        except Exception:
            pass
    return ["npm", "test"]


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
        "✓": "OK", "✔": "OK", "√": "OK", "✗": "FAIL",
        "▶": ">", "ℹ": "i", "»": ">", "›": ">",
    }))
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)


def run_command(model_dir: Path, cmd: list[str], timeout: int = 120) -> str:
    env = None
    if len(cmd) >= 3 and cmd[1:3] == ["-m", "pytest"]:
        env = os.environ.copy()
        # Keep unrelated globally installed pytest plugins from breaking task-local tests.
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    try:
        r = subprocess.run(
            cmd, cwd=model_dir, capture_output=True, text=True, shell=False, timeout=120, env=env,
        )
    except Exception as e:
        return f"<failed to run {' '.join(cmd)}: {e}>"
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.splitlines() if not ln.startswith("> ")]
    body = "\n".join(lines).strip()
    return f"$ {' '.join(cmd)}\n{body}\nexit_code={r.returncode}".strip()


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
            subprocess.run(["npm", "run", "report"], cwd=model_dir, capture_output=True, shell=True, timeout=120)
        except Exception:
            pass
    if not p.exists():
        return f"<{report_rel} not found>"
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines] + ["", f"... (truncated, total {len(lines)} lines)"]
    return "\n".join(lines)


def render_panel(text: str, font, size) -> Image.Image:
    """Plain mono-text on white, no title, no border — just the evidence."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    x, y = 16, 16
    max_w = size[0] - 2 * x
    cw = font.getlength("M") if hasattr(font, "getlength") else 8
    cols = max(20, int(max_w / cw))
    line_h = font.size + 4 if hasattr(font, "size") else 14
    for raw in clean_terminal_text(text).splitlines():
        if not raw:
            y += line_h
            continue
        for i in range(0, len(raw), cols):
            d.text((x, y), raw[i : i + cols], fill="black", font=font)
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
    mono = load_font(_FONT_CANDIDATES, 13)
    panel_w, panel_h = 950, 1280

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
        img = trim_panel(render_panel(text, mono, (panel_w, panel_h)))
        img.save(path)
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
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    task_dir = tasks_dir / args.task_id
    map_path = task_dir / "model_map.json"
    if not map_path.exists():
        print(f"ERROR: {map_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(map_path.read_text(encoding="utf-8"))

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
