"""HarmonyOS / ArkTS 等无 dev server 题型的复测截图工具。

无法本地起 dev server 时（HarmonyOS ArkTS、纯后端服务、CLI 只输出报告等），
用 Playwright 渲染一张静态卡片当作 verify 证据：模型代号、新增文件、接线状态、
静态检查发现、综合判定。

用法：
  python3 skills/qc-eval/scripts/screenshot_arkts.py <TASK_ID>

前置：`tasks/<TASK_ID>/review_findings.json` 由 agent 手写，schema：
  {
    "task_id": "DRWVGW",
    "title": "康复疗程自适应调度",
    "models": {
      "<COL>": {
        "rating": "低（差）",
        "files_added": ["utils/RehabAdapt.ets", ...],
        "wiring": [["Index.ets 是否接入", "是（+330 行）"], ...],
        "static_hits": [["utils/RehabAdapt.ets 第 127 行", "Partial<AdaptConfig> ..."], ...],
        "verdict": "综合判定文本"
      }
    }
  }

输出：`delivery/<TASK_ID>/screenshots/<COL>_01_review.png`
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
SKILL_DIR = HERE.parent

HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
          background: #0f172a; color: #e2e8f0; padding: 28px; width: 1180px; }}
  h1 {{ margin: 0 0 4px; font-size: 24px; color: #f8fafc; }}
  h2 {{ margin: 24px 0 10px; font-size: 16px; color: #38bdf8; border-left: 3px solid #38bdf8; padding-left: 10px; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }}
  .b-code {{ background: #1e293b; color: #cbd5e1; }}
  .b-rating {{ background: #7f1d1d; color: #fecaca; margin-left: 8px; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin-bottom: 14px; }}
  ul {{ margin: 6px 0 0; padding-left: 20px; line-height: 1.7; font-size: 14px; }}
  li code {{ background: #0f172a; color: #f472b6; padding: 1px 6px; border-radius: 3px; font-size: 12px; }}
  .row {{ display: flex; gap: 10px; margin: 4px 0; font-size: 14px; }}
  .row .k {{ min-width: 260px; color: #94a3b8; }}
  .row .v {{ color: #e2e8f0; }}
  .verdict {{ background: #0c1526; border: 1px solid #334155; border-left: 4px solid #f97316;
               padding: 14px 16px; border-radius: 6px; margin-top: 6px; font-size: 14px; line-height: 1.7; }}
  .meta {{ color: #94a3b8; font-size: 13px; margin-top: 4px; }}
</style>
</head>
<body>
  <h1>{title} · 复测证据</h1>
  <div class="meta">
    模型 <span class="badge b-code">{code} / {name}</span>
    结论 <span class="badge b-rating">{rating}</span>
  </div>

  <h2>本模型新增文件</h2>
  <div class="card">
    <ul>{files}</ul>
  </div>

  <h2>接线与集成</h2>
  <div class="card">{wiring}</div>

  <h2>静态检查与轨迹交叉核对</h2>
  <div class="card">
    <ul>{static_hits}</ul>
  </div>

  <h2>综合判定</h2>
  <div class="verdict">{verdict}</div>
</body>
</html>
"""


def li(items):
    return ''.join(f'<li>{x}</li>' for x in items)


def rows(items):
    return ''.join(
        f'<div class="row"><div class="k">{k}</div><div class="v">{v}</div></div>'
        for k, v in items
    )


def code_rows(items):
    return ''.join(
        f'<li><code>{loc}</code> — {msg}</li>' for loc, msg in items
    )


def safe_col(col):
    return col.replace(' ', '_').replace('/', '_')


def main(task_id):
    task_dir = ROOT / 'tasks' / task_id
    findings_path = task_dir / 'review_findings.json'
    if not findings_path.exists():
        print(f'no {findings_path}', file=sys.stderr)
        sys.exit(2)

    findings = json.loads(findings_path.read_text(encoding='utf-8'))
    model_map = json.loads((task_dir / 'model_map.json').read_text(encoding='utf-8'))['models']

    pages_dir = task_dir / 'screenshot_pages'
    pages_dir.mkdir(exist_ok=True)
    deliv = ROOT / 'delivery' / task_id / 'screenshots'
    deliv.mkdir(parents=True, exist_ok=True)

    pages_map = {}
    for col, entry in findings['models'].items():
        code = model_map[col]['code']
        html = HTML_TEMPLATE.format(
            title=findings.get('title', task_id),
            code=code,
            name=col,
            rating=entry['rating'],
            files=li(entry['files_added']),
            wiring=rows(entry['wiring']),
            static_hits=code_rows(entry['static_hits']),
            verdict=entry['verdict'],
        )
        p = pages_dir / f'{safe_col(col)}.html'
        p.write_text(html, encoding='utf-8')
        pages_map[col] = p

    # write playwright driver
    js_lines = [
        "const { chromium } = require('playwright');",
        "(async () => {",
        "  const browser = await chromium.launch();",
        "  const ctx = await browser.newContext({ viewport: { width: 1240, height: 900 }, deviceScaleFactor: 1 });",
        "  const page = await ctx.newPage();",
    ]
    for col, p in pages_map.items():
        out = deliv / f'{safe_col(col)}_01_review.png'
        url = p.resolve().as_uri()
        js_lines.append(f"  await page.goto({json.dumps(url)});")
        js_lines.append("  await page.waitForLoadState('networkidle');")
        js_lines.append(f"  await page.screenshot({{ path: {json.dumps(str(out))}, fullPage: true }});")
    js_lines.append("  await browser.close();")
    js_lines.append("})();")
    js_path = SKILL_DIR / f'_shoot_{task_id}.js'
    js_path.write_text('\n'.join(js_lines), encoding='utf-8')
    try:
        subprocess.run(['node', str(js_path)], cwd=str(SKILL_DIR), check=True)
    finally:
        try:
            js_path.unlink()
        except OSError:
            pass
    print('screenshots written to', deliv)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: screenshot_arkts.py <TASK_ID>', file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1])
