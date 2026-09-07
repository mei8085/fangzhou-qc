#!/usr/bin/env python3
"""Remote docker driver for the qc-eval fullstack verify pipeline.

When to use this host is defined in SKILL.md「复测启动与截图」; Vue-only and CLI
tasks must not call this driver.

u03l is the Ubuntu workstation hosting a per-task docker compose stack:
  * postgres:15-alpine  — one instance, one DB per model
  * redis:7-alpine       — one instance, broker db 0..3 + result db 4..7
  * celery-worker-<CODE> ×N   — mounts extracted model code
  * celery-beat-<CODE>   ×N   — mounts extracted model code

Never touches u03l unless u03l is reachable. Failures fall into three buckets:
  * host off       → exit 2 with an actionable message; caller MUST stop.
  * stack partial  → down + up once, else exit 3.
  * transient      → retry with backoff.

CLI
    python u03l.py check-host
    python u03l.py ensure-up TASK_ID CODE [CODE ...]
    python u03l.py sync-code TASK_ID
    python u03l.py down TASK_ID
    python u03l.py status TASK_ID
    python u03l.py list-tasks
"""
from __future__ import annotations

import argparse
import io
import json
import shlex
import subprocess
import sys
import time
import tarfile
from pathlib import Path

from lib import remote_config as rc

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
REPO_ROOT = SKILL_DIR.parent.parent

sys.path.insert(0, str(HERE))  # so `from lib import ...` works when invoked directly


# ---------- exceptions ----------

class HostUnreachable(RuntimeError):
    pass


class ComposeUpFailed(RuntimeError):
    pass


# ---------- ssh helpers ----------

_SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=5",
    "-o", "StrictHostKeyChecking=accept-new",
]


