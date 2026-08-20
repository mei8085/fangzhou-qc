"""Shared naming + path conventions for the u03l docker backend.

Any script that talks to u03l should route path/name construction through here
so that project name, remote dir, and container names stay in lockstep.
"""
from __future__ import annotations

from pathlib import PurePosixPath

# u03l is the SSH alias configured in ~/.ssh/config; keep as a constant so
# swapping to u04l or a container later is a one-line change.
SSH_HOST = "u03l"
REMOTE_BASE = PurePosixPath("/home/fz/qc-eval")


def project_name(task_id: str) -> str:
    """docker compose project name for a task — lowercased, hyphens allowed."""
    return f"qc_{task_id.lower()}"


def remote_task_dir(task_id: str) -> PurePosixPath:
    return REMOTE_BASE / "tasks" / task_id


def remote_model_dir(task_id: str, code: str) -> PurePosixPath:
    return remote_task_dir(task_id) / code


def db_name(task_id: str, code: str) -> str:
    """One postgres database per (task, model), zero cross-model pollution."""
    return f"qc_{task_id.lower()}_{code.lower()}"


def broker_db_index(code_index: int) -> int:
    """redis broker db number for a given model index (0..3)."""
    if not 0 <= code_index <= 3:
        raise ValueError(f"code_index must be 0..3, got {code_index}")
    return code_index


def result_db_index(code_index: int) -> int:
    return 4 + code_index  # 4..7 for celery result backends


PG_USER = "airguard"
PG_PASSWORD = "airguard_dev"  # dev-only, never leaves u03l
