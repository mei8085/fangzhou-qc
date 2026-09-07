#!/usr/bin/env python3
"""Render terminal-style evidence for configured models absent from Ark runs."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))
from compose_cli import render_text_png  # noqa: E402
from lib.g1 import OUTPUT_SUBDIR  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def collected_codes(payload: dict) -> list[str]:
    return [
        str((row.get("modelRun") or {}).get("codeName") or "").strip()
        for row in payload.get("result") or []
        if str((row.get("modelRun") or {}).get("codeName") or "").strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--only", default="", help="only render one sheet/platform model")
    args = parser.parse_args()

    task_dir = REPO_ROOT / "tasks" / args.task_id
    map_path = task_dir / "model_map.json"
    runs_path = task_dir / OUTPUT_SUBDIR / "model_runs.json"
    if not map_path.exists() or not runs_path.exists():
        print(f"ERROR: missing {map_path if not map_path.exists() else runs_path}", file=sys.stderr)
        return 2

    model_map = load_json(map_path)
    runs = load_json(runs_path)
    codes = collected_codes(runs)
    normalized_codes = {code.lower() for code in codes}
    missing = []
    for sheet, info in (model_map.get("models") or {}).items():
        if not info.get("missing"):
            continue
        needle = args.only.strip().lower()
        if needle and needle not in {sheet.lower(), str(info.get("platform") or "").lower()}:
            continue
        platform = str(info.get("platform") or "").strip()
        if platform.lower() in normalized_codes:
            print(f"ERROR: {sheet}/{platform} is marked missing but exists in model_runs.json", file=sys.stderr)
            return 1
        missing.append((sheet, info))

    if not missing:
        print("ERROR: no matching missing models", file=sys.stderr)
        return 1

    out_dir = REPO_ROOT / "delivery" / args.task_id / "screenshots"
    out_dir.mkdir(parents=True, exist_ok=True)
    code_list = ",".join(codes) or "(none)"
    for sheet, info in missing:
        platform = str(info.get("platform") or "").strip()
        text = "\n".join([
            f"task_id={args.task_id}",
            f"expected_model={sheet}/{platform}",
            f"collected_platform_codes={code_list}",
            "matching_run_count=0",
            "status=not_submitted",
        ])
        tag = sheet.replace(" ", "_")
        frame = out_dir / f"{tag}_01_missing_model.png"
        verify = out_dir / f"{tag}_verify.png"
        render_text_png(text, frame)
        shutil.copyfile(frame, verify)
        print(f"{sheet}/{platform}: wrote {frame.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
