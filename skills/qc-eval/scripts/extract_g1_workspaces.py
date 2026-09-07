#!/usr/bin/env python3
"""Safely extract current-period Ark workspace zips for local verification."""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent
MAX_FILES = 100_000
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


def safe_relative_member(name: str) -> Path | None:
    path = PurePosixPath(name.replace("\\", "/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"unsafe zip member: {name!r}")
    if path.parts[0] != "workspace" or len(path.parts) == 1:
        return None
    relative = PurePosixPath(*path.parts[1:])
    if relative.parts[0] == ".autocase":
        return None
    return Path(*relative.parts)


def extract_workspace(archive: Path, target: Path, *, force: bool) -> int:
    if target.exists():
        if not force:
            return 0
        shutil.rmtree(target)
    target.mkdir(parents=True)

    count = 0
    total = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            relative = safe_relative_member(info.filename)
            if relative is None or info.is_dir():
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise RuntimeError(f"symlink zip member is not allowed: {info.filename!r}")
            count += 1
            total += info.file_size
            if count > MAX_FILES or total > MAX_UNCOMPRESSED_BYTES:
                raise RuntimeError(f"workspace archive exceeds extraction limits: {archive}")
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
    return count


def attachment_roots(archive: Path, task_id: str) -> list[str]:
    """Return top-level directories from the source attachment for this task."""
    with zipfile.ZipFile(archive) as workspace_zip:
        manifests = [
            info for info in workspace_zip.infolist()
            if info.filename == "workspace/.autocase/input/manifest.json"
        ]
        manifest = None
        for info in manifests:
            try:
                candidate = json.loads(workspace_zip.read(info))
            except (ValueError, UnicodeDecodeError):
                continue
            if str(candidate.get("taskId")) == str(task_id):
                manifest = candidate
        if not manifest:
            return []
        zip_names = [
            str(item.get("fileName") or "")
            for item in manifest.get("attachments") or []
            if str(item.get("fileName") or "").lower().endswith(".zip")
        ]
        roots: set[str] = set()
        for name in zip_names:
            member = f"workspace/.autocase/input/attachments/{name}"
            try:
                nested_bytes = workspace_zip.read(member)
                with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
                    roots.update(
                        PurePosixPath(info.filename.replace("\\", "/")).parts[0]
                        for info in nested.infolist()
                        if info.filename and not PurePosixPath(info.filename).is_absolute()
                    )
            except (KeyError, zipfile.BadZipFile):
                continue
        return sorted(roots)


def trajectory_entry(task_dir: Path, run_id: str, platform: str, candidates: list[Path]) -> Path | None:
    trajectory_dir = task_dir / "ark_g1" / f"{run_id}__{platform}" / "trajectory"
    texts = []
    for path in trajectory_dir.glob("*.json"):
        texts.append(path.read_text(encoding="utf-8", errors="replace"))
    haystack = "\n".join(texts)
    scored = []
    for path in candidates:
        name = path.name
        count = len(re.findall(rf"(?<![\w-]){re.escape(name)}(?![\w-])", haystack))
        scored.append((count, path))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1]
    return None


def detect_entry(
    target: Path,
    archive: Path,
    task_id: str,
    task_dir: Path,
    run_id: str,
    platform: str,
) -> Path:
    source_roots = [target / name for name in attachment_roots(archive, task_id)]
    source_projects = [
        path for path in source_roots
        if (path / "package.json").is_file() or (path / "pyproject.toml").is_file()
    ]
    if len(source_projects) == 1:
        return source_projects[0]
    if (target / "package.json").is_file() or (target / "pyproject.toml").is_file():
        return target
    package_projects = {
        path.parent
        for path in target.rglob("package.json")
        if ".autocase" not in path.parts and "node_modules" not in path.parts and "review" not in path.parts
    }
    python_projects = {
        path.parent
        for path in target.rglob("pyproject.toml")
        if ".autocase" not in path.parts
    }
    if package_projects:
        min_depth = min(len(path.relative_to(target).parts) for path in package_projects)
        package_projects = {
            path for path in package_projects
            if len(path.relative_to(target).parts) == min_depth
        }
    candidates = sorted(
        package_projects or python_projects or {
            path.parent
            for path in target.rglob("requirements.txt")
            if ".autocase" not in path.parts
        },
        key=lambda path: (len(path.relative_to(target).parts), str(path)),
    )
    traced = trajectory_entry(task_dir, run_id, platform, candidates)
    if traced:
        return traced
    return candidates[0] if candidates else target


def process_task(task_id: str, tasks_dir: Path, *, force: bool) -> bool:
    task_dir = tasks_dir / task_id
    model_map_path = task_dir / "model_map.json"
    if not model_map_path.exists():
        print(f"[err] missing {model_map_path}", file=sys.stderr)
        return False
    model_map = json.loads(model_map_path.read_text(encoding="utf-8-sig"))
    models = model_map.get("models") or {}
    if not models:
        print(f"[err] no models in {model_map_path}", file=sys.stderr)
        return False

    print(f"==> task {task_id}")
    for sheet, info in models.items():
        if info.get("missing"):
            info["artifact_missing"] = True
            print(f"  {sheet}/{info.get('platform') or '-'}: not submitted; skip workspace extraction")
            continue
        if info.get("artifact_download_unavailable"):
            info["artifact_missing"] = True
            info["artifact_download_state"] = "unavailable"
            print(f"  {sheet}/{info.get('platform') or '-'}: download unavailable; skip workspace extraction")
            continue
        platform = str(info.get("platform") or "").strip()
        run_id = str(info.get("task_model_run_id") or "").strip()
        code = str(info.get("code") or sheet).strip()
        workspace_dir = task_dir / "ark_g1" / f"{run_id}__{platform}" / "workspace"
        archives = sorted(workspace_dir.glob("*.zip"))
        if len(archives) != 1:
            raise RuntimeError(f"expected one workspace zip for {sheet}, found {len(archives)} in {workspace_dir}")
        target = task_dir / "extracted" / code
        count = extract_workspace(archives[0], target, force=force)
        entry = detect_entry(target, archives[0], task_id, task_dir, run_id, platform)
        info["entry"] = entry.relative_to(target).as_posix() or "."
        info["workspace_zip"] = archives[0].relative_to(task_dir).as_posix()
        info["artifact_missing"] = False
        state = f"extracted {count} file(s)" if count else "already extracted"
        print(f"  {sheet}/{platform}: {state}; entry={info['entry']}")

    model_map_path.write_text(json.dumps(model_map, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  updated {model_map_path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_ids", nargs="+")
    parser.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    parser.add_argument("--force", action="store_true", help="replace existing extracted model directories")
    args = parser.parse_args()
    ok = sum(process_task(str(task_id), Path(args.tasks_dir), force=args.force) for task_id in args.task_ids)
    return 0 if ok == len(args.task_ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
