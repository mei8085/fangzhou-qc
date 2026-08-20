#!/usr/bin/env python3
"""为 7JE7ZS 这类 PyQt5 + 关系图任务渲染复测 HTML 并截图。

对每个模型：
 1. cd 到模型目录、动态 import 它的数据提供者 + 图表工厂
 2. 调真实数据通道生成关系图 HTML
 3. 用 Playwright 加载 HTML（file:// 协议、headless chrome）截图

输出（delivery/<TASK_ID>/screenshots/<COL>_NN_*.png）：
    01_tree       目录层级树形图（pyvis）
    02_bubble     大小气泡图（plotly）
    03_network    下载关联网络图（pyvis）

之后再跑 compose.py 拼合成图。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

CHARTS = ["tree", "bubble", "network"]
CHART_TAGS = {"tree": "01_tree", "bubble": "02_bubble", "network": "03_network"}


RENDER_SNIPPETS = {
    "0F3TQ": r'''
import os, sys
sys.path.insert(0, os.getcwd())
from core.universal_monitor import UniversalMonitor
from core.graph_data import GraphDataProvider
from core.graph_charts import CHART_MAP
KEY = {"tree": "tree", "bubble": "bubble", "network": "download_network"}
mon = UniversalMonitor()
prov = GraphDataProvider(monitor=mon)
out_path = sys.argv[1]
key = KEY[sys.argv[2]]
label, fn, method = CHART_MAP[key]
data = getattr(prov, method)()
html = fn(data)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"OK {key} bytes={len(html)} method={method}")
''',
    "SI9GM": r'''
import os, sys
sys.path.insert(0, os.getcwd())
from core.graph_builder import GraphDataProvider, GraphBuilder
from core import graph_viz
prov = GraphDataProvider()
files = prov.get_files()
gb = GraphBuilder(files)
out_path = sys.argv[1]
key = sys.argv[2]
if key == "tree":
    G = gb.build_directory_tree()
    html = graph_viz.build_tree_html(G)
elif key == "bubble":
    data = gb.build_bubble_data()
    html = graph_viz.build_bubble_html(data)
elif key == "network":
    G = gb.build_download_network()
    html = graph_viz.build_download_html(G)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"OK {key} bytes={len(html)}")
''',
    "5C94P": r'''
import os, sys
sys.path.insert(0, os.getcwd())
from core.universal_monitor import UniversalMonitor
from core.graph_engine import GraphEngine
from core import graph_renderers
mon = UniversalMonitor()
eng = GraphEngine()
eng.collect_data(max_files=2000)
out_path = sys.argv[1]
key = sys.argv[2]
if key == "tree":
    G = eng.build_tree_graph()
    html = graph_renderers.render_tree_graph(G)
elif key == "bubble":
    data = eng.build_bubble_data()
    div = graph_renderers.render_bubble_chart(data)
    html = "<!DOCTYPE html><html><head><meta charset='utf-8'></head><body style='margin:0;background:#1A1A2E;'>" + div + "</body></html>"
elif key == "network":
    G = eng.build_network_graph()
    html = graph_renderers.render_network_graph(G)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"OK {key} bytes={len(html)}")
''',
    "915V3": r'''
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.getcwd())
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from core.universal_monitor import UniversalMonitor
from ui.relation_graph_view import RelationGraphView
mon = UniversalMonitor()
view = RelationGraphView(mon)
files = mon.get_changes(limit=2000)
unique = {}
for f in files:
    fp = f.get("filepath", "")
    if fp and fp not in unique:
        unique[fp] = f
files = list(unique.values())
out_path = sys.argv[1]
key = sys.argv[2]
if key == "tree":
    html = view._render_tree(files)
elif key == "bubble":
    html = view._render_bubble(files)
elif key == "network":
    html = view._render_network(files)
with open(out_path, "w", encoding="utf-8") as f:
    f.write(html)
print(f"OK {key} bytes={len(html)}")
''',
}


PY_EXE_CANDIDATES = [
    r"C:\Users\fangzheng\AppData\Local\Programs\Python\Python312\python.exe",
    sys.executable,
]
PY_EXE = next((p for p in PY_EXE_CANDIDATES if Path(p).exists()), sys.executable)


def render_html_for(model_code: str, model_dir: Path, chart_key: str, out_html: Path) -> tuple[bool, str]:
    snippet = RENDER_SNIPPETS.get(model_code)
    if not snippet:
        return False, f"no snippet for {model_code}"
    tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    tmp.write(snippet)
    tmp.close()
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(model_dir)
        env["PYTHONIOENCODING"] = "utf-8"
        r = subprocess.run(
            [PY_EXE, tmp.name, str(out_html), chart_key],
            cwd=str(model_dir), capture_output=True, text=True, timeout=240,
            env=env, encoding="utf-8", errors="replace",
        )
        ok = r.returncode == 0 and out_html.exists() and out_html.stat().st_size > 0
        log = (r.stdout or "") + "\n" + (r.stderr or "")
        return ok, log[-3000:]
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def screenshot_html(html_paths: list, png_paths: list) -> None:
    assert len(html_paths) == len(png_paths)
    js = HERE / "_render_screenshot.cjs"
    js.write_text(
        r"""
