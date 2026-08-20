#!/usr/bin/env python3
"""26 期专用：不依赖轨迹数据 / 方舟平台，直接从固定映射 + 本地 extracted/
构造 `tasks/<TASK_ID>/model_map.json`（schema 与 28/29 期一致）。

26 期特点
---------
- 没有轨迹数据（既没有飞书 29期轨迹数据 sheet 的 HTML，也没有方舟平台 API）
- 因此**只能对模型完成情况本身进行评分和评价**，不能像 28/29 期那样评"标注人评价
  是否准确"
- 4 个模型的代号↔模型名映射对整个 26 期是**固定的全局映射**，写在本脚本的
  `CODE_TO_MODEL_NAME` 里，不依赖任何外部 API

输出
----
`tasks/<TASK_ID>/model_map.json`，字段：

- `task_id` / `sheet_columns` / `models` / `extracted_codes` / 其余同 28/29 期
- `models[<name>]`：`code`、`display_name`、`platform_url=""`、`comment_pngs=[]`、
  `entry`
- `source = "26期固定映射 (fetch_no_trajectory.py)"`

用法::

    fetch_no_trajectory.py <TASK_ID> [<TASK_ID> ...] [--tasks-dir tasks]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from fetch_trajectory import detect_vite_entry  # noqa: E402

REPO_ROOT = HERE.parent.parent.parent

# 26 期全局代号 → 真实模型名（用户提供的方舟平台"模型管理"截图）。
# 新代号出现时补进来即可，不必按题保存 mapping.json。
CODE_TO_MODEL_NAME: dict[str, str] = {
    "QB7P9": "60B0605F",
    "M6HGZ": "60B0613H",
    "79SLI": "60B0614C",
    "AJAL3": "Opus 4.6",
}


def scan_extracted_codes(extracted_dir: Path) -> list[str]:
    if not extracted_dir.exists():
        return []
    return sorted(
        p.name for p in extracted_dir.iterdir()
        if p.is_dir() and p.name not in ("comments", "logs", "source")
    )


def build_model_map(task_id: str, extracted_dir: Path) -> tuple[dict, list[str]]:
    """Return (model_map_dict, warnings)."""
    warnings: list[str] = []
    codes = scan_extracted_codes(extracted_dir)
    models: dict[str, dict] = {}
    used_codes: list[str] = []
    for code in codes:
        name = CODE_TO_MODEL_NAME.get(code)
        if not name:
            warnings.append(f"extracted 里出现未知代号 {code!r}，请补进 CODE_TO_MODEL_NAME")
            continue
        entry = detect_vite_entry(extracted_dir / code)
        models[name] = {
            "code": code,
            "display_name": name,
            "platform_url": "",
            "comment_pngs": [],
            "entry": entry,
        }
        used_codes.append(code)

    declared = set(CODE_TO_MODEL_NAME.keys())
    missing_codes = sorted(c for c in codes if c not in used_codes)
    unused_declared = sorted(c for c in declared if c not in codes)

    mm = {
        "task_id": task_id,
        "view_user": None,
        "sheet_columns": [m["display_name"] for m in models.values()],
        "models": models,
        "extracted_codes": codes,
        "extra_extracted_codes": missing_codes,
        "missing_from_extracted": unused_declared,
        "source": "26期固定映射 (fetch_no_trajectory.py)",
    }
    return mm, warnings


def process_one(task_id: str, tasks_dir: Path) -> bool:
    task_id = task_id.upper()
    print(f"\n==> {task_id}")
    task_dir = tasks_dir / task_id
    extracted_dir = task_dir / "extracted"
    if not extracted_dir.exists():
        print(f"  [err] {extracted_dir} 不存在；先跑 fetch_portal + extract_portal")
        return False
    mm, warnings = build_model_map(task_id, extracted_dir)
    for w in warnings:
        print(f"  [warn] {w}")
    if not mm["models"]:
        print(f"  [err] extracted/ 里没识别出任何已知代号")
        return False
    out = task_dir / "model_map.json"
    out.write_text(json.dumps(mm, ensure_ascii=False, indent=2), encoding="utf-8")
    codes_desc = ", ".join(f"{v['code']}={k}" for k, v in mm["models"].items())
    print(f"  写入 model_map.json ({len(mm['models'])} 模型: {codes_desc})")
    entries_desc = ", ".join(f"{k}:{v['entry']}" for k, v in mm["models"].items())
    print(f"  vite entry: {entries_desc}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("task_ids", nargs="+", help="一个或多个任务 ID")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    args = p.parse_args()
    tasks_dir = Path(args.tasks_dir)
    n_ok = 0
    for tid in args.task_ids:
        if process_one(tid, tasks_dir):
            n_ok += 1
    print(f"\n完成 {n_ok}/{len(args.task_ids)} 个任务")
    return 0 if n_ok == len(args.task_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
