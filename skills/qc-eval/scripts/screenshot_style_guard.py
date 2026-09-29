#!/usr/bin/env python3
"""Guard verification screenshots against artificial compose artifacts.

Rules:
- If a model has only one per-step screenshot, <COL>_verify.png must be an
  exact copy of that screenshot.
- If a model has multiple per-step screenshots, the verify image must be a
  no-margin tiling of those images. Plain black fill is allowed only in unused
  canvas areas caused by different image heights; added frames, headers, labels,
  captions, or reviewer-written explanation panels are still rejected by size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

from zero_one_redline import is_zero_one

REPO_ROOT = Path(__file__).resolve().parents[3]


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())


def model_screenshot_tag(name: str) -> str:
    """Match compose.py tags: only spaces become underscores."""
    return str(name).replace(" ", "_")


def iter_model_names(model_map: dict) -> list[str]:
    """Prefer sheet_columns, then models key order."""
    cols = model_map.get("sheet_columns")
    if cols:
        return list(cols)
    return list((model_map.get("models") or {}).keys())


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def possible_no_margin_sizes(images: list[Image.Image]) -> set[tuple[int, int]]:
    sizes: set[tuple[int, int]] = set()
    n = len(images)
    for wrap_cols in range(1, n + 1):
        rows = [images[i : i + wrap_cols] for i in range(0, n, wrap_cols)]
        width = max(sum(im.width for im in row) for row in rows)
        height = sum(max(im.height for im in row) for row in rows)
        sizes.add((width, height))
    return sizes


def check_task(task_id: str) -> list[str]:
    task_dir = REPO_ROOT / "tasks" / task_id
    shot_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    map_path = task_dir / "model_map.json"
    errors: list[str] = []

    qc_path = task_dir / "qc_cells.json"
    sheet = load_json(qc_path).get("sheet", {}) if qc_path.exists() else {}
    if is_zero_one(sheet):
        model_map = {"sheet_columns": list((sheet.get("models") or {}).keys())}
    elif map_path.exists():
        model_map = load_json(map_path)
    else:
        return [f"{task_id}: missing tasks/{task_id}/model_map.json"]
    if not shot_dir.exists():
        return [f"{task_id}: missing delivery/{task_id}/screenshots"]

    for model_name in iter_model_names(model_map):
        tag = model_screenshot_tag(model_name)
        frames = sorted(
            p for p in shot_dir.glob(f"{tag}_*.png")
            if re.match(rf"{re.escape(tag)}_\d+_.+\.png$", p.name)
        )
        verify = shot_dir / f"{tag}_verify.png"
        if not frames:
            continue
        if not verify.exists():
            errors.append(f"{task_id}/{model_name}: missing {verify.name}")
            continue

        if len(frames) == 1:
            if sha256(frames[0]) != sha256(verify):
                errors.append(
                    f"{task_id}/{model_name}: single-frame verify image must be an exact copy "
                    f"of {frames[0].name}; rerun compose.py/compose_cli.py"
                )
            continue

        try:
            imgs = [Image.open(p) for p in frames]
            verify_img = Image.open(verify)
        except Exception as exc:
            errors.append(f"{task_id}/{model_name}: cannot open screenshot: {exc}")
            continue

        expected_sizes = possible_no_margin_sizes(imgs)
        actual = (verify_img.width, verify_img.height)
        if actual not in expected_sizes:
            want = ", ".join(f"{w}x{h}" for w, h in sorted(expected_sizes))
            errors.append(
                f"{task_id}/{model_name}: {verify.name} size is {actual[0]}x{actual[1]}, "
                f"expected no-margin tiling size {want}; do not add padding, "
                "headers, labels, borders, or explanation panels"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="+")
    args = parser.parse_args()

    all_errors: list[str] = []
    for task_id in args.task_ids:
        errors = check_task(task_id)
        if errors:
            print(f"  [FAIL] {task_id}")
            for err in errors:
                print(f"    - {err}")
            all_errors.extend(errors)
        else:
            print(f"  [OK]  {task_id}")
    return 1 if all_errors else 0


if __name__ == "__main__":
    sys.exit(main())
