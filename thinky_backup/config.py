"""Read a job's settings from environment variables. All validation lives here."""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass

DEFAULT_FORGET = "--keep-daily 7 --keep-weekly 4 --keep-monthly 6"


class ConfigError(Exception):
    pass


def _lines(value: str | None) -> list[str]:
    out = []
    for raw in (value or "").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _bool(name: str, value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    v = value.strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name}: not a boolean: {value!r}")


@dataclass(frozen=True)
class Config:
    host: str
    tag: str
    sources: list[str]
    excludes: list[str]
    forget_args: list[str]
    sqlite_scan: bool
    scratch: str
    fresh_files: list[str]
    fresh_max_age_hours: float
    check_subset: str
    repository2: str
    password2: str
    push_backup: str
    push_check: str
    push_drill: str
    backup_cron: str
    check_cron: str
    drill_cron: str
    drill_mariadb_file: str
    drill_mariadb_table: str
    drill_sqlite_file: str
    drill_pgdump_file: str


def load(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    for key in ("RESTIC_REPOSITORY", "RESTIC_PASSWORD", "BACKUP_HOST", "BACKUP_TAG"):
        if not env.get(key):
            raise ConfigError(f"{key} is required")
    try:
        max_age = float(env.get("FRESH_MAX_AGE_HOURS") or "6")
    except ValueError:
        raise ConfigError(f"FRESH_MAX_AGE_HOURS: not a number: {env['FRESH_MAX_AGE_HOURS']!r}") from None
    repository2 = env.get("RESTIC_REPOSITORY2", "")
    password2 = env.get("RESTIC_PASSWORD2", "")
    if repository2 and not password2:
        raise ConfigError("RESTIC_PASSWORD2 is required when RESTIC_REPOSITORY2 is set")
    table = env.get("DRILL_MARIADB_TABLE") or "entities"
    if not re.fullmatch(r"[A-Za-z0-9_]+", table):
        raise ConfigError(f"DRILL_MARIADB_TABLE: not a plain table name: {table!r}")
    return Config(
        host=env["BACKUP_HOST"],
        tag=env["BACKUP_TAG"],
        sources=_lines(env.get("BACKUP_SOURCES")),
        excludes=_lines(env.get("BACKUP_EXCLUDES")),
        forget_args=shlex.split(env.get("FORGET_ARGS") or DEFAULT_FORGET),
        sqlite_scan=_bool("SQLITE_SCAN", env.get("SQLITE_SCAN"), True),
        scratch=env.get("SCRATCH_DIR") or "/scratch",
        fresh_files=_lines(env.get("FRESH_FILES")),
        fresh_max_age_hours=max_age,
        check_subset=env.get("CHECK_READ_DATA_SUBSET") or "5%",
        repository2=repository2,
        password2=password2,
        push_backup=env.get("KUMA_PUSH_BACKUP", ""),
        push_check=env.get("KUMA_PUSH_CHECK", ""),
        push_drill=env.get("KUMA_PUSH_DRILL", ""),
        backup_cron=env.get("BACKUP_CRON", ""),
        check_cron=env.get("CHECK_CRON", ""),
        drill_cron=env.get("DRILL_CRON", ""),
        drill_mariadb_file=env.get("DRILL_MARIADB_FILE", ""),
        drill_mariadb_table=table,
        drill_sqlite_file=env.get("DRILL_SQLITE_FILE", ""),
        drill_pgdump_file=env.get("DRILL_PGDUMP_FILE", ""),
    )
