import sqlite3

import pytest

from thinky_backup import sqlite_snap


def make_wal_db(path, rows):
    """A WAL database whose rows are still only in the -wal file (not checkpointed)."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t (n INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    return conn  # keep open so the WAL is not checkpointed on close


def count(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
    finally:
        conn.close()


def test_snapshot_includes_uncheckpointed_wal(tmp_path):
    live = tmp_path / "app" / "app.db"
    live.parent.mkdir()
    keep = make_wal_db(live, 50)
    assert (tmp_path / "app" / "app.db-wal").stat().st_size > 0
    dest = tmp_path / "snap" / "app.db"
    sqlite_snap.snapshot(str(live), str(dest))
    keep.close()
    assert count(dest) == 50
    assert not (tmp_path / "snap" / "app.db.partial").exists()


def test_corrupt_database_raises_after_retries(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(sqlite_snap.MAGIC + b"\x00" * 200)
    with pytest.raises(sqlite_snap.SnapshotError, match="bad.db"):
        sqlite_snap.snapshot(str(bad), str(tmp_path / "out.db"), attempts=2, delay=0)


def test_find_databases(tmp_path):
    (tmp_path / "a").mkdir()
    make_wal_db(tmp_path / "a" / "a.db", 1).close()
    make_wal_db(tmp_path / "a" / "logs.db", 1).close()
    (tmp_path / "a" / "notes.txt").write_text("SQLite format 3 is not at offset 0")
    (tmp_path / "skip").mkdir()
    make_wal_db(tmp_path / "skip" / "s.db", 1).close()
    (tmp_path / "a" / "data.sqlite").write_bytes(sqlite_snap.MAGIC + b"\x00" * 100)
    found = sqlite_snap.find_databases([str(tmp_path)], [str(tmp_path / "skip"), "logs.db"])
    assert found == [str(tmp_path / "a" / "a.db"), str(tmp_path / "a" / "data.sqlite")]


def test_find_accepts_a_file_source(tmp_path):
    db = tmp_path / "one.db"
    make_wal_db(db, 1).close()
    assert sqlite_snap.find_databases([str(db)], []) == [str(db)]


@pytest.mark.parametrize("path,excludes,expected", [
    ("/src/opt/sonarr/logs.db", ["logs.db"], True),
    ("/src/opt/sonarr/sonarr.db", ["logs.db"], False),
    ("/src/opt/calibre/config/Calibre Library/metadata.db", ["/src/opt/calibre/config/Calibre Library"], True),
    ("/src/opt/calibre/config/Calibre Library2/x.db", ["/src/opt/calibre/config/Calibre Library"], False),
    ("/src/opt/x/MediaCover", ["MediaCover"], True),
    ("/src/opt/x/a.log", ["*.log"], True),
])
def test_is_excluded(path, excludes, expected):
    assert sqlite_snap.is_excluded(path, excludes) is expected


def test_snapshot_all_mirrors_paths_and_reports_failures(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    make_wal_db(src / "good.db", 3).close()
    (src / "bad.db").write_bytes(sqlite_snap.MAGIC + b"\x00" * 200)
    snap_root = tmp_path / "snap"
    (snap_root / "leftover").mkdir(parents=True)
    sqlite_snap.SNAPSHOT_DELAY = 0
    result = sqlite_snap.snapshot_all([str(src)], [], str(snap_root))
    assert result.snapshotted == [str(src / "good.db")]
    assert len(result.problems) == 1 and "bad.db" in result.problems[0]
    assert count(sqlite_snap.snapshot_path(str(src / "good.db"), str(snap_root))) == 3
    assert not (snap_root / "leftover").exists()
