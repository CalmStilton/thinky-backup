"""Report a job's result to an Uptime Kuma push monitor. Reporting never breaks a job."""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


def push_url(base: str, ok: bool, msg: str) -> str:
    # Kuma shows push URLs with "?status=up&msg=OK&ping=" already on; drop it and build our own.
    base = base.split("?", 1)[0]
    query = urllib.parse.urlencode({"status": "up" if ok else "down", "msg": msg[:200], "ping": ""})
    return f"{base}?{query}"


def push(base: str, ok: bool, msg: str, opener=urllib.request.urlopen) -> None:
    if not base:
        log.warning("no Kuma push URL set; result not reported: %s", msg)
        return
    try:
        with opener(push_url(base, ok, msg), timeout=10) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001 - reporting must never fail the job
        log.error("Kuma push failed: %s", exc)
