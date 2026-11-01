import gzip
import os
import sqlite3

import pytest

from thinky_backup import config, drill, jobs


def gz(path, sql):
    with gzip.open(path, "wt") as fh:
        fh.write(sql)
    return str(path)


def test_mariadb_counts_rows(tmp_path):
    dump = gz(tmp_path / "d.sql.gz", "CREATE TABLE entities (id INT);\nINSERT INTO entities VALUES (1),(2);\n")
    assert drill.check_mariadb(dump, "entities", str(tmp_path / "w")) == []


def test_mariadb_empty_table_fails(tmp_path):
    dump = gz(tmp_path / "d.sql.gz", "CREATE TABLE entities (id INT);\n")
    assert drill.check_mariadb(dump, "entities", str(tmp_path / "w")) == ["mariadb: table entities is empty"]


def test_mariadb_bad_sql_fails(tmp_path):
    dump = gz(tmp_path / "d.sql.gz", "THIS IS NOT SQL;\n")
    problems = drill.check_mariadb(dump, "entities", str(tmp_path / "w"))
    assert len(problems) == 1 and problems[0].startswith("mariadb: load failed")


def test_mariadb_missing_dump(tmp_path):
    assert drill.check_mariadb(str(tmp_path / "nope.gz"), "entities", str(tmp_path)) == [
        f"mariadb: {tmp_path / 'nope.gz'} missing from snapshot"]


def test_sqlite_good_and_bad(tmp_path):
    good = tmp_path / "g.db"
    conn = sqlite3.connect(good)
    conn.execute("CREATE TABLE t (n)")
    conn.commit()
    conn.close()
    assert drill.check_sqlite(str(good)) == []
    bad = tmp_path / "b.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 200)
    assert drill.check_sqlite(str(bad))[0].startswith("sqlite:")


def test_pgdump_rejects_garbage(tmp_path):
    f = tmp_path / "x.dump"
    f.write_bytes(b"not a dump")
    assert drill.check_pgdump(str(f))[0].startswith("pg_dump:")
    # The happy path (a real -Fc dump) is checked against ReadMeABook's live dump in Task 12.


def test_drill_end_to_end(make_cfg, tmp_path, pushes):
    src = tmp_path / "src"
    src.mkdir()
    gz(src / "bookstack.sql.gz", "CREATE TABLE entities (id INT);\nINSERT INTO entities VALUES (7);\n")
    conn = sqlite3.connect(src / "app.db")
    conn.execute("CREATE TABLE t (n)")
    conn.commit()
    conn.close()
    cfg, restic = make_cfg(BACKUP_SOURCES=str(src))
    assert jobs.backup(cfg, restic, push=pushes) == 0
    snap_db = os.path.join(cfg.scratch, "sqlite", str(src / "app.db").lstrip("/"))
    cfg, restic = make_cfg(DRILL_MARIADB_FILE=str(src / "bookstack.sql.gz"), DRILL_SQLITE_FILE=snap_db)
    assert drill.drill(cfg, restic, push=pushes) == 0
    assert pushes[-1] == ("http://kuma/d", True, "testhost/configs drill ok")


def test_drill_reports_missing_file(make_cfg, tmp_path, pushes):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("x")
    cfg, restic = make_cfg(BACKUP_SOURCES=str(src))
    jobs.backup(cfg, restic, push=pushes)
    cfg, restic = make_cfg(DRILL_SQLITE_FILE=str(src / "absent.db"))
    assert drill.drill(cfg, restic, push=pushes) == 1
    # restic may exit 0 having restored nothing ("missing from snapshot") or non-zero ("restore failed");
    # either way the drill must fail and report down.
    assert pushes[-1][1] is False


def test_drill_needs_a_target(make_cfg, pushes):
    cfg, restic = make_cfg()
    with pytest.raises(config.ConfigError, match="DRILL_"):
        drill.drill(cfg, restic, push=pushes)
