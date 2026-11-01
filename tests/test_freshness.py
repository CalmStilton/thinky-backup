import os
import time

from thinky_backup import freshness


def test_fresh_file_passes(tmp_path):
    f = tmp_path / "dump.sql.gz"
    f.write_text("x")
    assert freshness.stale([str(f)], 6) == []


def test_old_file_is_stale(tmp_path):
    f = tmp_path / "dump.sql.gz"
    f.write_text("x")
    old = time.time() - 10 * 3600
    os.utime(f, (old, old))
    problems = freshness.stale([str(f)], 6)
    assert len(problems) == 1 and problems[0].startswith("stale (10.0h old)")


def test_missing_file(tmp_path):
    assert freshness.stale([str(tmp_path / "nope")], 6) == [f"missing: {tmp_path / 'nope'}"]


def test_glob_uses_newest_match(tmp_path):
    old, new = tmp_path / "a.dump", tmp_path / "b.dump"
    old.write_text("x")
    new.write_text("x")
    t = time.time() - 48 * 3600
    os.utime(old, (t, t))
    assert freshness.stale([str(tmp_path / "*.dump")], 6) == []
