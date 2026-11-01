from restore_support import SECRETS, gz  # noqa: F401

BOOKSTACK = {"/src/opt/bookstack/db/backups/bookstack-nightly.sql.gz": gz("DROP TABLE IF EXISTS entities;")}
READMEABOOK = {"/src/opt/readmeabook/config/backups/readmeabook-nightly.dump": b"PGDMP-fake"}


def cmds(world):
    return [c for c in world.docker_calls() if c[0] in ("run", "exec", "rm")]


def test_scratch_load_never_touches_the_live_database(world):
    world.backup("vm100", "configs", BOOKSTACK)
    r = world.run("db", "--host", "vm100", "--db", "bookstack", "--scratch")
    assert r.returncode == 0, r.stderr
    assert "has 42 rows" in r.stdout
    run = next(c for c in cmds(world) if c[0] == "run")
    assert "--network" in run and "none" in run
    assert not any("bookstack_db" in " ".join(c) for c in cmds(world))
    loaded = next(p for p in sorted(world.dock.glob("stdin-*")))
    assert loaded.read_bytes() == b"DROP TABLE IF EXISTS entities;"
    assert ["rm", "-f"] == next(c for c in cmds(world) if c[0] == "rm")[:2]


def test_postgres_scratch_check(world):
    world.backup("vm100", "configs", READMEABOOK)
    r = world.run("db", "--host", "vm100", "--db", "readmeabook", "--scratch")
    assert r.returncode == 0, r.stderr
    assert "tables" in r.stdout


def test_live_load_saves_the_current_database_first_and_needs_yes(world):
    world.backup("vm100", "configs", BOOKSTACK)
    refused = world.run("db", "--host", "vm100", "--db", "bookstack", stdin="no\n")
    assert refused.returncode == 1 and "not confirmed" in refused.stderr
    assert not any(c[0] == "exec" for c in world.docker_calls())
    r = world.run("db", "--host", "vm100", "--db", "bookstack", stdin="yes\n")
    assert r.returncode == 0, r.stderr
    execs = [c for c in world.docker_calls() if c[0] == "exec"]
    assert "mariadb-dump" in " ".join(execs[0]) and "mariadb -u" in " ".join(execs[1])
    assert all(c[2] == "bookstack_db" or c[1] == "bookstack_db" for c in execs[:2])
    saved = list((world.root / "opt/bookstack/db/backups").glob("bookstack-before-restore-*.sql.gz"))
    assert len(saved) == 1
    assert "$MYSQL_PASSWORD" in " ".join(execs[0]) and not any(s in " ".join(execs[0] + execs[1]) for s in SECRETS)
    assert next(p for p in sorted(world.dock.glob("stdin-*"))).read_bytes() == b"DROP TABLE IF EXISTS entities;"


def test_a_failed_save_stops_before_loading(world):
    world.backup("vm100", "configs", BOOKSTACK)
    r = world.run("db", "--host", "vm100", "--db", "bookstack", "--yes", FAKE_DOCKER_FAIL="mariadb-dump")
    assert r.returncode == 1 and "nothing was changed" in r.stderr
    assert not any("mariadb -u" in " ".join(c) for c in world.docker_calls() if c[0] == "exec")


def test_readmeabook_live_sequence(world):
    world.backup("vm100", "configs", READMEABOOK)
    world.live("opt/readmeabook/config/backups/.keep", "")
    r = world.run("db", "--host", "vm100", "--db", "readmeabook", stdin="yes\n")
    assert r.returncode == 0, r.stderr
    execs = [" ".join(c) for c in world.docker_calls() if c[0] == "exec"]
    assert "pg_dump -Fc -f /app/config/backups/readmeabook-before-restore-" in execs[0]
    assert "pg_restore --clean --if-exists -d readmeabook /app/config/backups/readmeabook-restored-" in execs[1]
    restored = list((world.root / "opt/readmeabook/config/backups").glob("readmeabook-restored-*.dump"))
    assert len(restored) == 1 and restored[0].read_bytes() == b"PGDMP-fake"
    assert (restored[0].stat().st_mode & 0o777) == 0o644


def test_dry_run_only_checks_the_dump(world):
    world.backup("vm100", "configs", BOOKSTACK)
    r = world.run("db", "--host", "vm100", "--db", "bookstack", "--dry-run")
    assert r.returncode == 0 and "Dry run" in r.stdout
    assert world.docker_calls() == []


def test_damaged_dump_is_caught(world):
    world.backup("vm100", "configs", {"/src/opt/bookstack/db/backups/bookstack-nightly.sql.gz": b"not gzip"})
    r = world.run("db", "--host", "vm100", "--db", "bookstack", "--dry-run")
    assert r.returncode == 1 and "damaged" in r.stderr


def test_unknown_database(world):
    r = world.run("db", "--host", "vm100", "--db", "mystery")
    assert r.returncode == 1
