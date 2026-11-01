"""Shared helpers for the thinky-restore tests.

The tests build a real restic repository from files placed at absolute paths (/src/..., /scratch/...)
because restic stores absolute paths. That is only done inside the disposable test container
(THINKY_TEST_CONTAINER=1); elsewhere the tests skip, so they can never touch a real /src.
"""
import gzip
import json
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).parent.parent / "restore" / "thinky-restore"
FAKEBIN = pathlib.Path(__file__).parent / "fakebin"
PASSWORD = "Zq91-very-distinct-test-password"
AWS_ID = "AKIA-distinct-test-key-id"
AWS_SECRET = "distinct-test-secret-access-key"
SECRETS = (PASSWORD, AWS_ID, AWS_SECRET)


def isolated_script(tmp_path):
    """A copy of the tool in its own folder, so the stack's shipped map file is not picked up beside it."""
    d = tmp_path / "bin"
    d.mkdir(exist_ok=True)
    dest = d / "thinky-restore"
    shutil.copy(SCRIPT, dest)
    return dest


def gz(text):
    return gzip.compress(text.encode())


def real_binary(name):
    for d in os.environ["PATH"].split(":"):
        p = pathlib.Path(d) / name
        if p.exists() and pathlib.Path(d).resolve() != FAKEBIN.resolve():
            return str(p)
    raise FileNotFoundError(name)


class World:
    """A throwaway restic repository, a fake machine root (TR_ROOT) and a fake docker."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.script = isolated_script(tmp_path)
        self.root = tmp_path / "root"
        self.root.mkdir()
        self.repo = tmp_path / "repo"
        self.dock = tmp_path / "docker"
        (self.dock / "mounts").mkdir(parents=True)
        (self.dock / "ctr-scratch").mkdir()
        (self.dock / "ps").write_text("")
        self.base_env = {**os.environ, "PATH": f"{FAKEBIN}:{os.environ['PATH']}",
                         "REAL_RESTIC": real_binary("restic"), "FAKE_DOCKER_DIR": str(self.dock),
                         "RESTIC_CACHE_DIR": str(tmp_path / "cache"), "HOME": str(tmp_path)}
        init_env = {**self.base_env, "RESTIC_REPOSITORY": str(self.repo), "RESTIC_PASSWORD": PASSWORD}
        subprocess.run([self.base_env["REAL_RESTIC"], "init"], env=init_env, check=True, capture_output=True)

    # -- building snapshots ---------------------------------------------------------
    def backup(self, host, tag, files, owners=None):
        """Write `files` ({absolute path: text or bytes}) to the real filesystem, back them up, remove them."""
        if os.environ.get("THINKY_TEST_CONTAINER") != "1":
            pytest.skip("needs the disposable test container (THINKY_TEST_CONTAINER=1)")
        made_files, made_dirs = [], []
        for path, content in files.items():
            p = pathlib.Path(path)
            assert not p.exists(), f"{path} already exists; refusing to overwrite it"
            for parent in reversed(p.parents):
                if not parent.exists():
                    parent.mkdir()
                    made_dirs.append(parent)
            p.write_bytes(content if isinstance(content, bytes) else content.encode())
            made_files.append(p)
        for path, (uid, gid) in (owners or {}).items():
            os.chown(path, uid, gid)
        env = {**self.base_env, "RESTIC_REPOSITORY": str(self.repo), "RESTIC_PASSWORD": PASSWORD}
        try:
            out = subprocess.run([self.base_env["REAL_RESTIC"], "backup", "--host", host, "--tag", tag,
                                  *self.sources(files)], env=env, capture_output=True, text=True)
            assert out.returncode == 0, out.stderr
        finally:
            for p in made_files:
                p.unlink()
            for d in reversed(made_dirs):
                shutil.rmtree(d, ignore_errors=True)

    @staticmethod
    def sources(files):
        tops = set()
        for path in files:
            parts = path.split("/")
            tops.add("/" + parts[1] if parts[1] in ("src", "scratch") else "/".join(parts[:3]))
        return sorted(tops)

    # -- the fake machine -----------------------------------------------------------
    def live(self, rel, content=None, owner=None):
        p = self.root / rel.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        if content is not None:
            p.write_bytes(content if isinstance(content, bytes) else content.encode())
            if owner:
                os.chown(p, *owner)
        return p

    def set_running(self, *names):
        (self.dock / "ps").write_text("\n".join(names) + "\n")

    def mount(self, name, dest, src):
        with open(self.dock / "mounts" / name, "a") as fh:
            fh.write(f"{dest}\t{src}\n")

    def running(self):
        return [n for n in (self.dock / "ps").read_text().split() if n]

    def docker_calls(self):
        log = self.dock / "log"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def restic_log(self):
        log = self.dock / "restic.log"
        return log.read_text() if log.exists() else ""

    def aside(self, rel):
        """The *.before-restore-* siblings of a live path."""
        p = self.root / rel.lstrip("/")
        return sorted(p.parent.glob(p.name + ".before-restore-*"))

    # -- running the tool ---------------------------------------------------------
    def env(self, **extra):
        env = {**self.base_env, "TR_ROOT": str(self.root), "TR_BACKEND": "local",
               "RESTIC_REPOSITORY": str(self.repo), "RESTIC_PASSWORD": PASSWORD,
               "AWS_ACCESS_KEY_ID": AWS_ID, "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
               "RCLONE_CONFIG_GDRIVE_CLIENT_ID": "test-cid", "RCLONE_CONFIG_GDRIVE_CLIENT_SECRET": "test-csecret",
               "RCLONE_CONFIG_GDRIVE_TOKEN": '{"access_token":"test"}', "RCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID": "test-fid",
               "THINKY_RESTORE_CONF": "/nonexistent", "THINKY_RESTORE_ENV_FILE": "/nonexistent",
               "THINKY_RESTORE_MAP": ""}
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    def run(self, *args, stdin="", **extra):
        return subprocess.run(["bash", str(self.script), *args], input=stdin, env=self.env(**extra),
                              capture_output=True, text=True, timeout=180)

    def everything(self, result):
        """All text the tool could have leaked a secret into: output, both logs, and every file under tmp."""
        parts = [result.stdout, result.stderr, (self.dock / "log").read_text() if (self.dock / "log").exists() else "",
                 self.restic_log()]
        for p in self.tmp.rglob("*"):
            if p.is_file() and not str(p).startswith(str(self.repo)) and "cache" not in p.parts:
                try:
                    parts.append(p.read_text(errors="ignore"))
                except OSError:
                    pass
        return "\n".join(parts)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def script(tmp_path):
    return isolated_script(tmp_path)


VM100_MAP = "/src/thames-water/data=/root/thames-water-service/data\n/src/frigate/config=/opt/frigate/config\n"


@pytest.fixture
def mapfile(tmp_path):
    p = tmp_path / "test.map"
    p.write_text("# test map\n" + VM100_MAP)
    return str(p)
