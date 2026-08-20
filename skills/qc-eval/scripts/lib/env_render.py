"""Render <model_dir>/.env.local from .env.example given tunnel state.

.env.example holds placeholder URLs pointing at localhost:5432/6379; we rewrite
each to the tunneled local ports and to this model's own DB name + broker db.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import remote_config as rc


_URL_KEYS = ("DATABASE_URL", "REDIS_URL", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND")


def render(model_dir: Path, task_id: str, code: str, code_index: int,
           tunnel_state: dict, uvicorn_port: int) -> Path:
    """Write model_dir/.env.local; return its path.

    tunnel_state expected: {"postgres": {"local": int, ...}, "redis": {"local": int, ...}}
    """
    example = model_dir / ".env.example"
    lines: list[str] = []
    if example.exists():
        lines = example.read_text(encoding="utf-8").splitlines()

    pg_local = tunnel_state["postgres"]["local"]
    redis_local = tunnel_state["redis"]["local"]
    db = rc.db_name(task_id, code)
    broker_idx = rc.broker_db_index(code_index)
    result_idx = rc.result_db_index(code_index)

    overrides = {
        "DATABASE_URL":
            f"postgresql+asyncpg://{rc.PG_USER}:{rc.PG_PASSWORD}@localhost:{pg_local}/{db}",
        "REDIS_URL":            f"redis://localhost:{redis_local}/{broker_idx}",
        "CELERY_BROKER_URL":    f"redis://localhost:{redis_local}/{broker_idx}",
        "CELERY_RESULT_BACKEND": f"redis://localhost:{redis_local}/{result_idx}",
        "SECRET_KEY":           "qc-eval-dev-not-secret",
        "APP_ENV":              "development",
        "LOG_LEVEL":            "INFO",
        # some models expect these:
        "APP_PORT":             str(uvicorn_port),
        "PORT":                 str(uvicorn_port),
    }

    seen = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Z_][A-Z_0-9]*)\s*=", line)
        if m and m.group(1) in overrides:
            key = m.group(1)
            out.append(f"{key}={overrides[key]}")
            seen.add(key)
        else:
            out.append(line)
    # append keys not in .env.example
    for k, v in overrides.items():
        if k not in seen:
            out.append(f"{k}={v}")

    target = model_dir / ".env.local"
    target.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
    return target
