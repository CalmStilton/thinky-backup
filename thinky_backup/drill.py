"""Monthly restore drill: restore chosen files from the latest snapshot and prove they load."""
from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time

from . import jobs
from .config import Config, ConfigError
from .restic import Restic


def check_sqlite(path: str) -> list[str]:
    if not os.path.exists(path):
        return [f"sqlite: {path} missing from snapshot"]
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return [f"sqlite: {exc}"]
    return [] if verdict == "ok" else [f"sqlite: integrity_check: {verdict}"]


def check_pgdump(path: str) -> list[str]:
    if not os.path.exists(path):
        return [f"pg_dump: {path} missing from snapshot"]
    out = subprocess.run(["pg_restore", "--list", path], capture_output=True, text=True)
    if out.returncode != 0:
        return [f"pg_dump: pg_restore --list failed: {out.stderr.strip()[:200]}"]
    if " TABLE " not in out.stdout:
        return ["pg_dump: dump lists no tables"]
    return []


def _wait_for_server(sock: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ping = subprocess.run(["mariadb-admin", f"--socket={sock}", "ping"], capture_output=True)
        if ping.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def check_mariadb(dump_gz: str, table: str, workdir: str, timeout: float = 60) -> list[str]:
    if not os.path.exists(dump_gz):
        return [f"mariadb: {dump_gz} missing from snapshot"]
    datadir = os.path.join(workdir, "mariadb")
    sock = os.path.join(workdir, "mariadb.sock")
    os.makedirs(workdir, exist_ok=True)
    install = subprocess.run(["mariadb-install-db", f"--datadir={datadir}", "--user=root",
                              "--skip-test-db", "--auth-root-authentication-method=normal"],
                             capture_output=True, text=True)
    if install.returncode != 0:
        return [f"mariadb: scratch install failed: {install.stderr.strip()[:200]}"]
    server = subprocess.Popen(["mariadbd", f"--datadir={datadir}", f"--socket={sock}",
                               "--skip-networking", "--skip-grant-tables", "--user=root"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not _wait_for_server(sock, timeout):
            return ["mariadb: scratch server did not start"]
        client = ["mariadb", f"--socket={sock}"]
        subprocess.run([*client, "-e", "CREATE DATABASE drill"], check=True, capture_output=True)
        load = subprocess.Popen([*client, "drill"], stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        with gzip.open(dump_gz, "rb") as fh:
            try:
                shutil.copyfileobj(fh, load.stdin)
            except BrokenPipeError:
                pass
        _, err = load.communicate()
        if load.returncode != 0:
            return [f"mariadb: load failed: {err.decode(errors='replace').strip()[:200]}"]
        out = subprocess.run([*client, "-N", "-B", "-e", f"SELECT COUNT(*) FROM drill.`{table}`"],
                             capture_output=True, text=True)
        if out.returncode != 0:
            return [f"mariadb: count failed: {out.stderr.strip()[:200]}"]
        return [] if int(out.stdout.strip()) > 0 else [f"mariadb: table {table} is empty"]
    finally:
        server.terminate()
        try:
            server.wait(30)
        except subprocess.TimeoutExpired:
            server.kill()


def drill(cfg: Config, restic: Restic, push=None) -> int:
    targets = [f for f in (cfg.drill_mariadb_file, cfg.drill_sqlite_file, cfg.drill_pgdump_file) if f]
    if not targets:
        raise ConfigError("drill: set at least one of DRILL_MARIADB_FILE, DRILL_SQLITE_FILE, DRILL_PGDUMP_FILE")
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        args = ["restore", "latest", "--host", cfg.host, "--tag", cfg.tag, "--target", tmp]
        for target in targets:
            args += ["--include", target]
        rc = restic.run(*args).returncode
        if rc != 0:
            problems.append(f"restic restore failed (exit {rc})")
        else:
            def restored(p: str) -> str:
                return os.path.join(tmp, p.lstrip("/"))
            if cfg.drill_mariadb_file:
                problems += check_mariadb(restored(cfg.drill_mariadb_file), cfg.drill_mariadb_table,
                                          os.path.join(tmp, "_mariadb"))
            if cfg.drill_sqlite_file:
                problems += check_sqlite(restored(cfg.drill_sqlite_file))
            if cfg.drill_pgdump_file:
                problems += check_pgdump(restored(cfg.drill_pgdump_file))
    return jobs.finish(cfg.push_drill, f"{cfg.host}/{cfg.tag} drill", problems, push)
