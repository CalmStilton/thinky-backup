"""Run restic. Global --retry-lock so hosts sharing a repo wait for each other's prune/check."""
from __future__ import annotations

import logging
import os
import shlex
import subprocess

log = logging.getLogger(__name__)


class Restic:
    def __init__(self, env: dict[str, str] | None = None, runner=subprocess.run):
        self.env = dict(os.environ if env is None else env)
        self.runner = runner

    def run(self, *args: str, env_overrides: dict[str, str] | None = None,
            capture: bool = False) -> subprocess.CompletedProcess:
        cmd = ["restic", "--retry-lock", "30m", *args]
        log.info("running: %s", shlex.join(cmd))
        return self.runner(cmd, env={**self.env, **(env_overrides or {})}, text=True,
                           capture_output=capture)
