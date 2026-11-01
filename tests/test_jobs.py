import os
import sqlite3
import subprocess

import pytest

from conftest import ls_latest, snapshot_count
from thinky_backup import config, jobs


@pytest.fixture
def source(tmp_path):
    src = tmp_path / "src" / "app"
    (src / "logs").mkdir(parents=True)
    (src / "config.xml").write_text("<x/>")
    (src / "logs" / "app.txt").write_text("noise")
    conn = sqlite3.connect(src / "app.db")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (n)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    (tmp_path / "dump.sql.gz").write_text("dump")
    return src


def test_backup_ok(make_cfg, source, tmp_path, pushes):
    cfg, restic = make_cfg(BACKUP_SOURCES=str(source), BACKUP_EXCLUDES="logs",
                           FRESH_FILES=str(tmp_path / "dump.sql.gz"))
    assert jobs.backup(cfg, restic, push=pushes) == 0
    assert pushes == [("http://kuma/b", True, "testhost/configs backup ok")]
    paths = ls_latest(restic)
    snap = os.path.join(cfg.scratch, "sqlite", str(source / "app.db").lstrip("/"))
    assert str(source / "config.xml") in paths
    assert snap in paths
    assert str(source / "app.db") not in paths          # live file replaced by the snapshot
    assert str(source / "logs") not in paths            # excluded by basename


def test_stale_dump_still_uploads_but_reports_down(make_cfg, source, tmp_path, pushes):
    cfg, restic = make_cfg(BACKUP_SOURCES=str(source), FRESH_FILES=str(tmp_path / "missing.gz"))
    assert jobs.backup(cfg, restic, push=pushes) == 1
    assert pushes[0][1] is False and "missing:" in pushes[0][2]
    assert snapshot_count(restic) == 1


def test_uninitialised_repo_reports_down(make_cfg, source, tmp_path, pushes):
    cfg, restic = make_cfg(BACKUP_SOURCES=str(source), RESTIC_REPOSITORY=str(tmp_path / "nope"))
    assert jobs.backup(cfg, restic, push=pushes) == 1
    assert pushes[0][1] is False and "restic backup failed" in pushes[0][2]


def test_empty_sources_is_a_config_error(make_cfg, pushes):
    cfg, restic = make_cfg()
    with pytest.raises(config.ConfigError, match="BACKUP_SOURCES"):
        jobs.backup(cfg, restic, push=pushes)


def test_forget_applies_retention(make_cfg, source, pushes):
    cfg, restic = make_cfg(BACKUP_SOURCES=str(source), FORGET_ARGS="--keep-last 1")
    for _ in range(3):
        assert jobs.backup(cfg, restic, push=pushes) == 0
    assert snapshot_count(restic) == 1


def test_paths_with_glob_characters_are_excluded_literally(make_cfg, tmp_path, pushes):
    src = tmp_path / "src" / "odd [1]"
    src.mkdir(parents=True)
    conn = sqlite3.connect(src / "x.db")
    conn.execute("CREATE TABLE t (n)")
    conn.commit()
    conn.close()
    cfg, restic = make_cfg(BACKUP_SOURCES=str(src))
    assert jobs.backup(cfg, restic, push=pushes) == 0
    assert str(src / "x.db") not in ls_latest(restic)


def test_copy_to_second_repo(make_cfg, source, tmp_path, repo_env, pushes):
    repo2 = str(tmp_path / "repo2")
    subprocess.run(["restic", "init", "--copy-chunker-params"], check=True, capture_output=True,
                   env={**repo_env, "RESTIC_REPOSITORY": repo2, "RESTIC_PASSWORD": "pw2",
                        "RESTIC_FROM_REPOSITORY": repo_env["RESTIC_REPOSITORY"],
                        "RESTIC_FROM_PASSWORD": "test"})
    cfg, restic = make_cfg(BACKUP_SOURCES=str(source), RESTIC_REPOSITORY2=repo2, RESTIC_PASSWORD2="pw2")
    assert jobs.backup(cfg, restic, push=pushes) == 0
    assert snapshot_count(restic, {"RESTIC_REPOSITORY": repo2, "RESTIC_PASSWORD": "pw2"}) == 1


def test_check_ok_and_broken(make_cfg, source, tmp_path, pushes):
    cfg, restic = make_cfg(BACKUP_SOURCES=str(source), CHECK_READ_DATA_SUBSET="100%")
    jobs.backup(cfg, restic, push=pushes)
    assert jobs.check(cfg, restic, push=pushes) == 0
    assert pushes[-1] == ("http://kuma/c", True, "testhost/configs check ok")
    for pack in (tmp_path / "repo" / "data").rglob("*"):
        if pack.is_file():
            pack.write_bytes(b"corrupt")
    assert jobs.check(cfg, restic, push=pushes) == 1
    assert pushes[-1][1] is False


def test_init_is_idempotent(make_cfg, tmp_path):
    cfg, restic = make_cfg(RESTIC_REPOSITORY=str(tmp_path / "fresh"))
    assert jobs.init(restic) == 0
    assert jobs.init(restic) == 0
