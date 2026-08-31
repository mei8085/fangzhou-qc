#!/usr/bin/env python3
"""Inspect first-round task uploads and expose uploaded prompt material.

The Ark task page calls these files ``attachments`` under the first Prompt's
"上传产物" section. They are separate from each model's Workspace/download
list. The collector downloads them first, then invokes this script before the
prompt-cheat gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".mdown",
    ".mkd",
    ".txt",
    ".rst",
    ".adoc",
    ".asciidoc",
    ".prompt",
    ".instructions",
}
ARCHIVE_EXTENSIONS = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
SKIP_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "__macosx",
}
MAX_ARCHIVE_ENTRIES = int(os.environ.get("QC_UPLOAD_MAX_ARCHIVE_ENTRIES", "100000"))
MAX_ARCHIVE_BYTES = int(os.environ.get("QC_UPLOAD_MAX_ARCHIVE_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_TEXT_FILES = int(os.environ.get("QC_UPLOAD_MAX_TEXT_FILES", "1000"))
MAX_TEXT_FILE_BYTES = int(os.environ.get("QC_UPLOAD_MAX_TEXT_FILE_BYTES", str(5 * 1024 * 1024)))
MAX_TEXT_TOTAL_BYTES = int(os.environ.get("QC_UPLOAD_MAX_TEXT_TOTAL_BYTES", str(50 * 1024 * 1024)))
MAX_NESTED_DEPTH = int(os.environ.get("QC_UPLOAD_MAX_NESTED_DEPTH", "3"))


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def portable_path(name: str) -> PurePosixPath:
    normalized = str(name).replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe archive path: {name!r}")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"unsafe archive drive path: {name!r}")
    return path


def is_skipped(path: PurePosixPath) -> bool:
    return any(part.lower() in SKIP_PARTS or part.startswith("._") for part in path.parts)


def is_text_candidate(path: PurePosixPath) -> bool:
    return path.suffix.lower() in TEXT_EXTENSIONS and not is_skipped(path)


def is_archive_name(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def decode_text(raw: bytes, source: str) -> tuple[str, str]:
    if b"\x00" in raw[:8192]:
        raise ValueError(f"text candidate contains NUL bytes: {source}")
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError(f"cannot decode text candidate as UTF-8/GB18030: {source}")


def material(source_file: str, archive_path: str, raw: bytes) -> dict[str, Any]:
    source = f"{source_file}!/{archive_path}" if archive_path else source_file
    if len(raw) > MAX_TEXT_FILE_BYTES:
        raise ValueError(
            f"text candidate exceeds {MAX_TEXT_FILE_BYTES} bytes and needs manual review: {source}"
        )
    text, encoding = decode_text(raw, source)
    return {
        "source_file": source_file,
        "archive_path": archive_path,
        "source": source,
        "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding,
        "text": text.replace("\r\n", "\n").replace("\r", "\n"),
    }


def check_material_limits(materials: list[dict[str, Any]]) -> None:
    if len(materials) > MAX_TEXT_FILES:
        raise ValueError(f"more than {MAX_TEXT_FILES} uploaded text files; manual review required")
    total = sum(int(item["size_bytes"]) for item in materials)
    if total > MAX_TEXT_TOTAL_BYTES:
        raise ValueError(
            f"uploaded text totals {total} bytes, over {MAX_TEXT_TOTAL_BYTES}; manual review required"
        )


def deduplicate_materials(materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one scan copy per content hash while retaining every source path."""
    unique: dict[str, dict[str, Any]] = {}
    for item in materials:
        digest = str(item["sha256"])
        source = str(item["source"])
        if digest not in unique:
            unique[digest] = {**item, "occurrence_count": 1, "occurrences": [source]}
        else:
            unique[digest]["occurrence_count"] += 1
            unique[digest]["occurrences"].append(source)
    return list(unique.values())


