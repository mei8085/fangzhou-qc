#!/usr/bin/env python3
"""针对 pnpm benchmark 型任务（如 IEM2XW SLA policies）：
渲染每个模型的 benchmark-result/<task>.json 步骤摘要 + 关键交付物文件清单
成两张单图 + 一张并排合成图。

Outputs (under delivery/<TASK_ID>/screenshots/):
    <COL>_01_bench.png     — benchmark-result JSON 关键步骤摘要
    <COL>_02_files.png     — 交付关键文件树
    <COL>_verify.png       — 并排合成
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from compose_cli import (
    _FONT_CANDIDATES,
    load_font,
    render_panel,
    trim_panel,
)
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent


def summarize_bench(bench: dict) -> str:
    lines = []
    lines.append(f"task            : {bench.get('task')}")
    lines.append(f"total           : {bench.get('total')}")
    lines.append(f"passed          : {bench.get('passed')}")
    lines.append(f"lint            : {bench.get('lint')}")
    lines.append(f"typecheck       : {bench.get('typecheck')}")
    lines.append(f"baseTests       : {bench.get('baseTests')}")
    lines.append(f"taskPublicTests : {bench.get('taskPublicTests')}")
    lines.append(f"baseE2E         : {bench.get('baseE2E')}")
    lines.append(f"taskE2E         : {bench.get('taskE2E')}")
    failures = bench.get('failures') or []
    lines.append(f"failures        : {len(failures)}")
    lines.append("")
    lines.append("steps:")
    for st in bench.get("steps", []):
        label = st.get("label")
        passed = "OK" if st.get("passed") else "FAIL"
        status = st.get("status")
        lines.append(f"  {label:<18} {passed}  status={status}")
        stdout = (st.get("stdout") or "").strip().splitlines()
        # keep only lines that carry signal
        for ln in stdout:
            if any(k in ln for k in ("passed", "Tests", "Test Files", "RUN", "Duration", "ok")):
                lines.append(f"      | {ln.strip()}")
    return "\n".join(lines)


def list_key_files(model_dir: Path) -> str:
    """Return a text listing of the SLA-related deliverables in the model dir."""
    key_globs = [
        "migrations/002*.sql",
        "src/server/routes/slaPolicies.ts",
        "src/server/services/sla*.ts",
        "src/client/components/Sla*.tsx",
        "src/shared/types.ts",
    ]
    lines: list[str] = []
    lines.append(f"model dir: {model_dir.name}")
    lines.append("")
    for glob in key_globs:
        hits = sorted(model_dir.glob(glob))
        if not hits:
            lines.append(f"  {glob:<45}  (missing)")
            continue
        for p in hits:
            rel = p.relative_to(model_dir).as_posix()
            try:
                size = p.stat().st_size
                nl = sum(1 for _ in p.open("r", encoding="utf-8", errors="ignore"))
            except OSError:
                size, nl = 0, 0
            lines.append(f"  {rel:<50}  {nl:>4} lines  {size:>7} B")
    lines.append("")
    lines.append("routes/tickets extension for sla:")
    tickets_route = model_dir / "src/server/routes/tickets.ts"
    if tickets_route.exists():
        txt = tickets_route.read_text(encoding="utf-8", errors="ignore")
        for i, ln in enumerate(txt.splitlines(), 1):
            if "sla" in ln.lower():
                lines.append(f"  tickets.ts:{i:>4}  {ln.strip()[:110]}")
    return "\n".join(lines)


def compose_one(sheet_label: str, model_dir: Path, bench_json: Path, out_dir: Path) -> dict:
    mono = load_font(_FONT_CANDIDATES, 13)
    panel_w, panel_h = 950, 1400

    out_dir.mkdir(parents=True, exist_ok=True)
    tag = sheet_label.replace(" ", "_")

    try:
        bench = json.loads(bench_json.read_text(encoding="utf-8"))
        bench_text = summarize_bench(bench)
    except Exception as exc:
        bench_text = f"<failed to read {bench_json}: {exc}>"

    files_text = list_key_files(model_dir)

    bench_png = out_dir / f"{tag}_01_bench.png"
    files_png = out_dir / f"{tag}_02_files.png"
    verify_png = out_dir / f"{tag}_verify.png"

    left = trim_panel(render_panel(bench_text, mono, (panel_w, panel_h)))
    left.save(bench_png)
    right = trim_panel(render_panel(files_text, mono, (panel_w, panel_h)))
    right.save(files_png)

    gap = 8
    total_w = left.width + right.width + gap * 3
    total_h = max(left.height, right.height) + gap * 2
    composite = Image.new("RGB", (total_w, total_h), "black")
    composite.paste(left, (gap, gap))
    composite.paste(right, (gap + left.width + gap, gap))
    composite.save(verify_png)

    return {"bench": bench_png, "files": files_png, "verify": verify_png}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_id")
    p.add_argument("--bench-name", default="task-001.json",
                   help="benchmark-result/<name> to render (default task-001.json)")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--delivery-dir", default=str(REPO_ROOT / "delivery"))
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    task_dir = tasks_dir / args.task_id
    map_path = task_dir / "model_map.json"
    if not map_path.exists():
        print(f"[err] missing {map_path}", file=sys.stderr)
        return 1
    mapping = json.loads(map_path.read_text(encoding="utf-8"))
    out_dir = Path(args.delivery_dir) / args.task_id / "screenshots"
    for col, info in mapping["models"].items():
        code = info["code"]
        model_dir = task_dir / "extracted" / code
        bench_json = model_dir / "benchmark-result" / args.bench_name
        if not model_dir.exists():
            print(f"[warn] no model dir for {col} ({code})", file=sys.stderr)
            continue
        res = compose_one(col, model_dir, bench_json, out_dir)
        print(f"  {col:<30} -> {res['verify'].name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
