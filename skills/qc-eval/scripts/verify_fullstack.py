#!/usr/bin/env python3
"""Orchestrator for full-stack QC verify — period-agnostic.

Triggered when the agent judges a task needs a real backend to verify (see
SKILL.md 5f decision rules). Detection is entirely via file presence, not by
期数: `qc_cells.json[sheet].verifiable == "是"` + a hand-authored
`tasks/<TASK_ID>/verify_routes.json`. Any of 28 / 29 / later 期 can use this.

Steps:

  1. checks u03l is reachable (stops otherwise)
  2. rsyncs each extracted model to u03l
  3. brings up the docker stack (per-task project name)
  4. opens SSH tunnels for postgres + redis
  5. for each of 4 models:
       venv → env.local → migrate → uvicorn → vite dev → Playwright routes
  6. tears down local uvicorn/vite, then closes tunnels, then compose down

--dry-write   PNGs land in tmp/verify_smoke/<TASK_ID>/ instead of delivery/,
              qc_cells.json is not touched. Use for plumbing tests.
--keep-alive  Skip teardown; print URLs for manual browser drive.
--only CODE   Only run for a single model.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO_ROOT = HERE.parent.parent.parent

import tunnel                                # noqa: E402
import u03l                                   # noqa: E402
from lib import env_render, port_alloc, remote_config as rc, venv_manager  # noqa: E402


class VerifyBlocked(RuntimeError):
    """Non-recoverable — caller should stop the whole emit."""


def _log(msg: str) -> None:
    print(f"  [verify] {msg}", flush=True)


def _wait_for_http(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if 200 <= r.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _wait_for_vite(proc: subprocess.Popen, timeout: float = 60.0) -> Optional[str]:
    import re
    strip_ansi = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
    marker = re.compile(r"Local:\s+(https?://[^\s]+)")
    deadline = time.time() + timeout
    for line in proc.stdout:                 # type: ignore[union-attr]
        if time.time() > deadline:
            return None
        clean = strip_ansi.sub("", line)
        m = marker.search(clean)
        if m:
            return m.group(1).rstrip("/")
    return None


def _load_task(task_id: str) -> tuple[dict, dict]:
    cells = REPO_ROOT / "tasks" / task_id / "qc_cells.json"
    if not cells.exists():
        raise VerifyBlocked(f"missing tasks/{task_id}/qc_cells.json")
    qc = json.loads(cells.read_text(encoding="utf-8"))
    mm = REPO_ROOT / "tasks" / task_id / "model_map.json"
    if not mm.exists():
        raise VerifyBlocked(f"missing tasks/{task_id}/model_map.json")
    return qc, json.loads(mm.read_text(encoding="utf-8"))


def _load_routes(task_id: str) -> Optional[dict]:
    p = REPO_ROOT / "tasks" / task_id / "verify_routes.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _screenshot_dir(task_id: str, dry_write: bool) -> Path:
    if dry_write:
        d = REPO_ROOT / "tmp" / "verify_smoke" / task_id
    else:
        d = REPO_ROOT / "delivery" / task_id / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ProcHolder:
    """Track background processes so we always tear them down."""
    def __init__(self) -> None:
        self.procs: list[tuple[str, subprocess.Popen]] = []

    def add(self, label: str, p: subprocess.Popen) -> None:
        self.procs.append((label, p))

    def kill_all(self) -> None:
        # LIFO: kill vite before uvicorn, uvicorn before pip etc.
        for label, p in reversed(self.procs):
            if p.poll() is None:
                try:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                                       capture_output=True)
                    else:
                        p.terminate()
                        try:
                            p.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            p.kill()
                except Exception:
                    pass
        self.procs.clear()


def _start_uvicorn(model_dir: Path, python_bin: Path, env: dict, port: int,
                   log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lf = log_path.open("wb")
    return subprocess.Popen(
        [str(python_bin), "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        cwd=str(model_dir), env=env,
        stdout=lf, stderr=subprocess.STDOUT,
    )


def _start_vite(frontend_dir: Path, port: int, log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", str(port), "--strictPort"],
        cwd=str(frontend_dir),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, shell=(os.name == "nt"),
    )


def _run_migrations(model_dir: Path, python_bin: Path, env: dict, log_path: Path) -> str:
    """Try alembic upgrade head; if no alembic, try Base.metadata.create_all. Returns status text."""
    alembic_dir = model_dir / "alembic"
    versions = list((alembic_dir / "versions").glob("*.py")) if alembic_dir.exists() else []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if versions:
        r = subprocess.run(
            [str(python_bin), "-m", "alembic", "upgrade", "head"],
            cwd=str(model_dir), env=env, capture_output=True, text=True,
        )
        log_path.write_text((r.stdout or "") + "\n" + (r.stderr or ""), encoding="utf-8")
        return "alembic-ok" if r.returncode == 0 else "alembic-fail"
    # fallback: import Base and create_all synchronously
    boot = (
        "import asyncio\n"
        "from app.core.database import Base, engine\n"
        "async def go():\n"
        "    async with engine.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n"
        "asyncio.run(go())\n"
        "print('bootstrap-ok')\n"
    )
    r = subprocess.run(
        [str(python_bin), "-c", boot],
        cwd=str(model_dir), env=env, capture_output=True, text=True,
    )
    log_path.write_text((r.stdout or "") + "\n" + (r.stderr or ""), encoding="utf-8")
    return "bootstrap-ok" if r.returncode == 0 else "bootstrap-fail"


def verify_one(task_id: str, code: str, code_index: int, tunnel_state: dict,
               routes: dict, dry_write: bool, procs: ProcHolder,
               uvicorn_port: int, vite_port: int) -> dict:
    task_dir = REPO_ROOT / "tasks" / task_id
    model_dir = task_dir / "extracted" / code
    logs_dir = task_dir / "logs"
    result = {"code": code, "steps": {}}

    _log(f"{code}  ==> venv")
    venv_dir = task_dir / f"venv_{code}"
    try:
        python_bin = venv_manager.ensure(venv_dir, model_dir / "requirements.txt")
    except subprocess.CalledProcessError as e:
        result["error"] = f"venv/pip failed: {e.stderr or e.stdout}"[:800]
        return result
    result["steps"]["venv"] = "ok"

    _log(f"{code}  ==> env.local")
    env_render.render(model_dir, task_id, code, code_index, tunnel_state, uvicorn_port)
    env = os.environ.copy()
    env["APP_ENV_FILE"] = str(model_dir / ".env.local")
    # models with pydantic-settings read .env by default; alias to .env.local
    env["ENV_FILE"] = str(model_dir / ".env.local")
    # inject the vars directly too, in case model ignores .env.local
    for line in (model_dir / ".env.local").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    result["steps"]["env"] = "ok"

    _log(f"{code}  ==> migrate")
    mig = _run_migrations(model_dir, python_bin, env,
                          logs_dir / f"{code}_migrate.log")
    result["steps"]["migrate"] = mig
    if mig.endswith("-fail"):
        _log(f"  migrate failed; see {logs_dir}/{code}_migrate.log — continuing to try uvicorn anyway")

    _log(f"{code}  ==> uvicorn :{uvicorn_port}")
    u = _start_uvicorn(model_dir, python_bin, env, uvicorn_port,
                       logs_dir / f"{code}_uvicorn.log")
    procs.add(f"uvicorn:{code}", u)
    if not _wait_for_http(f"http://127.0.0.1:{uvicorn_port}/docs", timeout=30):
        result["steps"]["uvicorn"] = "no-response"
        return result
    result["steps"]["uvicorn"] = "ready"

    frontend = model_dir / "frontend"
    if not frontend.exists():
        result["steps"]["vite"] = "no-frontend-dir"
        return result

    _log(f"{code}  ==> vite dev :{vite_port}")
    v = _start_vite(frontend, vite_port, logs_dir / f"{code}_vite.log")
    procs.add(f"vite:{code}", v)
    url = _wait_for_vite(v, timeout=90)
    if not url:
        result["steps"]["vite"] = "no-url"
        return result
    result["steps"]["vite"] = f"ready {url}"

    _log(f"{code}  ==> screenshots")
    out_dir = _screenshot_dir(task_id, dry_write)
    routes_path = task_dir / "verify_routes.json"
    js = HERE / "screenshot_fullstack_verify.js"
    if not js.exists():
        result["steps"]["screenshot"] = "js-missing"
        return result
    r = subprocess.run(
        ["node", str(js),
         "--task", task_id, "--code", code,
         "--vue-url", url, "--api-port", str(uvicorn_port),
         "--routes", str(routes_path), "--out-dir", str(out_dir)],
        capture_output=True, text=True,
    )
    result["steps"]["screenshot"] = "ok" if r.returncode == 0 else f"fail: {r.stderr[:200]}"

    # stop vite before uvicorn (proxy noise otherwise)
    procs.kill_all()
    return result


def _cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="verify_fullstack.py")
    p.add_argument("task_id")
    p.add_argument("--only", help="single CODE")
    p.add_argument("--dry-write", action="store_true",
                   help="write PNGs to tmp/verify_smoke/ instead of delivery/")
    p.add_argument("--keep-alive", action="store_true",
                   help="don't teardown; print URLs for manual browsing")
    args = p.parse_args(argv)
    task_id = args.task_id

    try:
        u03l.check_host()
    except u03l.HostUnreachable as e:
        print(f"[stop] {e}", file=sys.stderr)
        return 2

    qc, mm = _load_task(task_id)
    routes = _load_routes(task_id)
    if routes is None:
        print(f"[stop] tasks/{task_id}/verify_routes.json 缺失；无路由无法自动截图。",
              file=sys.stderr)
        return 4

    # deterministic code order
    all_codes = sorted(mm["models"].keys(), key=lambda k: mm["models"][k]["code"])
    codes = [mm["models"][k]["code"] for k in all_codes]
    if args.only:
        codes = [c for c in codes if c == args.only]
        if not codes:
            print(f"[stop] --only {args.only} not in model_map", file=sys.stderr)
            return 4

    _log(f"sync {len(codes)} model(s) to u03l …")
    u03l.sync_code(task_id, codes)

    _log(f"docker compose up on u03l …")
    ports = u03l.ensure_up(task_id, codes)
    _log(f"remote ports: postgres={ports['postgres_port']} redis={ports['redis_port']}")

    tstate = tunnel.open(task_id, ports["postgres_port"], ports["redis_port"])
    _log(f"tunnels: postgres={tstate['postgres']['local']} redis={tstate['redis']['local']}")

    procs = ProcHolder()

    def _cleanup() -> None:
        if args.keep_alive:
            return
        procs.kill_all()
        try:
            tunnel.close(task_id)
        except Exception:
            pass
        try:
            u03l.down(task_id)
        except Exception:
            pass

    atexit.register(_cleanup)

    def _sigint(_sig, _frm):  # type: ignore[no-untyped-def]
        _cleanup()
        sys.exit(130)
    signal.signal(signal.SIGINT, _sigint)

    base = port_alloc.base_for(task_id)
    results = []
    for i, code in enumerate(codes):
        code_index = i
        uvicorn_port = port_alloc.pick_free(base["uvicorn"] + i)
        vite_port = port_alloc.pick_free(base["vite"] + i)
        try:
            r = verify_one(task_id, code, code_index, tstate, routes,
                           args.dry_write, procs, uvicorn_port, vite_port)
        except Exception as e:
            r = {"code": code, "error": str(e)}
        results.append(r)

    summary_path = (REPO_ROOT / "tasks" / task_id / "logs" / "_verify_summary.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False),
                            encoding="utf-8")
    _log(f"summary → {summary_path.relative_to(REPO_ROOT)}")
    for r in results:
        _log(f"  {r.get('code')}: {r.get('steps', r.get('error', '?'))}")

    if args.keep_alive:
        _log("--keep-alive: 保留 stack + tunnels，手动排障后运行 tunnel.py close + u03l.py down")
        return 0

    return 0 if all(("error" not in r) and (r["steps"].get("screenshot") == "ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
