#!/usr/bin/env python3
"""Extract 33/34期 platform-downloaded artifact zips into the standard layout.

Input comes from fetch_platform_artifacts.js:

    tasks/<TASK_ID>/platform_artifacts/artifact_index.json

Output:

    tasks/<TASK_ID>/extracted/source/
    tasks/<TASK_ID>/extracted/<MODEL_ID>/

The extractor is intentionally conservative: it skips unsafe zip members and
does not overwrite an existing target unless --force is passed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent


def is_safe_member(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return not p.is_absolute() and ".." not in p.parts


def strip_single_root(parts: list[str]) -> list[str]:
    """Drop common archive wrapper dirs like VBK4N7/ or VBK4N7_JOHWC/."""
    if len(parts) >= 2 and parts[0]:
        return parts[1:]
    return parts


def extract_zip(
    zip_path: Path,
    out_dir: Path,
    *,
    force: bool,
    strip_root: bool = True,
    only_prefix: str | None = None,
) -> tuple[int, int]:
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    if out_dir.exists():
        if force:
            shutil.rmtree(out_dir)
        else:
            print(f"   [keep] {out_dir.relative_to(REPO_ROOT)} exists (--force 覆盖)")
            return 0, 0
    out_dir.mkdir(parents=True, exist_ok=True)

    files = 0
    skipped = 0
    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        root_names = {
            PurePosixPath(i.filename.replace("\\", "/")).parts[0]
            for i in infos
            if PurePosixPath(i.filename.replace("\\", "/")).parts
        }
        do_strip = strip_root and len(root_names) == 1
        for info in infos:
            name = info.filename
            if not is_safe_member(name):
                skipped += 1
                continue
            parts = list(PurePosixPath(name.replace("\\", "/")).parts)
            if only_prefix:
                prefix = only_prefix.strip("/")
                if not parts or parts[0] != prefix:
                    skipped += 1
                    continue
                parts = parts[1:]
            if do_strip:
                parts = strip_single_root(parts)
            if not parts:
                skipped += 1
                continue
            target = out_dir.joinpath(*parts)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                files += 1
            except OSError:
                skipped += 1
    return files, skipped


def process_one(task_id: str, tasks_dir: Path, force: bool) -> bool:
    task_dir = tasks_dir / task_id
    index_path = task_dir / "platform_artifacts" / "artifact_index.json"
    if not index_path.exists():
        print(f"[skip] {task_id}: {index_path.relative_to(REPO_ROOT)} not found")
        return False
    idx = json.loads(index_path.read_text(encoding="utf-8"))
    extracted = task_dir / "extracted"
    extracted.mkdir(parents=True, exist_ok=True)

    print(f"\n==> {task_id}")
    source_zip = idx.get("source_zip")
    if source_zip:
        zip_path = task_dir / source_zip
        # /api/tasks/<TASK>/download returns a full task bundle. Keep only the
        # original source/ subtree here; per-model zips are extracted below.
        files, skipped = extract_zip(zip_path, extracted / "source", force=force, only_prefix="source")
        print(f"   source: {files} file(s), {skipped} skipped")

    for m in idx.get("models", []):
        code = m.get("code")
        z = m.get("zip")
        if not code or not z:
            continue
        files, skipped = extract_zip(task_dir / z, extracted / code, force=force)
        print(f"   {m.get('name', code)} ({code}): {files} file(s), {skipped} skipped")

    entries = sorted(p.name for p in extracted.iterdir() if p.is_dir())
    print(f"   extracted/ top-level: {entries[:30]}{' ...' if len(entries) > 30 else ''}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_ids", nargs="+")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    ok = 0
    tasks_dir = Path(args.tasks_dir)
    for tid in args.task_ids:
        if process_one(tid, tasks_dir, args.force):
            ok += 1
    return 0 if ok == len(args.task_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
