"""Lark/Feishu helpers — thin wrappers around the lark-cli binary.

All scripts in this skill go through this module so that profile, retries,
and JSON parsing live in one place. If lark-cli is ever replaced, only
this file needs to change.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LarkError(RuntimeError):
    pass


def _run(args: list[str], *, check: bool = True) -> str:
    res = subprocess.run(args, capture_output=True, text=True)
    if check and res.returncode != 0:
        raise LarkError(f"lark-cli failed ({res.returncode}): {' '.join(args)}\n{res.stderr.strip()}")
    return res.stdout


def lark(*cli_args: str, profile: str | None = None, check: bool = True) -> str:
    """Run lark-cli and return stdout."""
    cmd = ["lark-cli"]
    if profile:
        cmd += ["--profile", profile]
    cmd += list(cli_args)
    return _run(cmd, check=check)


def lark_json(*cli_args: str, profile: str | None = None) -> Any:
    """Run lark-cli and parse stdout as JSON."""
    out = lark(*cli_args, profile=profile)
    return json.loads(out)


# ---------- Wiki & spreadsheet discovery ----------

_WIKI_TOKEN_RE = re.compile(r"/wiki/([A-Za-z0-9]+)")


def extract_wiki_node_token(url: str) -> str:
    m = _WIKI_TOKEN_RE.search(url)
    if not m:
        raise ValueError(f"not a wiki URL: {url}")
    return m.group(1)


def resolve_wiki_to_sheet(wiki_url: str, profile: str) -> str:
    """Resolve a wiki/<token> URL to its underlying spreadsheet token."""
    node_token = extract_wiki_node_token(wiki_url)
    data = lark_json(
        "api", "GET", "/open-apis/wiki/v2/spaces/get_node",
        "--params", json.dumps({"token": node_token}),
        profile=profile,
    )
    node = data["data"]["node"]
    if node["obj_type"] != "sheet":
        raise LarkError(f"wiki node is not a sheet (got {node['obj_type']})")
    return node["obj_token"]


@dataclass
class SheetMeta:
    sheet_id: str
    title: str
    row_count: int
    column_count: int


def list_sheets(spreadsheet_token: str, profile: str) -> list[SheetMeta]:
    data = lark_json(
        "api", "GET",
        f"/open-apis/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query",
        profile=profile,
    )
    out = []
    for s in data["data"]["sheets"]:
        out.append(SheetMeta(
            sheet_id=s["sheet_id"],
            title=s["title"],
            row_count=s["grid_properties"]["row_count"],
            column_count=s["grid_properties"]["column_count"],
        ))
    return out


def find_sheet(spreadsheet_token: str, title: str, profile: str) -> SheetMeta:
    for s in list_sheets(spreadsheet_token, profile):
        if s.title == title:
            return s
    raise KeyError(f"no sheet titled {title!r} in {spreadsheet_token}")


# ---------- Range read/write ----------

def read_range(spreadsheet_token: str, sheet_id: str, a1: str, profile: str) -> list[list]:
    rng = f"{sheet_id}!{a1}"
    data = lark_json(
        "api", "GET",
        f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values/{rng}",
        profile=profile,
    )
    return data["data"]["valueRange"].get("values") or []


def write_cells(
    spreadsheet_token: str,
    sheet_id: str,
    a1: str,
    cells: list[list[dict]],
    profile: str,
    *,
    dry_run: bool = False,
    work_dir: Path | None = None,
) -> dict:
    """Write a 2D cell array via lark-cli sheets +cells-set.

    lark-cli requires the --cells JSON file to be inside CWD. We write the
    JSON to a temp file under work_dir (or cwd) and pass a relative path.
    """
    cwd = Path(work_dir) if work_dir else Path.cwd()
    tmp = cwd / ".lark-cells.json"
    tmp.write_text(json.dumps(cells, ensure_ascii=False))
    try:
        args = [
            "sheets", "+cells-set",
            "--spreadsheet-token", spreadsheet_token,
            "--sheet-id", sheet_id,
            "--range", a1,
            "--cells", f"@./{tmp.name}",
            "--allow-overwrite",
        ]
        if dry_run:
            args.append("--dry-run")
        out = subprocess.run(["lark-cli", "--profile", profile, *args], cwd=cwd, capture_output=True, text=True)
        if out.returncode != 0:
            raise LarkError(f"write_cells failed: {out.stderr}")
        return json.loads(out.stdout) if out.stdout.strip().startswith("{") else {"raw": out.stdout}
    finally:
        if tmp.exists():
            tmp.unlink()


def upload_image_to_cell(
    spreadsheet_token: str,
    sheet_id: str,
    cell: str,
    image_path: Path,
    profile: str,
    *,
    name: str | None = None,
) -> dict:
    """Embed a local image into a single cell via lark-cli sheets +cells-set-image."""
    args = [
        "sheets", "+cells-set-image",
        "--spreadsheet-token", spreadsheet_token,
        "--sheet-id", sheet_id,
        "--range", cell,
        "--image", str(image_path),
    ]
    if name:
        args += ["--name", name]
    data = lark_json(*args, profile=profile)
    if not data.get("ok", True):
        raise LarkError(f"upload failed: {data}")
    return data


# ---------- Drive media download ----------

def download_attachment(
    file_token: str,
    spreadsheet_token: str,
    out_path: Path,
    profile: str,
) -> Path:
    """Download a sheet-embedded attachment via /drive/v1/medias/{token}/download.

    lark-cli requires --output to be relative to CWD, so we cd into the parent
    dir and pass just the filename.
    """
    extra = json.dumps({"spreadsheetToken": spreadsheet_token})
    params = json.dumps({"extra": extra})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["lark-cli", "--profile", profile,
           "api", "GET", f"/open-apis/drive/v1/medias/{file_token}/download",
           "--params", params,
           "--output", out_path.name]
    res = subprocess.run(cmd, cwd=out_path.parent, capture_output=True, text=True)
    if res.returncode != 0:
        raise LarkError(f"download failed: {res.stderr.strip()}")
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        raise LarkError(f"download non-JSON reply: {res.stdout[:200]}")
    if "saved_path" not in data:
        raise LarkError(f"download did not save path: {data}")
    return Path(data["saved_path"])
