import os
import subprocess

import pytest

from thinky_backup import config, sqlite_snap
from thinky_backup.restic import Restic

sqlite_snap.SNAPSHOT_DELAY = 0


class Pushes(list):
    def __call__(self, url, ok, msg):
        self.append((url, ok, msg))


@pytest.fixture
def pushes():
    return Pushes()


@pytest.fixture
def repo_env(tmp_path):
    env = {**os.environ, "RESTIC_REPOSITORY": str(tmp_path / "repo"), "RESTIC_PASSWORD": "test",
           "RESTIC_CACHE_DIR": str(tmp_path / "cache")}
    subprocess.run(["restic", "init"], env=env, check=True, capture_output=True)
    return env


@pytest.fixture
def make_cfg(tmp_path, repo_env):
    def _make(**extra):
        env = {**repo_env, "BACKUP_HOST": "testhost", "BACKUP_TAG": "configs",
               "SCRATCH_DIR": str(tmp_path / "scratch"), "KUMA_PUSH_BACKUP": "http://kuma/b",
               "KUMA_PUSH_CHECK": "http://kuma/c", "KUMA_PUSH_DRILL": "http://kuma/d"}
        env.update(extra)
        return config.load(env), Restic(env)
    return _make


def ls_latest(restic):
    out = restic.run("ls", "latest", capture=True)
    assert out.returncode == 0, out.stderr
    return set(out.stdout.splitlines())


def snapshot_count(restic, env_overrides=None):
    import json
    out = restic.run("snapshots", "--json", capture=True, env_overrides=env_overrides)
    assert out.returncode == 0, out.stderr
    return len(json.loads(out.stdout))
