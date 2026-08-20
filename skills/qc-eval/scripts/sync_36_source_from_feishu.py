#!/usr/bin/env python3
"""Compatibility wrapper for the current 38期 Feishu QC source sync.

The historical filename is kept so older commands do not silently use stale
previous-period defaults. All implementation lives in sync_source_from_feishu.py.
"""

from sync_source_from_feishu import main


if __name__ == "__main__":
    raise SystemExit(main())
