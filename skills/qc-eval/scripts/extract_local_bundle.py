#!/usr/bin/env python3
"""Extract a local 24期 task bundle into the standard QC layout.

Input:
    tasks/<TASK_ID>.zip

Output:
    tasks/<TASK_ID>/extracted/source/
    tasks/<TASK_ID>/extracted/<MODEL_CODE>/
    tasks/<TASK_ID>/feedback/*.json
    tasks/<TASK_ID>/model_map.json
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import zipfile
import os
import zlib
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent

MODEL_MAP = {
    "60B0605F": "0605F",
    "GLM5.1": "glm5.1",
    "30B0606D": "0606D",
    "Q3.7Max": "qwen3.7max",
}
SHEET_ORDER = ["0605F", "glm5.1", "0606D", "qwen3.7max"]


def safe_member(name: str) -> bool:
    p = PurePosixPath(name.replace("\\", "/"))
    return bool(p.parts) and not p.is_absolute() and ".." not in p.parts


def fs_path(path: Path) -> str:
    """Return a Windows extended-length path when needed."""
    s = str(path.resolve())
    if os.name == "nt" and not s.startswith("\\\\?\\"):
        return "\\\\?\\" + s
    return s


def extract_zip_bytes(data: bytes, out_dir: Path, *, force: bool) -> int:
    if out_dir.exists():
        if force:
            shutil.rmtree(out_dir)
        else:
            return 0
    os.makedirs(fs_path(out_dir), exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not safe_member(info.filename):
                continue
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            target = out_dir.joinpath(*parts)
            os.makedirs(fs_path(target.parent), exist_ok=True)
            with zf.open(info) as src, open(fs_path(target), "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def _read_u16(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 2], "little")


def _read_u32(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 4], "little")


def extract_streaming_zip_bytes(data: bytes, out_dir: Path, *, force: bool) -> int:
    """Best-effort extractor for artifacts with damaged central directories.

    Some 24期 local bundles contain ZIPs that have valid local file records but
    a broken/truncated central directory, so Python's ZipFile rejects the whole
    artifact. The generated artifacts all use local records with deflate data
    descriptors; walking those records lets us keep the workflow moving.
    """
    if out_dir.exists():
        if force:
            shutil.rmtree(out_dir)
        else:
            return 0
    os.makedirs(fs_path(out_dir), exist_ok=True)
    count = 0
    pos = 0
    while pos + 30 <= len(data) and data[pos:pos + 4] == b"PK\x03\x04":
        flag = _read_u16(data, pos + 6)
        method = _read_u16(data, pos + 8)
        comp_size = _read_u32(data, pos + 18)
        name_len = _read_u16(data, pos + 26)
        extra_len = _read_u16(data, pos + 28)
        name_start = pos + 30
        data_start = name_start + name_len + extra_len
        name = data[name_start:name_start + name_len].decode("utf-8", errors="replace")
        if not safe_member(name):
            break
        parts = PurePosixPath(name.replace("\\", "/")).parts
        target = out_dir.joinpath(*parts)
        is_dir = name.endswith("/")
        if is_dir:
            os.makedirs(fs_path(target), exist_ok=True)
        else:
            os.makedirs(fs_path(target.parent), exist_ok=True)
            next_pos = -1
            if method == 0:
                file_end = data_start + comp_size
                with open(fs_path(target), "wb") as dst:
                    dst.write(data[data_start:file_end])
                next_pos = file_end
            elif method == 8:
                decomp = zlib.decompressobj(-15)
                cur = data_start
                truncated = False
                with open(fs_path(target), "wb") as dst:
                    while cur < len(data):
                        chunk = data[cur:cur + 1024 * 1024]
                        out = decomp.decompress(chunk)
                        if out:
                            dst.write(out)
                        cur += len(chunk)
                        if decomp.eof:
                            cur -= len(decomp.unused_data)
                            break
                    if not decomp.eof:
                        truncated = True
                if truncated:
                    try:
                        target.unlink(missing_ok=True)
                    except TypeError:
                        if target.exists():
                            target.unlink()
                    print(f"      [warn] truncated stream at {name}; keeping files extracted before it")
                    break
                next_pos = data.find(b"PK\x03\x04", cur)
                if next_pos < 0:
                    break
            else:
                raise zipfile.BadZipFile(f"unsupported compression method {method} for {name}")
            count += 1
            if next_pos < 0:
                break
            pos = next_pos
            continue
        next_pos = data.find(b"PK\x03\x04", data_start)
        if next_pos < 0:
            break
        pos = next_pos
    return count


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def process_one(task_id: str, tasks_dir: Path, *, force: bool) -> bool:
    task_id = task_id.upper()
    bundle = tasks_dir / f"{task_id}.zip"
    if not bundle.exists():
        print(f"[skip] {task_id}: {bundle.relative_to(REPO_ROOT)} not found")
        return False

    task_dir = tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    extracted = task_dir / "extracted"
    artifacts = task_dir / "artifacts"
    source_dir = task_dir / "source"

    with zipfile.ZipFile(bundle) as outer:
        print(f"\n==> {task_id}")
        # Keep raw bundle files available for review.
        for info in outer.infolist():
            if info.is_dir() or not safe_member(info.filename):
                continue
            parts = PurePosixPath(info.filename.replace("\\", "/")).parts
            if parts[0] in {"raw", "images"} or info.filename.endswith(".html"):
                target = task_dir.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and not force:
                    continue
                with outer.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        source_bytes = outer.read("source/source_artifact.zip")
        (source_dir).mkdir(parents=True, exist_ok=True)
        (source_dir / "source_artifact.zip").write_bytes(source_bytes)
        n = extract_zip_bytes(source_bytes, extracted / "source", force=force)
        print(f"   source: {n} file(s)")

        task_details = json.loads(outer.read(f"raw/{task_id}/task_details.json").decode("utf-8"))
        runs = task_details.get("taskManagerTask", {}).get("runs") or task_details.get("runs") or []
        code_to_model = {}
        for run in runs:
            code = run.get("modelId")
            model_name = run.get("modelName")
            if code and model_name in MODEL_MAP:
                code_to_model[code] = model_name

        models = {}
        extracted_codes = []
        for code, model_name in sorted(code_to_model.items(), key=lambda item: SHEET_ORDER.index(MODEL_MAP[item[1]])):
            col = MODEL_MAP[model_name]
            zname = f"artifacts/{code}_artifact.zip"
            if zname in outer.namelist():
                zbytes = outer.read(zname)
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / f"{code}_artifact.zip").write_bytes(zbytes)
                try:
                    n = extract_zip_bytes(zbytes, extracted / code, force=force)
                except zipfile.BadZipFile:
                    print(f"   {col} ({code}): central directory broken, using streaming ZIP fallback")
                    n = extract_streaming_zip_bytes(zbytes, extracted / code, force=force)
                print(f"   {col} ({code}): {n} file(s)")
                artifact_missing = False
            else:
                print(f"   {col} ({code}): artifact missing ({zname})")
                artifact_missing = True
            models[col] = {
                "code": code,
                "display_name": col,
                "platform_url": "",
                "entry": ".",
                "comment_pngs": [],
                "artifact_missing": artifact_missing,
            }
            extracted_codes.append(code)

            raw_base = f"raw/{task_id}/{code}"
            check = json.loads(outer.read(f"{raw_base}/scoring_feedback.json").decode("utf-8"))
            user_feedback = json.loads(outer.read(f"{raw_base}/user_feedback.json").decode("utf-8"))
            write_json(task_dir / "feedback" / f"{col}__{code}.check.json", check)
            write_json(task_dir / "feedback" / f"{col}__{code}.user_feedback.json", user_feedback)

        model_map = {
            "task_id": task_id,
            "sheet_columns": SHEET_ORDER,
            "models": models,
            "extracted_codes": extracted_codes,
            "source": f"24 local task bundle tasks/{task_id}.zip",
        }
        write_json(task_dir / "model_map.json", model_map)

    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_ids", nargs="+")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    ok = sum(process_one(tid, tasks_dir, force=args.force) for tid in args.task_ids)
    return 0 if ok == len(args.task_ids) else 1


if __name__ == "__main__":
    sys.exit(main())
