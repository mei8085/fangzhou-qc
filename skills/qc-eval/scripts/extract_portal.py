#!/usr/bin/env python3
"""Extract a portal-downloaded task-<ID>.tar.zst into tasks/<ID>/extracted/.

Skips symlinks (the archives contain Linux-absolute symlinks like
/home/claude-user/.claude/debug/... that are useless on Windows) and tolerates
the leading "task-<ID>/" path prefix inside the archive.

Usage:
    extract_portal.py <TASK_ID> [<TASK_ID> ...] [--tasks-dir tasks] [--force]
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent.parent


def decompress_zst(archive: Path, tar_path: Path) -> None:
    """Decompress .zst with the zstd CLI when available, else Python fallback."""
    try:
        subprocess.run(
            ["zstd", "-d", "-q", str(archive), "-o", str(tar_path), "--force"],
            check=True,
        )
        return
    except FileNotFoundError:
        pass
    try:
        import zstandard as zstd  # type: ignore
    except ImportError as exc:
        raise RuntimeError("zstd 命令不可用，且 Python zstandard 包未安装") from exc
    with archive.open("rb") as src, tar_path.open("wb") as dst:
        reader = zstd.ZstdDecompressor().stream_reader(src)
        try:
            shutil.copyfileobj(reader, dst)
        finally:
            reader.close()


def extract_one(task_id: str, tasks_dir: Path, force: bool) -> bool:
    task_dir = tasks_dir / task_id
    archive = task_dir / f"task-{task_id}.tar.zst"
    if not archive.exists():
        archive = task_dir / f"source-{task_id}.tar.zst"
    if not archive.exists():
        print(f"[skip] {task_id}: task-{task_id}.tar.zst or source-{task_id}.tar.zst not found")
        return False

    out_dir = task_dir / "extracted"
    if out_dir.exists():
        if force:
            shutil.rmtree(out_dir)
        else:
            print(f"[skip] {task_id}: {out_dir} exists (use --force to overwrite)")
            return True
    out_dir.mkdir(parents=True, exist_ok=True)

    # Decompress .tar.zst → temp .tar (Python's tarfile has no zstd support yet).
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as tmp:
        tar_path = Path(tmp.name)
    try:
        print(f"==> {task_id}: zstd -d {archive.name} ({archive.stat().st_size/1024/1024:.1f} MiB)")
        decompress_zst(archive, tar_path)

        skipped_symlinks = 0
        extracted_files = 0
        with tarfile.open(tar_path, mode="r:") as tf:
            for member in tf:
                # Skip symlinks/hardlinks — they encode absolute Linux paths.
                if member.issym() or member.islnk():
                    skipped_symlinks += 1
                    continue
                # Strip the leading "<ID>/" prefix so extracted/ contains the
                # per-model dirs and source/ directly.
                name = member.name
                if name == task_id:
                    continue
                prefix = f"{task_id}/"
                if name.startswith(prefix):
                    member.name = name[len(prefix):]
                # also tolerate "task-<ID>/" just in case some archives use it
                alt = f"task-{task_id}/"
                if name.startswith(alt):
                    member.name = name[len(alt):]
                alt = f"source-{task_id}/"
                if name.startswith(alt):
                    member.name = name[len(alt):]
                try:
                    tf.extract(member, path=out_dir, filter="data")
                    if member.isfile():
                        extracted_files += 1
                except OSError as e:
                    print(f"   [warn] could not extract {member.name}: {e}")
        print(f"   {extracted_files} file(s), {skipped_symlinks} symlink(s) skipped")
    finally:
        try:
            tar_path.unlink()
        except OSError:
            pass

    # Show top-level layout
    entries = sorted(p.name for p in out_dir.iterdir())
    print(f"   extracted/ top-level: {entries[:20]}{' ...' if len(entries)>20 else ''}")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("task_ids", nargs="+")
    p.add_argument("--tasks-dir", default=str(REPO_ROOT / "tasks"))
    p.add_argument("--force", action="store_true", help="overwrite existing extracted/")
    args = p.parse_args()

    tasks_dir = Path(args.tasks_dir)
    ok = True
    for tid in args.task_ids:
        if not extract_one(tid, tasks_dir, args.force):
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