const fs = require('fs');
const { chromium } = require('playwright');
(async () => {
  const items = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 760 } });
  const page = await ctx.newPage();
  for (const it of items) {
    try {
      const url = 'file:///' + it.html.replace(/\\/g, '/');
      await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    } catch (e) { console.log('goto warn', it.html, e.message); }
    await page.waitForTimeout(2500);
    try {
      await page.screenshot({ path: it.png, fullPage: false });
      console.log('shot', it.png);
    } catch (e) { console.log('shot fail', it.png, e.message); }
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(2); });
""",
        encoding="utf-8",
    )
    items = [{"html": str(h.resolve()), "png": str(p.resolve())} for h, p in zip(html_paths, png_paths)]
    skills_dir = HERE.parent
    payload_file = HERE / "_render_payload.json"
    payload_file.write_text(json.dumps(items), encoding="utf-8")
    r = subprocess.run(
        ["node", str(js), str(payload_file)],
        cwd=str(skills_dir), capture_output=True, text=True, timeout=600,
    )
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("task_id")
    args = p.parse_args()
    task_id = args.task_id
    map_path = REPO_ROOT / "tasks" / task_id / "model_map.json"
    with open(map_path, encoding="utf-8") as f:
        mm = json.load(f)
    delivery = REPO_ROOT / "delivery" / task_id / "screenshots"
    delivery.mkdir(parents=True, exist_ok=True)
    render_root = REPO_ROOT / "tasks" / task_id / "_render"
    render_root.mkdir(exist_ok=True)

    html_pairs = []
    failures = {}
    for col, info in mm["models"].items():
        code = info["code"]
        safe_col = col.replace(" ", "_")
        model_dir = REPO_ROOT / "tasks" / task_id / "extracted" / code
        for key in CHARTS:
            tag = CHART_TAGS[key]
            html_out = render_root / f"{safe_col}_{tag}.html"
            png_out = delivery / f"{safe_col}_{tag}.png"
            ok, log = render_html_for(code, model_dir, key, html_out)
            if not ok:
                failures.setdefault(col, []).append(f"{tag}: {log.strip()[:400]}")
                html_out.write_text(
                    f"<html><body style='background:#1A1A2E;color:#E74C3C;font:14px Microsoft YaHei;padding:40px;'>"
                    f"<h2>{col} {tag} 渲染失败</h2><pre style='color:#95A5A6;font-size:12px;white-space:pre-wrap'>{log[-2000:]}</pre>"
                    f"</body></html>",
                    encoding="utf-8",
                )
            html_pairs.append((html_out, png_out))

    print(f"=> rendered {len(html_pairs)} html files")
    screenshot_html([h for h, _ in html_pairs], [p for _, p in html_pairs])

    summary_path = render_root / "_summary.json"
    summary_path.write_text(json.dumps({"failures": failures}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=> summary {summary_path}")
    if failures:
        print("failures:")
        for k, v in failures.items():
            for ln in v:
                print(f"  {k}: {ln[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
