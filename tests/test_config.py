import pytest

from thinky_backup import config

BASE = {
    "RESTIC_REPOSITORY": "/tmp/repo",
    "RESTIC_PASSWORD": "pw",
    "BACKUP_HOST": "vm100",
    "BACKUP_TAG": "configs",
}


def test_defaults():
    cfg = config.load(dict(BASE))
    assert cfg.host == "vm100" and cfg.tag == "configs"
    assert cfg.sources == [] and cfg.excludes == []
    assert cfg.forget_args == ["--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6"]
    assert cfg.sqlite_scan is True
    assert cfg.scratch == "/scratch"
    assert cfg.fresh_max_age_hours == 6.0
    assert cfg.check_subset == "5%"
    assert cfg.drill_mariadb_table == "entities"
    assert cfg.repository2 == "" and cfg.push_backup == ""


@pytest.mark.parametrize("key", ["RESTIC_REPOSITORY", "RESTIC_PASSWORD", "BACKUP_HOST", "BACKUP_TAG"])
def test_required(key):
    env = dict(BASE)
    del env[key]
    with pytest.raises(config.ConfigError, match=key):
        config.load(env)


def test_lists_skip_blanks_and_comments():
    env = dict(BASE, BACKUP_SOURCES="\n  /src/a  \n# not this\n\n/src/b with space\n")
    assert config.load(env).sources == ["/src/a", "/src/b with space"]


def test_forget_args_are_split():
    env = dict(BASE, FORGET_ARGS="--keep-weekly 4 --keep-monthly 3")
    assert config.load(env).forget_args == ["--keep-weekly", "4", "--keep-monthly", "3"]


@pytest.mark.parametrize("raw,expected", [("false", False), ("0", False), ("YES", True), ("", True)])
def test_sqlite_scan_bool(raw, expected):
    assert config.load(dict(BASE, SQLITE_SCAN=raw)).sqlite_scan is expected


def test_bad_bool():
    with pytest.raises(config.ConfigError, match="SQLITE_SCAN"):
        config.load(dict(BASE, SQLITE_SCAN="maybe"))


def test_bad_max_age():
    with pytest.raises(config.ConfigError, match="FRESH_MAX_AGE_HOURS"):
        config.load(dict(BASE, FRESH_MAX_AGE_HOURS="six"))


def test_repository2_needs_password2():
    with pytest.raises(config.ConfigError, match="RESTIC_PASSWORD2"):
        config.load(dict(BASE, RESTIC_REPOSITORY2="/tmp/repo2"))
    cfg = config.load(dict(BASE, RESTIC_REPOSITORY2="/tmp/repo2", RESTIC_PASSWORD2="pw2"))
    assert cfg.repository2 == "/tmp/repo2" and cfg.password2 == "pw2"


def test_table_name_is_validated():
    with pytest.raises(config.ConfigError, match="DRILL_MARIADB_TABLE"):
        config.load(dict(BASE, DRILL_MARIADB_TABLE="entities; DROP"))


@pytest.mark.parametrize("pattern", ["/data/*/tmp.db", "cache/*.db"])
def test_excludes_the_sqlite_scan_cannot_honour_are_rejected(pattern):
    with pytest.raises(config.ConfigError, match="BACKUP_EXCLUDES"):
        config.load(dict(BASE, BACKUP_EXCLUDES=pattern))


@pytest.mark.parametrize("pattern", [
    "logs", "*.log", "/src/opt/calibre/config/Calibre Library", "MediaCover",
])
def test_excludes_the_sqlite_scan_honours_are_accepted(pattern):
    assert config.load(dict(BASE, BACKUP_EXCLUDES=pattern)).excludes == [pattern]