def inspect_zip(path: Path, source_file: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    materials: list[dict[str, Any]] = []
    skipped_text: list[str] = []
    nested_archives: list[str] = []
    scanned_entries = 0
    expanded_bytes = 0

    def scan(archive: zipfile.ZipFile, prefix: str = "", depth: int = 0) -> None:
        nonlocal scanned_entries, expanded_bytes
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise ValueError(f"archive has {len(entries)} entries; limit is {MAX_ARCHIVE_ENTRIES}: {source_file}")
        scanned_entries += len(entries)
        expanded_bytes += sum(info.file_size for info in entries if not info.is_dir())
        if scanned_entries > MAX_ARCHIVE_ENTRIES:
            raise ValueError(f"nested archives exceed {MAX_ARCHIVE_ENTRIES} entries: {source_file}")
        if expanded_bytes > MAX_ARCHIVE_BYTES:
            raise ValueError(f"archives expand to {expanded_bytes} bytes; manual review required: {source_file}")
        for info in entries:
            if info.is_dir():
                continue
            archive_path = portable_path(info.filename)
            display_path = f"{prefix}!/{info.filename}" if prefix else info.filename
            if info.flag_bits & 0x1:
                raise ValueError(f"encrypted archive entry needs manual review: {source_file}!/{display_path}")
            if is_archive_name(info.filename) and not is_skipped(archive_path):
                nested_archives.append(display_path)
                if depth >= MAX_NESTED_DEPTH:
                    raise ValueError(
                        f"nested archive depth exceeds {MAX_NESTED_DEPTH}: {source_file}!/{display_path}"
                    )
                if not info.filename.lower().endswith(".zip"):
                    raise ValueError(f"nested non-ZIP archive needs manual review: {source_file}!/{display_path}")
                with archive.open(info) as stream:
                    nested_raw = stream.read()
                with zipfile.ZipFile(BytesIO(nested_raw)) as nested:
                    scan(nested, display_path, depth + 1)
                continue
            if archive_path.suffix.lower() in TEXT_EXTENSIONS and is_skipped(archive_path):
                skipped_text.append(display_path)
                continue
            if not is_text_candidate(archive_path):
                continue
            with archive.open(info) as stream:
                materials.append(material(source_file, display_path, stream.read()))
            check_material_limits(materials)

    with zipfile.ZipFile(path) as archive:
        scan(archive)
    return {
        "kind": "zip",
        "entry_count": scanned_entries,
        "expanded_size_bytes": expanded_bytes,
        "nested_archive_count": len(nested_archives),
        "nested_archive_sample": nested_archives[:20],
        "text_material_count": len(materials),
        "skipped_dependency_text_count": len(skipped_text),
        "skipped_dependency_text_sample": skipped_text[:20],
    }, materials


def inspect_tar(path: Path, source_file: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    materials: list[dict[str, Any]] = []
    skipped_text: list[str] = []
    nested_archives: list[str] = []
    with tarfile.open(path, mode="r:*") as archive:
        entries = archive.getmembers()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise ValueError(f"archive has {len(entries)} entries; limit is {MAX_ARCHIVE_ENTRIES}: {source_file}")
        regular = [entry for entry in entries if entry.isfile()]
        total_bytes = sum(entry.size for entry in regular)
        if total_bytes > MAX_ARCHIVE_BYTES:
            raise ValueError(f"archive expands to {total_bytes} bytes; manual review required: {source_file}")
        for entry in regular:
            archive_path = portable_path(entry.name)
            if is_archive_name(entry.name) and not is_skipped(archive_path):
                nested_archives.append(entry.name)
            if archive_path.suffix.lower() in TEXT_EXTENSIONS and is_skipped(archive_path):
                skipped_text.append(entry.name)
                continue
            if not is_text_candidate(archive_path):
                continue
            stream = archive.extractfile(entry)
            if stream is None:
                raise ValueError(f"cannot read archive entry: {source_file}!/{entry.name}")
            materials.append(material(source_file, entry.name, stream.read()))
            check_material_limits(materials)
    if nested_archives:
        sample = ", ".join(nested_archives[:5])
        raise ValueError(f"nested upload archive needs manual review ({sample}): {source_file}")
    return {
        "kind": "tar",
        "entry_count": len(entries),
        "expanded_size_bytes": total_bytes,
        "text_material_count": len(materials),
        "skipped_dependency_text_count": len(skipped_text),
        "skipped_dependency_text_sample": skipped_text[:20],
    }, materials


def inspect_file(path: Path, source_file: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lower = source_file.lower()
    if lower.endswith(".zip"):
        return inspect_zip(path, source_file)
    if any(lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS if ext != ".zip"):
        return inspect_tar(path, source_file)
    portable = portable_path(source_file)
    if is_text_candidate(portable):
        item = material(source_file, "", path.read_bytes())
        return {"kind": "text", "text_material_count": 1}, [item]
    return {"kind": "binary", "text_material_count": 0, "manual_review_required": True}, []


def inspect(task_dir: Path) -> dict[str, Any]:
    manifest_path = task_dir / "task_uploads.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing {manifest_path}; rerun the Ark collector")
    manifest = read_json(manifest_path)
    if manifest.get("status") not in {"downloaded", "complete"}:
        raise ValueError(f"task upload manifest is not downloaded: status={manifest.get('status')!r}")

    report_items: list[dict[str, Any]] = []
    materials: list[dict[str, Any]] = []
    for item in manifest.get("items") or []:
        rel_path = str(item.get("local_path") or "")
        local_path = (task_dir / Path(rel_path)).resolve()
        try:
            local_path.relative_to(task_dir)
        except ValueError as exc:
            raise ValueError(f"task upload path escapes task directory: {rel_path}") from exc
        if not local_path.is_file():
            raise FileNotFoundError(f"downloaded task upload is missing: {local_path}")
        expected_hash = str(item.get("sha256") or "")
        actual_hash = hashlib.sha256(local_path.read_bytes()).hexdigest()
        if expected_hash and actual_hash != expected_hash:
            raise ValueError(f"task upload checksum changed: {local_path}")
        details, found = inspect_file(local_path, str(item.get("file_name") or local_path.name))
        report_items.append({
            "index": item.get("index"),
            "file_name": item.get("file_name"),
            "local_path": rel_path.replace("\\", "/"),
            **details,
        })
        materials.extend(found)
        check_material_limits(materials)

    unique_materials = deduplicate_materials(materials)
    prompt_materials_path = task_dir / "task_prompt_materials.json"
    write_json(prompt_materials_path, {
        "schema_version": 1,
        "source": "first_round_prompt_uploads",
        "material_count": len(unique_materials),
        "text_material_occurrence_count": len(materials),
        "materials": unique_materials,
        "generated_at": utc_now(),
    })
    report = {
        "schema_version": 1,
        "source": "CaseBffV1CrowdtestTaskGet.attachments",
        "source_label": "首轮 Prompt / 上传产物",
        "reported_count": manifest.get("reported_count", len(report_items)),
        "inspected_count": len(report_items),
        "text_material_count": len(materials),
        "unique_text_material_count": len(unique_materials),
        "items": report_items,
        "prompt_materials_path": prompt_materials_path.name,
        "generated_at": utc_now(),
    }
    write_json(task_dir / "task_uploads_inspection.json", report)
    manifest["status"] = "complete"
    manifest["inspection_path"] = "task_uploads_inspection.json"
    manifest["prompt_materials_path"] = prompt_materials_path.name
    manifest["text_material_count"] = len(materials)
    manifest["unique_text_material_count"] = len(unique_materials)
    manifest["completed_at"] = utc_now()
    manifest.pop("error", None)
    write_json(manifest_path, manifest)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", required=True, type=Path, help="tasks/<ID>/ark_g1 directory")
    args = parser.parse_args()
    task_dir = args.task_dir.resolve()
    manifest_path = task_dir / "task_uploads.json"
    try:
        report = inspect(task_dir)
    except Exception as exc:
        if manifest_path.exists():
            try:
                manifest = read_json(manifest_path)
                manifest["status"] = "inspection_failed"
                manifest["error"] = str(exc)
                manifest["failed_at"] = utc_now()
                write_json(manifest_path, manifest)
            except Exception:
                pass
        print(f"  [err] task upload inspection failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"==> task uploads inspected: {report['inspected_count']} file(s), "
        f"{report['text_material_count']} text path(s), "
        f"{report['unique_text_material_count']} unique text material(s)"
    )
    print(f"  wrote {task_dir / 'task_uploads_inspection.json'}")
    print(f"  wrote {task_dir / 'task_prompt_materials.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