def _ssh(cmd: str, *, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess:
    """Run `cmd` on u03l via SSH; returns CompletedProcess."""
    full = ["ssh", *_SSH_OPTS, rc.SSH_HOST, cmd]
    return subprocess.run(full, capture_output=True, text=True, timeout=timeout, check=check)


def _scp_to_remote(local_path: Path, remote_path: str) -> None:
    subprocess.run(
        ["scp", *_SSH_OPTS, str(local_path), f"{rc.SSH_HOST}:{remote_path}"],
        check=True, capture_output=True, text=True,
    )


def _write_lf(path: Path, content: str) -> None:
    """Write file with UNIX line endings — required because these files run on u03l."""
    with open(path, "wb") as f:
        f.write(content.replace("\r\n", "\n").encode("utf-8"))


def _rsync_dir(local_dir: Path, remote_dir: str) -> None:
    # trailing slash matters: copy CONTENTS of local_dir into remote_dir
    rsync_cmd = [
        "rsync", "-az", "--delete",
        "--exclude=node_modules/", "--exclude=__pycache__/",
        "--exclude=.venv/", "--exclude=venv/", "--exclude=.git/",
        "-e", "ssh " + " ".join(_SSH_OPTS),
        f"{local_dir.as_posix().rstrip('/')}/",
        f"{rc.SSH_HOST}:{remote_dir}/",
    ]
    try:
        subprocess.run(rsync_cmd, check=True, capture_output=True, text=True)
        return
    except FileNotFoundError:
        pass

    # Fallback for Windows hosts without rsync: recreate the remote dir and
    # stream a tar archive over ssh.
    _ssh(f"rm -rf {shlex.quote(str(remote_dir))} && mkdir -p {shlex.quote(str(remote_dir))}",
         timeout=60, check=True)
    proc = subprocess.Popen(
        ["ssh", *_SSH_OPTS, rc.SSH_HOST, f"tar -x -C {shlex.quote(str(remote_dir))}"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
    )
    try:
        assert proc.stdin is not None
        with tarfile.open(fileobj=proc.stdin, mode="w|") as tf:
            for item in sorted(local_dir.rglob("*")):
                arcname = item.relative_to(local_dir)
                tf.add(item, arcname=str(arcname))
        proc.stdin.close()
        stdout, stderr = proc.communicate(timeout=120)
    except Exception:
        proc.kill()
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode or 1, proc.args, stdout, stderr)


# ---------- host lifecycle ----------

def check_host() -> None:
    """Raise HostUnreachable with actionable text if u03l is off/unreachable."""
    try:
        r = subprocess.run(
            ["ssh", *_SSH_OPTS, rc.SSH_HOST, "true"],
            capture_output=True, text=True, timeout=8,
        )
    except subprocess.TimeoutExpired:
        raise HostUnreachable(
            f"u03l 探活超时。请开机（或检查网络）后重跑。SSH host = {rc.SSH_HOST}"
        )
    if r.returncode != 0:
        raise HostUnreachable(
            f"u03l 不可达（ssh 返回 {r.returncode}）：{r.stderr.strip() or '(no stderr)'}\n"
            f"请开机或修 ~/.ssh/config 里 Host {rc.SSH_HOST} 后重跑。"
        )


# ---------- compose rendering ----------

def _render_compose(task_id: str, codes: list[str]) -> str:
    """Generate the full docker-compose YAML for a task's stack.

    Only postgres/redis are stable; celery-worker-<CODE> + celery-beat-<CODE>
    are fanned out per model.
    """
    proj = rc.project_name(task_id)
    remote_dir = rc.remote_task_dir(task_id)

    # postgres init: create one DB per model
    db_creates = "\n".join(
        '    CREATE DATABASE "' + rc.db_name(task_id, c).replace('"', '""') + '";'
        for c in codes
    )
    init_sql = (
        f"#!/bin/sh\nset -e\n"
        f"psql -v ON_ERROR_STOP=1 --username \"$POSTGRES_USER\" --dbname postgres <<EOSQL\n"
        f"{db_creates}\nEOSQL\n"
    )

    lines: list[str] = [
        f"# Auto-rendered by u03l.py for {task_id}. Do NOT hand-edit.",
        f"name: {proj}",
        "services:",
        # postgres
        "  postgres:",
        "    image: postgres:15-alpine",
        "    restart: unless-stopped",
        "    environment:",
        f"      POSTGRES_USER: {rc.PG_USER}",
        f"      POSTGRES_PASSWORD: {rc.PG_PASSWORD}",
        f"      POSTGRES_DB: postgres",
        "    ports:",
        "      - \"5432\"",          # dynamic host port
        "    volumes:",
        "      - pg_data:/var/lib/postgresql/data",
        "      - ./init-db.sh:/docker-entrypoint-initdb.d/init-db.sh:ro",
        "    healthcheck:",
        f"      test: [\"CMD-SHELL\", \"pg_isready -U {rc.PG_USER}\"]",
        "      interval: 3s",
        "      timeout: 3s",
        "      retries: 20",
        # redis
        "  redis:",
        "    image: redis:7-alpine",
        "    restart: unless-stopped",
        "    command: [\"redis-server\", \"--maxmemory\", \"256mb\", \"--maxmemory-policy\", \"allkeys-lru\"]",
        "    ports:",
        "      - \"6379\"",
        "    healthcheck:",
        "      test: [\"CMD\", \"redis-cli\", \"ping\"]",
        "      interval: 3s",
        "      timeout: 3s",
        "      retries: 20",
    ]

    # celery workers + beats
    for i, code in enumerate(codes):
        broker = f"redis://redis:6379/{rc.broker_db_index(i)}"
        result = f"redis://redis:6379/{rc.result_db_index(i)}"
        db_url = f"postgresql+asyncpg://{rc.PG_USER}:{rc.PG_PASSWORD}@postgres:5432/{rc.db_name(task_id, code)}"
        env_block = [
            f"      DATABASE_URL: {db_url}",
            f"      REDIS_URL: redis://redis:6379/{rc.broker_db_index(i)}",
            f"      CELERY_BROKER_URL: {broker}",
            f"      CELERY_RESULT_BACKEND: {result}",
            f"      SECRET_KEY: qc-eval-dev-not-secret",
        ]
        common = [
            "    image: python:3.11-slim",
            "    working_dir: /app",
            "    volumes:",
            f"      - {remote_dir}/{code}:/app",
            "    depends_on:",
            "      postgres:",
            "        condition: service_healthy",
            "      redis:",
            "        condition: service_healthy",
            "    environment:",
            *env_block,
        ]
        # celery-worker probes app.celery_app then app.tasks then app.celery — one of them
        # usually exists per model; if not, container exits and we mark verify_error.
        launch_worker = (
            "bash -lc "
            "'set -e; "
            "pip install --quiet --disable-pip-version-check -r requirements.txt >/tmp/pip.log 2>&1 || "
            "  (echo pip-install-failed; tail -40 /tmp/pip.log; sleep infinity); "
            "for M in app.celery_app app.core.celery_app app.tasks app.celery; do "
            "  python -c \"import importlib; importlib.import_module(\\\"$M\\\"); print(\\\"picked \\\"$M)\" 2>/dev/null && exec celery -A $M worker -l INFO --pool=solo; "
            "done; "
            "echo no-celery-app; sleep infinity'"
        )
        launch_beat = launch_worker.replace("worker -l INFO --pool=solo", "beat -l INFO")
        lines.extend([
            f"  celery-worker-{code.lower()}:",
            *common,
            f"    command: {launch_worker}",
            f"  celery-beat-{code.lower()}:",
            *common,
            f"    command: {launch_beat}",
        ])

    lines.extend([
        "volumes:",
        "  pg_data:",
    ])

    # side-car init-db.sh returned separately below (embedded via docker-compose file adjacent)
    return "\n".join(lines) + "\n", init_sql


# ---------- ensure_up ----------

def ensure_up(task_id: str, codes: list[str]) -> dict:
    """Bring up the stack idempotently; return dynamic host ports."""
    check_host()
    remote_dir = rc.remote_task_dir(task_id)

    _ssh(f"mkdir -p {shlex.quote(str(remote_dir))}")

    compose_yaml, init_sql = _render_compose(task_id, codes)

    # write both files locally then scp — MUST use LF line endings (going to Linux)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _write_lf(tdp / "docker-compose.yml", compose_yaml)
        _write_lf(tdp / "init-db.sh", init_sql)
        _scp_to_remote(tdp / "docker-compose.yml", f"{remote_dir}/docker-compose.yml")
        _scp_to_remote(tdp / "init-db.sh", f"{remote_dir}/init-db.sh")

    _ssh(f"cd {shlex.quote(str(remote_dir))} && chmod +x init-db.sh")

    proj = rc.project_name(task_id)
    up = _ssh(
        f"cd {shlex.quote(str(remote_dir))} && "
        f"docker compose -p {proj} up -d --wait --wait-timeout 90",
        timeout=180, check=False,
    )
    if up.returncode != 0:
        # autoheal: down then up once
        _ssh(f"cd {shlex.quote(str(remote_dir))} && docker compose -p {proj} down -v",
             timeout=60, check=False)
        up = _ssh(
            f"cd {shlex.quote(str(remote_dir))} && "
            f"docker compose -p {proj} up -d --wait --wait-timeout 120",
            timeout=180, check=False,
        )
        if up.returncode != 0:
            raise ComposeUpFailed(
                f"{proj} up failed twice.\nstdout:\n{up.stdout}\nstderr:\n{up.stderr}"
            )

    return _query_ports(task_id)


def _query_ports(task_id: str, retries: int = 5) -> dict:
    proj = rc.project_name(task_id)
    remote_dir = rc.remote_task_dir(task_id)
    for i in range(retries):
        pg = _ssh(
            f"cd {shlex.quote(str(remote_dir))} && "
            f"docker compose -p {proj} port postgres 5432",
            check=False,
        )
        redis = _ssh(
            f"cd {shlex.quote(str(remote_dir))} && "
            f"docker compose -p {proj} port redis 6379",
            check=False,
        )
        if pg.returncode == 0 and redis.returncode == 0 and ":" in pg.stdout and ":" in redis.stdout:
            return {
                "postgres_port": int(pg.stdout.strip().rsplit(":", 1)[1]),
                "redis_port": int(redis.stdout.strip().rsplit(":", 1)[1]),
            }
        time.sleep(0.5 * (i + 1))
    raise ComposeUpFailed(f"could not parse compose ports after {retries} retries")


# ---------- other ops ----------

def sync_code(task_id: str, codes: list[str]) -> None:
    """rsync extracted/<CODE>/ per model to u03l."""
    check_host()
    for code in codes:
        local = REPO_ROOT / "tasks" / task_id / "extracted" / code
        if not local.exists():
            raise FileNotFoundError(f"missing {local}")
        remote = rc.remote_model_dir(task_id, code)
        _ssh(f"mkdir -p {shlex.quote(str(remote))}")
        _rsync_dir(local, str(remote))


def down(task_id: str, prune_data: bool = True) -> None:
    check_host()
    proj = rc.project_name(task_id)
    remote_dir = rc.remote_task_dir(task_id)
    _ssh(
        f"cd {shlex.quote(str(remote_dir))} 2>/dev/null && "
        f"docker compose -p {proj} down -v || true",
        timeout=60, check=False,
    )
    if prune_data:
        _ssh(f"rm -rf {shlex.quote(str(remote_dir))}", check=False)


def status(task_id: str) -> dict:
    check_host()
    proj = rc.project_name(task_id)
    r = _ssh(
        f"docker compose -p {proj} ps --format json 2>/dev/null || echo '[]'",
        check=False,
    )
    try:
        raw = r.stdout.strip()
        containers = [json.loads(l) for l in raw.split("\n") if l.strip().startswith("{")]
    except json.JSONDecodeError:
        containers = []
    if not containers:
        return {"up": False, "containers": []}
    try:
        ports = _query_ports(task_id, retries=1)
    except Exception:
        ports = {}
    return {"up": True, "containers": containers, "ports": ports}


def list_tasks() -> list[str]:
    check_host()
    r = _ssh("docker compose ls --format json 2>/dev/null || echo '[]'", check=False)
    try:
        entries = json.loads(r.stdout.strip() or "[]")
    except json.JSONDecodeError:
        return []
    return [e["Name"] for e in entries if e.get("Name", "").startswith("qc_")]


# ---------- CLI ----------

def _cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="u03l.py")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check-host")

    sp = sub.add_parser("ensure-up")
    sp.add_argument("task_id")
    sp.add_argument("codes", nargs="+")

    sp = sub.add_parser("sync-code")
    sp.add_argument("task_id")
    sp.add_argument("codes", nargs="+")

    sp = sub.add_parser("down")
    sp.add_argument("task_id")
    sp.add_argument("--keep-data", action="store_true")

    sp = sub.add_parser("status")
    sp.add_argument("task_id")

    sub.add_parser("list-tasks")

    args = p.parse_args(argv)
    try:
        if args.cmd == "check-host":
            check_host()
            print("u03l 可达")
            return 0
        if args.cmd == "ensure-up":
            ports = ensure_up(args.task_id, args.codes)
            print(json.dumps(ports, indent=2))
            return 0
        if args.cmd == "sync-code":
            sync_code(args.task_id, args.codes)
            print("sync OK")
            return 0
        if args.cmd == "down":
            down(args.task_id, prune_data=not args.keep_data)
            print("down OK")
            return 0
        if args.cmd == "status":
            print(json.dumps(status(args.task_id), indent=2, ensure_ascii=False))
            return 0
        if args.cmd == "list-tasks":
            for n in list_tasks():
                print(n)
            return 0
    except HostUnreachable as e:
        print(f"[stop] {e}", file=sys.stderr)
        return 2
    except ComposeUpFailed as e:
        print(f"[error] compose up failed: {e}", file=sys.stderr)
        return 3
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
