#!/usr/bin/env python3
"""Try ClickVisual UI startup on u03l and render raw logs as evidence."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[3]


def safe_tag(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name.strip())


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout)


def run_checked(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    res = run(cmd, cwd=cwd, timeout=timeout)
    if res.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{res.stdout}\n{res.stderr}")
    return res


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def make_ui_tar(ui_dir: Path, tar_path: Path) -> None:
    if tar_path.exists():
        tar_path.unlink()
    skip_dirs = {"node_modules", "dist", ".git"}
    with tarfile.open(tar_path, "w:gz") as tf:
        for p in ui_dir.rglob("*"):
            rel = p.relative_to(ui_dir)
            if any(part in skip_dirs for part in rel.parts):
                continue
            tf.add(p, arcname=Path("ui") / rel)


def font(size: int) -> ImageFont.ImageFont:
    for name in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simsun.ttc", "consola.ttf", "C:/Windows/Fonts/consola.ttf", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_log(text: str, out_path: Path) -> None:
    text = strip_ansi(text)
    img = Image.new("RGB", (1500, 950), "#0d1117")
    draw = ImageDraw.Draw(img)
    fnt = font(20)
    x, y = 22, 22
    line_h = 28
    for raw in text.splitlines()[-80:]:
        chunks = [raw[i:i + 125] for i in range(0, len(raw), 125)] or [""]
        for chunk in chunks:
            draw.text((x, y), chunk, fill="#e6edf3", font=fnt)
            y += line_h
            if y + line_h > img.height:
                break
        if y + line_h > img.height:
            break
    bg = Image.new("RGB", img.size, "#0d1117")
    bbox = ImageChops.difference(img, bg).getbbox()
    if bbox:
        img = img.crop((0, 0, img.width, min(img.height, bbox[3] + 24)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def prepare_remote(task_id: str, code: str, ui_dir: Path, logs_dir: Path) -> str:
    tar_path = logs_dir / f"{code}-ui-src.tgz"
    make_ui_tar(ui_dir, tar_path)
    remote_dir = f"/tmp/qc_{task_id}_{code}_ui_recheck"
    cleanup = (
        f"docker run --rm -v /tmp:/host_tmp node:18 "
        f"bash -lc 'rm -rf /host_tmp/qc_{task_id}_{code}_ui_recheck' >/dev/null 2>&1 || true; "
        f"mkdir -p {remote_dir}"
    )
    run_checked(["ssh", "u03l", cleanup], timeout=120)
    run_checked(["scp", str(tar_path), f"u03l:{remote_dir}/ui-src.tgz"], timeout=120)
    template = f"/tmp/qc_{task_id}_1PFMT_ui/ui/node_modules"
    cmd = (
        f"cd {remote_dir} && tar -xzf ui-src.tgz && "
        f"if [ -d {template} ]; then cp -a {template} ui/node_modules; fi && "
        "if [ ! -d ui/node_modules/.bin ]; then "
        "docker run --rm -e HTTP_PROXY= -e HTTPS_PROXY= -e http_proxy= -e https_proxy= "
        "-e ALL_PROXY= -e all_proxy= -v \"$PWD/ui:/work\" -w /work node:18 "
        "bash -lc 'npm config delete proxy || true; npm config delete https-proxy || true; "
        "npx -y npm@9.9.4 install --legacy-peer-deps --no-audit --no-fund'; fi"
    )
    run_checked(["ssh", "u03l", cmd], timeout=900)
    return remote_dir


def try_start(task_id: str, col: str, code: str, remote_dir: str, port: int, seconds: int, logs_dir: Path, out_dir: Path) -> None:
    tag = safe_tag(col)
    cname = f"qc_{task_id.lower()}_{code.lower()}_ui"
    run(["ssh", "u03l", f"docker rm -f {cname} >/dev/null 2>&1 || true"], timeout=30)
    start_cmd = (
        f"docker run -d --name {cname} --network host "
        f"-e HTTP_PROXY= -e HTTPS_PROXY= -e http_proxy= -e https_proxy= -e ALL_PROXY= -e all_proxy= "
        f"-e BROWSER=none -e CI=1 -e HOST=127.0.0.1 -e PORT={port} -e UMI_UI=none -e UMI_ENV=dev -e MFSU=false "
        f"-v {remote_dir}/ui:/work -w /work node:18 bash -lc 'npm run start:no-ui'"
    )
    res = run_checked(["ssh", "u03l", start_cmd], timeout=60)
    time.sleep(seconds)
    logs = run(["ssh", "u03l", f"docker logs {cname} 2>&1 || true"], timeout=60).stdout
    run(["ssh", "u03l", f"docker rm -f {cname} >/dev/null 2>&1 || true"], timeout=30)
    log_path = logs_dir / f"{code}-u03l-ui-dev.log"
    log_path.write_text(logs, encoding="utf-8", errors="replace")
    render_log(logs, out_dir / f"{tag}_02_frontend_u03l_start_timeout.png")


def main() -> int:
    task_id = sys.argv[1] if len(sys.argv) > 1 else "9AP9AS"
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    task_dir = REPO_ROOT / "tasks" / task_id
    out_dir = REPO_ROOT / "delivery" / task_id / "screenshots"
    logs_dir = task_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    model_map = json.loads((task_dir / "model_map.json").read_text(encoding="utf-8"))
    port = 5531
    for col in model_map["sheet_columns"]:
        code = model_map["models"][col]["code"]
        ui_dir = task_dir / "extracted" / code / "ui"
        remote_dir = prepare_remote(task_id, code, ui_dir, logs_dir)
        try_start(task_id, col, code, remote_dir, port, seconds, logs_dir, out_dir)
        port += 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
