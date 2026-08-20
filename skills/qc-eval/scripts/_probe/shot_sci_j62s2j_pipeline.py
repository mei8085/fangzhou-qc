#!/usr/bin/env python3
"""Run each model's Phase 1 pipeline on 3 sample queries, render output as PNG."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO = Path("D:/fz/fangzhou/fangzhou")
TASK = "J62S2J"
OUT = REPO / "delivery" / TASK / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

MAP = json.loads((REPO / "tasks" / TASK / "model_map.json").read_text(encoding="utf-8"))

QUERIES = [
    "基于图神经网络的多跳推理",
    "GNN 多跳推理",
    "diffusion model for text-to-image generation",
]

RUNNER = r"""
import sys, json, traceback
sys.path.insert(0, '.')
try:
    from sci_retrieval.pipeline import run_phase1_query_understanding
except Exception as e:
    print('IMPORT_ERROR:', repr(e))
    traceback.print_exc()
    sys.exit(1)

QUERIES = %s
for q in QUERIES:
    print('=' * 72)
    print('query:', q)
    try:
        r = run_phase1_query_understanding(q)
        cq = r['canonical_query']
        te = r['topic_expansion']
        rp = r['retrieval_plan']
        def g(o, k):
            if hasattr(o, k):
                return getattr(o, k)
            if isinstance(o, dict):
                return o.get(k)
            return None
        print(f"  detected_language: {g(cq, 'detected_language')}")
        print(f"  query_en:          {g(cq, 'query_en')}")
        print(f"  keywords:          {g(cq, 'keywords')}")
        print(f"  arxiv_query:       {g(cq, 'arxiv_query')}")
        topics = g(te, 'top_topics') or []
        print(f"  top_topics count:  {len(topics)}")
        kws = g(te, 'expanded_keywords') or []
        print(f"  expanded_keywords: {kws[:8]}")
        print(f"  plan.use_arxiv:    {g(rp, 'use_arxiv')}")
        print(f"  plan.use_openalex: {g(rp, 'use_openalex_topics')}")
    except Exception as e:
        print('ERROR:', repr(e))
        traceback.print_exc()
""" % (json.dumps(QUERIES, ensure_ascii=False),)


def render_text_png(title: str, text: str, out_path: Path) -> None:
    lines = text.splitlines()
    # simple monospace rendering
    try:
        font = ImageFont.truetype("consola.ttf", 16)
        font_title = ImageFont.truetype("consolab.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
        font_title = font
    line_h = 22
    pad = 20
    max_line_w = 0
    for ln in [title, ""] + lines:
        try:
            bbox = font.getbbox(ln)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(ln) * 10
        if w > max_line_w:
            max_line_w = w
    W = max(900, min(1600, max_line_w + pad * 2))
    H = pad * 2 + line_h * (len(lines) + 3)
    img = Image.new("RGB", (W, H), (16, 16, 16))
    d = ImageDraw.Draw(img)
    d.text((pad, pad), title, fill=(255, 210, 90), font=font_title)
    y = pad + line_h + 8
    for ln in lines:
        color = (220, 220, 220)
        low = ln.lower()
        if "error" in low or "traceback" in low or "import_error" in low:
            color = (255, 120, 120)
        elif "query_en" in ln or "keywords" in ln or "arxiv_query" in ln:
            color = (150, 230, 150)
        elif ln.startswith("query:"):
            color = (140, 200, 255)
        elif ln.startswith("="):
            color = (100, 100, 100)
        d.text((pad, y), ln, fill=color, font=font)
        y += line_h
    img.save(out_path)


def main() -> int:
    for col, info in MAP["models"].items():
        code = info["code"]
        cwd = REPO / "tasks" / TASK / "extracted" / code
        safe = col.replace("/", "_").replace(" ", "_")
        print(f"[{col}] running phase1 in {cwd}")
        proc = subprocess.run(
            [sys.executable, "-c", RUNNER],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        text = proc.stdout + ("\n---STDERR---\n" + proc.stderr if proc.stderr.strip() else "")
        out = OUT / f"{safe}_02_phase1.png"
        render_text_png(f"[{col}]  Phase 1 pipeline output  (cwd=extracted/{code})", text, out)
        print(f"  wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
