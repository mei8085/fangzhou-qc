"""Local port allocation for the fullstack verify pipeline.

Deterministic per-task base ports keep parallel sessions from stepping on each
other; a bind-probe walk handles the (rare) collision case.

Layout per TASK_ID (each block reserves 8 ports, more than we need):
  pg_local_base    : 1 port  (postgres over SSH tunnel)
  redis_local_base : 1 port  (redis over SSH tunnel)
  uvicorn_base     : 4 ports (one per model)
  vite_base        : 4 ports (one per model)

Ranges chosen far outside common dev ports (5432/6379/3000/5173/8000).
"""
from __future__ import annotations

import hashlib
import socket


# 4 disjoint zones, each 256 ports wide. Deterministic hash picks the offset
# within the zone.
_PG_ZONE     = (45000, 45256)
_REDIS_ZONE  = (46000, 46256)
_UVICORN_ZONE = (47000, 47256)  # need 4 consecutive → step by 4
_VITE_ZONE   = (48000, 48256)


def _hash_offset(task_id: str, mod: int) -> int:
    h = hashlib.sha1(task_id.encode()).digest()
    return int.from_bytes(h[:4], "big") % mod


def base_for(task_id: str) -> dict[str, int]:
    """Return preferred base ports for a task; may still collide, use pick_free."""
    return {
        "postgres": _PG_ZONE[0] + _hash_offset(task_id + "postgres", 256),
        "redis": _REDIS_ZONE[0] + _hash_offset(task_id + "redis", 256),
        # uvicorn/vite: pick a base that leaves room for 4 sequential ports
        "uvicorn": _UVICORN_ZONE[0] + (_hash_offset(task_id + "uvicorn", 63) * 4),
        "vite": _VITE_ZONE[0] + (_hash_offset(task_id + "vite", 63) * 4),
    }


def pick_free(preferred: int, max_walk: int = 32) -> int:
    """Return `preferred` if it's bindable on localhost, else walk +1 up to max_walk."""
    for candidate in range(preferred, preferred + max_walk):
        if _is_free(candidate):
            return candidate
    raise RuntimeError(f"no free port in [{preferred}..{preferred + max_walk})")


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True
