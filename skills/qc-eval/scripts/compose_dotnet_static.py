#!/usr/bin/env python3
"""For .NET MVC tasks where running docker + dotnet build locally is impractical,
render per-model verification PNGs from static source analysis:

    <COL>_01_overview.png  — counts: cshtml localized, css lines, media queries,
                              bottom-nav refs, drawer refs, CSS vars
    <COL>_02_evidence.png  — head of the _Layout.cshtml (navigation skeleton)
                              + key per-model finding (e.g. Razor escape bug)
    <COL>_verify.png       — side-by-side composite

Usage:
    compose_dotnet_static.py <TASK_ID>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageChops

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib.fonts import CJK_FONT_CANDIDATES as _CJK_FONT_CANDIDATES  # noqa: E402
from lib.fonts import FONT_CANDIDATES as _FONT_CANDIDATES  # noqa: E402
from lib.fonts import load_font  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent


def count_lines(p: Path) -> int:
    try:
        return sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
    except FileNotFoundError:
        return 0


def grep_count(p: Path, pattern: str) -> int:
    if not p.exists():
        return 0
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        return len(re.findall(pattern, txt))
    except Exception:
        return 0


def has_chinese(p: Path) -> bool:
    try:
        txt = p.read_text(encoding="utf-8", errors="ignore")
        return bool(re.search(r"[一-鿿]", txt))
    except Exception:
        return False


def collect_overview(web_root: Path) -> dict:
    css = web_root / "wwwroot" / "css" / "site.css"
    js = web_root / "wwwroot" / "js" / "site.js"
    layout = web_root / "Views" / "Shared" / "_Layout.cshtml"
    views = list((web_root / "Views").rglob("*.cshtml"))
    return {
        "css_lines": count_lines(css),
        "css_media": grep_count(css, r"@media"),
        "css_vars": grep_count(css, r"var\(--"),
        "css_transitions": grep_count(css, r"transition"),
        "css_gradients": grep_count(css, r"linear-gradient"),
        "css_44px": grep_count(css, r"44px"),
        "js_lines": count_lines(js),
        "js_chart_grad": grep_count(js, r"createLinearGradient"),
        "layout_lines": count_lines(layout),
        "layout_bottom_nav": grep_count(layout, r"bottomNav|bottom-nav"),
        "layout_drawer": grep_count(layout, r"sidebarToggle|sidebarOverlay|offcanvas"),
        "views_total": len(views),
        "views_localized": sum(1 for v in views if has_chinese(v)),
    }


def overview_text(col: str, code: str, ov: dict) -> str:
    return (
        f"F4GLXZ  ·  {col}  ({code})\n"
        f"AttributionPlatform.Web 静态核查\n"
        f"\n"
        f"视图文件 (cshtml) ............ 共 {ov['views_total']} / 已汉化 {ov['views_localized']}\n"
        f"site.css 总行数 ............... {ov['css_lines']}\n"
        f"  @media 断点 ................. {ov['css_media']}\n"
        f"  CSS 变量 var(--) 引用 ....... {ov['css_vars']}\n"
        f"  transition 过渡 .............. {ov['css_transitions']}\n"
        f"  linear-gradient 渐变 ........ {ov['css_gradients']}\n"
        f"  44px 触摸尺寸引用 ........... {ov['css_44px']}\n"
        f"site.js 总行数 ................. {ov['js_lines']}\n"
        f"  Chart.js 渐变填充 ........... {ov['js_chart_grad']}\n"
        f"_Layout.cshtml 行数 ........... {ov['layout_lines']}\n"
        f"  底部导航 (bottomNav) ........ {ov['layout_bottom_nav']}\n"
        f"  抽屉 / 折叠侧栏 .............. {ov['layout_drawer']}\n"
    )


def evidence_text(col: str, code: str, web_root: Path) -> str:
    findings = []
    # Razor escape bug detection
    for view in (web_root / "Views").rglob("*.cshtml"):
        try:
            txt = view.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "<style" not in txt:
            continue
        bad = re.findall(r"^\s*@(media|keyframes|font-face|supports|import|charset)\b",
                         txt, flags=re.MULTILINE)
        if bad:
            rel = view.relative_to(web_root)
            findings.append(f"Razor 未转义 @ 指令: {rel}  共 {len(bad)} 处 (需写为 @@)")

    layout = web_root / "Views" / "Shared" / "_Layout.cshtml"
    head = ""
    if layout.exists():
        lines = layout.read_text(encoding="utf-8", errors="ignore").splitlines()
        head = "\n".join(lines[:48])

    finding_text = "\n".join(findings) if findings else "未在视图中发现 Razor @ 指令转义遗漏"

    return (
        f"_Layout.cshtml 头部 (导航骨架)\n"
        f"{'-' * 60}\n"
        f"{head}\n"
        f"\n"
        f"{'-' * 60}\n"
        f"自动核查结论:\n"
        f"{finding_text}\n"
    )


def render_panel(text: str, font_mono, font_cjk, size) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    x, y = 16, 16
    max_w = size[0] - 2 * x
    line_h = font_mono.size + 6 if hasattr(font_mono, "size") else 14
    cw = font_mono.getlength("M") if hasattr(font_mono, "getlength") else 8
    cols = max(20, int(max_w / cw))
    for raw in text.splitlines():
        if not raw:
            y += line_h
            continue
        # Pick font per line based on whether it has CJK
        font = font_cjk if re.search(r"[一-鿿]", raw) else font_mono
        for i in range(0, len(raw), cols):
            d.text((x, y), raw[i : i + cols], fill="black", font=font)
            y += line_h
            if y + line_h > size[1]:
                return img
    return img


def trim_panel(img: Image.Image, pad: int = 24) -> Image.Image:
    bg = Image.new(img.mode, img.size, (255, 255, 255))
    diff = ImageChops.difference(img, bg)
    bbox = diff.getbbox()
    if not bbox:
        return img
    _, _, _, bottom = bbox
    new_h = min(img.height, bottom + pad)
    return img.crop((0, 0, img.width, new_h))


def compose_one(col: str, code: str, web_root: Path, out_dir: Path) -> dict:
    mono = load_font(_FONT_CANDIDATES, 14)
    cjk = load_font(_CJK_FONT_CANDIDATES, 14)
    panel_w, panel_h = 1000, 1500

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = col.replace(" ", "_")

    ov = collect_overview(web_root)
    ov_text = overview_text(col, code, ov)
    ev_text = evidence_text(col, code, web_root)

    p1 = out_dir / f"{tag}_01_overview.png"
    p2 = out_dir / f"{tag}_02_evidence.png"
    pv = out_dir / f"{tag}_verify.png"

    left = trim_panel(render_panel(ov_text, mono, cjk, (panel_w, panel_h)))
    left.save(p1)
    right = trim_panel(render_panel(ev_text, mono, cjk, (panel_w, panel_h)))
    right.save(p2)

    gap = 8
    total_w = left.width + right.width + gap * 3
    total_h = max(left.height, right.height) + gap * 2
    comp = Image.new("RGB", (total_w, total_h), "black")
    comp.paste(left, (gap, gap))
    comp.paste(right, (gap + left.width + gap, gap))
    comp.save(pv)

    return {"overview": p1, "evidence": p2, "verify": pv}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()

    task_dir = Path(args.tasks_dir) / args.task_id
    mm_path = task_dir / "model_map.json"
    if not mm_path.exists():
        print(f"ERROR: {mm_path} not found", file=sys.stderr)
        return 2
    mm = json.loads(mm_path.read_text(encoding="utf-8"))

    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    for col, info in mm["models"].items():
        code = info["code"]
        web_root = task_dir / "extracted" / code / "src" / "AttributionPlatform.Web"
        if not web_root.exists():
            print(f"!! {col} ({code}): missing {web_root}")
            continue
        print(f"==> {col} ({code})")
        outs = compose_one(col, code, web_root, out_dir)
        for k, v in outs.items():
            print(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
