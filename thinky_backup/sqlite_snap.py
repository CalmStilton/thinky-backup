"""Consistent copies of live SQLite databases from read-only mounts.

Opening a live WAL database on a read-only mount fails (SQLite has to write the -shm file),
and opening it read-write as root can leave root-owned -wal/-shm files behind for the app.
So each database and its -wal/-journal are copied into a private temp dir, the copy is opened
there (SQLite replays the WAL), integrity-checked, and written out as one clean file with the
backup API. A copy torn by a concurrent write fails integrity_check and is retried.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field

MAGIC = b"SQLite format 3\x00"
SIDE_FILES = ("-wal", "-journal")  # copied with the database; -shm is rebuilt by SQLite
SKIP_SUFFIXES = ("-wal", "-shm", "-journal")
SNAPSHOT_DELAY = 2.0


class SnapshotError(Exception):
    pass


@dataclass
class ScanResult:
    snapshotted: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def is_excluded(path: str, excludes: list[str]) -> bool:
    name = os.path.basename(path)
    for pattern in excludes:
        if pattern.startswith("/"):
            prefix = pattern.rstrip("/")
            if path == prefix or path.startswith(prefix + "/") or fnmatch.fnmatchcase(path, pattern):
                return True
        elif fnmatch.fnmatchcase(name, pattern):
            return True
    return False


def is_sqlite(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(16) == MAGIC
    except OSError:
        return False


def _candidate(path: str, excludes: list[str]) -> bool:
    return (not path.endswith(SKIP_SUFFIXES) and not os.path.islink(path)
            and not is_excluded(path, excludes) and is_sqlite(path))


def find_databases(sources: list[str], excludes: list[str]) -> list[str]:
    found = []
    for src in sources:
        if os.path.isfile(src):
            if _candidate(src, excludes):
                found.append(src)
            continue
        for root, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if not is_excluded(os.path.join(root, d), excludes))
            for name in sorted(files):
                path = os.path.join(root, name)
                if _candidate(path, excludes):
                    found.append(path)
    return found


def snapshot_path(live: str, snap_root: str) -> str:
    return os.path.join(snap_root, live.lstrip("/"))


def snapshot(live: str, dest: str, attempts: int = 3, delay: float = 2.0) -> None:
    last = "unknown error"
    for attempt in range(1, attempts + 1):
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "db")
            try:
                shutil.copyfile(live, copy)
                for suffix in SIDE_FILES:
                    if os.path.exists(live + suffix):
                        shutil.copyfile(live + suffix, copy + suffix)
                src = sqlite3.connect(copy)
                try:
                    verdict = src.execute("PRAGMA integrity_check").fetchone()[0]
                    if verdict == "ok":
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        partial = dest + ".partial"
                        if os.path.exists(partial):
                            os.remove(partial)
                        out = sqlite3.connect(partial)
                        try:
                            src.backup(out)
                        finally:
                            out.close()
                        os.replace(partial, dest)
                        return
                    last = f"integrity_check: {verdict}"
                finally:
                    src.close()
            except (OSError, sqlite3.Error) as exc:
                last = str(exc)
        if attempt < attempts:
            time.sleep(delay)
    raise SnapshotError(f"{live}: {last}")


def snapshot_all(sources: list[str], excludes: list[str], snap_root: str) -> ScanResult:
    shutil.rmtree(snap_root, ignore_errors=True)
    result = ScanResult()
    for live in find_databases(sources, excludes):
        try:
            snapshot(live, snapshot_path(live, snap_root), delay=SNAPSHOT_DELAY)
            result.snapshotted.append(live)
        except SnapshotError as exc:
            # The live file is not excluded, so restic still uploads it as a best effort.
            result.problems.append(f"sqlite snapshot failed: {exc}")
    return result
