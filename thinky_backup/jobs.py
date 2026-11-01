"""The backup, check and init jobs. Each ends with exactly one Kuma push."""
from __future__ import annotations

import logging
import os
import re

from . import freshness, kuma, sqlite_snap
from .config import Config, ConfigError
from .restic import Restic

log = logging.getLogger(__name__)
SIDE_SUFFIXES = ("-wal", "-shm", "-journal")


def _escape(path: str) -> str:
    """Turn a literal path into a restic exclude pattern (restic patterns are globs)."""
    return re.sub(r"([*?\[\\])", r"\\\1", path)


def finish(push_url: str, job: str, problems: list[str], push=None) -> int:
    push = kuma.push if push is None else push  # not `or`: an empty test double is falsy
    if problems:
        msg = f"{job}: " + "; ".join(problems)
        log.error(msg)
        push(push_url, False, msg)
        return 1
    log.info("%s ok", job)
    push(push_url, True, f"{job} ok")
    return 0


def backup(cfg: Config, restic: Restic, push=None) -> int:
    if not cfg.sources:
        raise ConfigError("BACKUP_SOURCES is empty")
    job = f"{cfg.host}/{cfg.tag} backup"
    problems: list[str] = []
    os.makedirs(cfg.scratch, exist_ok=True)
    snap_root = os.path.join(cfg.scratch, "sqlite")
    live_excludes: list[str] = []
    extra_sources: list[str] = []
    if cfg.sqlite_scan:
        scan = sqlite_snap.snapshot_all(cfg.sources, cfg.excludes, snap_root)
        problems += scan.problems
        for live in scan.snapshotted:
            live_excludes += [_escape(live)] + [_escape(live + s) for s in SIDE_SUFFIXES]
        if scan.snapshotted:
            extra_sources.append(snap_root)
    problems += freshness.stale(cfg.fresh_files, cfg.fresh_max_age_hours)

    exclude_file = os.path.join(cfg.scratch, "excludes.txt")
    with open(exclude_file, "w", encoding="utf-8") as fh:
        fh.writelines(f"{p}\n" for p in [*cfg.excludes, *live_excludes])

    rc = restic.run("backup", "--host", cfg.host, "--tag", cfg.tag, "--exclude-file", exclude_file,
                    *cfg.sources, *extra_sources).returncode
    if rc == 3:
        problems.append("some source files could not be read (restic exit 3)")
    elif rc != 0:
        problems.append(f"restic backup failed (exit {rc})")
        return finish(cfg.push_backup, job, problems, push)

    forget = ("forget", "--host", cfg.host, "--tag", cfg.tag, "--group-by", "host,tags", "--prune",
              *cfg.forget_args)
    rc = restic.run(*forget).returncode
    if rc != 0:
        problems.append(f"restic forget failed (exit {rc})")

    if cfg.repository2:
        # Clear RESTIC_REPOSITORY2/PASSWORD2: restic rejects them alongside --from-repo.
        second = {"RESTIC_REPOSITORY": cfg.repository2, "RESTIC_PASSWORD": cfg.password2,
                  "RESTIC_REPOSITORY2": "", "RESTIC_PASSWORD2": "",
                  "RESTIC_FROM_REPOSITORY": restic.env["RESTIC_REPOSITORY"],
                  "RESTIC_FROM_PASSWORD": restic.env["RESTIC_PASSWORD"]}
        rc = restic.run("copy", "--host", cfg.host, "--tag", cfg.tag, env_overrides=second).returncode
        if rc != 0:
            problems.append(f"restic copy to second repo failed (exit {rc})")
        else:
            rc = restic.run(*forget, env_overrides=second).returncode
            if rc != 0:
                problems.append(f"restic forget on second repo failed (exit {rc})")
    return finish(cfg.push_backup, job, problems, push)


def check(cfg: Config, restic: Restic, push=None) -> int:
    rc = restic.run("check", f"--read-data-subset={cfg.check_subset}").returncode
    problems = [] if rc == 0 else [f"restic check failed (exit {rc})"]
    return finish(cfg.push_check, f"{cfg.host}/{cfg.tag} check", problems, push)


def init(restic: Restic) -> int:
    if restic.run("cat", "config", capture=True).returncode == 0:
        log.info("repository already initialised")
        return 0
    return restic.run("init").returncode
