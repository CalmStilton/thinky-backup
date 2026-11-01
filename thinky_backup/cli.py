"""thinky-backup {schedule,backup,check,drill,init}"""
from __future__ import annotations

import logging
import os
import sys

from . import config, drill, jobs, kuma
from .config import ConfigError
from .restic import Restic

log = logging.getLogger("thinky_backup")
COMMANDS = ("schedule", "backup", "check", "drill", "init")
CRONTAB = "/tmp/thinky-backup.crontab"


def crontab(cfg: config.Config) -> str:
    lines = [f"{cron} thinky-backup {cmd}"
             for cron, cmd in ((cfg.backup_cron, "backup"), (cfg.check_cron, "check"),
                               (cfg.drill_cron, "drill")) if cron]
    if not lines:
        raise ConfigError("schedule: set at least one of BACKUP_CRON, CHECK_CRON, DRILL_CRON")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(f"usage: thinky-backup {{{','.join(COMMANDS)}}}", file=sys.stderr)
        return 2
    cmd = argv[0]
    try:
        cfg = config.load()
    except ConfigError as exc:
        log.error("config: %s", exc)
        return 2
    if cmd == "schedule":
        try:
            table = crontab(cfg)
        except ConfigError as exc:
            log.error("config: %s", exc)
            return 2
        with open(CRONTAB, "w", encoding="utf-8") as fh:
            fh.write(table)
        log.info("schedule:\n%s", table.rstrip())
        os.execvp("supercronic", ["supercronic", CRONTAB])
    restic = Restic()
    if cmd == "init":
        return jobs.init(restic)
    run = {"backup": jobs.backup, "check": jobs.check, "drill": drill.drill}[cmd]
    url = {"backup": cfg.push_backup, "check": cfg.push_check, "drill": cfg.push_drill}[cmd]
    try:
        return run(cfg, restic)
    except ConfigError as exc:
        log.error("config: %s", exc)
        kuma.push(url, False, f"{cmd} config error: {exc}")
        return 2
    except Exception as exc:
        kuma.push(url, False, f"{cmd} crashed: {exc}")
        raise
