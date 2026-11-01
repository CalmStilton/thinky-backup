import os

import pytest

from restore_support import World, gz  # noqa: F401

root_only = pytest.mark.skipif(os.geteuid() != 0, reason="ownership tests need root")

SNAP = {
    "/src/opt/sonarr/config.xml": "NEW-CONFIG",
    "/src/opt/sonarr/Backups/scheduled/b.zip": "zip",
    "/src/opt/sonarr/sonarr.db-wal": "stale wal",
    "/src/opt/sonarr/sonarr.db-shm": "stale shm",
    "/scratch/sqlite/src/opt/sonarr/sonarr.db": "CLEAN-DB",
    "/src/opt/other/x": "untouched",
    "/src/vol/kuma_data/note.txt": "kuma",
    "/scratch/sqlite/src/vol/kuma_data/kuma.db": "KUMA-CLEAN",
}


def setup_live(world):
    world.live("opt/sonarr/config.xml", "OLD-CONFIG", owner=(1000, 1000) if os.geteuid() == 0 else None)
    world.live("opt/sonarr/sonarr.db", "OLD-DB", owner=(1000, 1000) if os.geteuid() == 0 else None)
    world.live("opt/other/x", "live-other")


def test_dry_run_changes_nothing(world):
    world.backup("vm100", "configs", SNAP)
    setup_live(world)
    r = world.run("app", "--host", "vm100", "--app", "sonarr", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "Dry run" in r.stdout and "sonarr.db" not in r.stderr
    assert (world.root / "opt/sonarr/config.xml").read_text() == "OLD-CONFIG"
    assert world.aside("opt/sonarr") == []
    assert not list((world.root / "var/tmp").glob("thinky-restore-*"))      # the staging folder is tidied up


def test_refuses_without_yes(world):
    world.backup("vm100", "configs", SNAP)
    setup_live(world)
    world.set_running("sonarr")
    world.mount("sonarr", "/config", "/opt/sonarr")
    r = world.run("app", "--host", "vm100", "--app", "sonarr", stdin="no\n")
    assert r.returncode == 1 and "not confirmed" in r.stderr
    assert (world.root / "opt/sonarr/config.xml").read_text() == "OLD-CONFIG"
    assert world.aside("opt/sonarr") == []
    assert world.running() == ["sonarr"]
    assert not any(c[0] == "stop" for c in world.docker_calls())


def test_restore_replaces_moves_aside_and_overlays_the_database(world):
    world.backup("vm100", "configs", SNAP)
    setup_live(world)
    world.set_running("sonarr", "unrelated")
    world.mount("sonarr", "/config", "/opt/sonarr")
    world.mount("unrelated", "/data", "/srv/else")
    r = world.run("app", "--host", "vm100", "--app", "sonarr", stdin="yes\n")
    assert r.returncode == 0, r.stderr
    live = world.root / "opt/sonarr"
    assert (live / "config.xml").read_text() == "NEW-CONFIG"
    assert (live / "sonarr.db").read_text() == "CLEAN-DB"
    assert not (live / "sonarr.db-wal").exists() and not (live / "sonarr.db-shm").exists()
    (aside,) = world.aside("opt/sonarr")
    assert (aside / "config.xml").read_text() == "OLD-CONFIG" and (aside / "sonarr.db").read_text() == "OLD-DB"
    assert (world.root / "opt/other/x").read_text() == "live-other"       # neighbours untouched
    calls = [c[:2] for c in world.docker_calls() if c[0] in ("stop", "start")]
    assert calls == [["stop", "sonarr"], ["start", "sonarr"]]
    assert world.running() == ["unrelated", "sonarr"]
    assert "To undo:" in r.stdout and str(aside) in r.stdout


@root_only
def test_ownership_is_kept_and_the_database_takes_the_old_owner(world):
    world.backup("vm100", "configs", SNAP, owners={"/src/opt/sonarr/config.xml": (1234, 5678)})
    setup_live(world)
    r = world.run("app", "--host", "vm100", "--app", "sonarr", stdin="yes\n")
    assert r.returncode == 0, r.stderr
    cfg = (world.root / "opt/sonarr/config.xml").stat()
    db = (world.root / "opt/sonarr/sonarr.db").stat()
    assert (cfg.st_uid, cfg.st_gid) == (1234, 5678)
    assert (db.st_uid, db.st_gid) == (1000, 1000)


def test_a_second_restore_in_the_same_minute_does_not_clobber_the_first_aside(world):
    world.backup("vm100", "configs", SNAP)
    setup_live(world)
    for _ in range(2):
        assert world.run("app", "--host", "vm100", "--app", "sonarr", stdin="yes\n").returncode == 0
    assert len(world.aside("opt/sonarr")) == 2


def test_named_volume_app_goes_into_the_docker_volume_dir(world):
    world.backup("vm100", "configs", SNAP)
    world.live("var/lib/docker/volumes/kuma_data/_data/note.txt", "OLD")
    world.live("var/lib/docker/volumes/kuma_data/_data/kuma.db", "OLD-DB")
    r = world.run("app", "--host", "vm100", "--app", "vol/kuma_data", stdin="yes\n")
    assert r.returncode == 0, r.stderr
    data = world.root / "var/lib/docker/volumes/kuma_data/_data"
    assert (data / "note.txt").read_text() == "kuma" and (data / "kuma.db").read_text() == "KUMA-CLEAN"
    assert len(list((data.parent).glob("_data.before-restore-*"))) == 1


def test_app_name_in_both_places_must_be_qualified(world):
    world.backup("vm100", "configs", {"/src/opt/dup/a": "1", "/src/vol/dup/b": "2"})
    r = world.run("app", "--host", "vm100", "--app", "dup")
    assert r.returncode == 1 and "opt/dup or vol/dup" in r.stderr


def test_unknown_app_is_reported(world):
    world.backup("vm100", "configs", SNAP)
    r = world.run("app", "--host", "vm100", "--app", "nope")
    assert r.returncode == 1 and "no app called 'nope'" in r.stderr


def test_app_with_no_sqlite_copy_restores(world):
    world.backup("vm100", "configs", SNAP)
    r = world.run("app", "--host", "vm100", "--app", "other", stdin="yes\n")
    assert r.returncode == 0, r.stderr
    assert (world.root / "opt/other/x").read_text() == "untouched"


def test_unmapped_native_style_path_needs_a_map(world, mapfile):
    world.backup("frigate", "configs", {"/src/frigate/config/c.yml": "cfg", "/scratch/sqlite/src/frigate/config/frigate.db": "DB"})
    r = world.run("app", "--host", "frigate", "--app", "/src/frigate/config")
    assert r.returncode == 1 and "see --map" in r.stderr
    r = world.run("app", "--host", "frigate", "--app", "/src/frigate/config", "--map", mapfile, stdin="yes\n")
    assert r.returncode == 0, r.stderr
    assert (world.root / "opt/frigate/config/frigate.db").read_text() == "DB"


def two_snapshots(world):
    world.backup("vm100", "configs", {"/src/opt/old/f": "1"})
    world.backup("vm100", "configs", {"/src/opt/new/f": "2"})


def test_unknown_host_says_so(world):
    two_snapshots(world)
    r = world.run("app", "--host", "nope", "--app", "new")
    assert r.returncode == 1 and "no 'configs' snapshots found for host 'nope'" in r.stderr


def test_snapshot_chosen_by_id_prefix(world):
    two_snapshots(world)
    ids = [ln.split()[0] for ln in world.run("snapshots", "--host", "vm100").stdout.splitlines() if ln.startswith("  ")]
    oldest = ids[0]
    r = world.run("app", "--host", "vm100", "--app", "old", "--snapshot", oldest[:6], "--dry-run")
    assert r.returncode == 0, r.stderr
    assert oldest in r.stdout
