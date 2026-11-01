"""Check that files made by other jobs (e.g. nightly DB dumps) exist and are recent."""
from __future__ import annotations

import glob
import os
import time


def stale(patterns: list[str], max_age_hours: float, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    problems = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        if not matches:
            problems.append(f"missing: {pattern}")
            continue
        age_h = (now - max(os.path.getmtime(m) for m in matches)) / 3600
        if age_h > max_age_hours:
            problems.append(f"stale ({age_h:.1f}h old): {pattern}")
    return problems
