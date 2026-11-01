import os

from restore_support import World  # noqa: F401

VM100 = {
    "/src/opt/sonarr/config.xml": "S",
    "/src/opt/ofelia/config.ini": "O",
    "/src/vol/portainer_data/compose/37/docker-compose.yml": "stack37",
    "/src/vol/kuma_data/note.txt": "k",
    "/src/thames-water/data/f.csv": "w",
    "/scratch/sqlite/src/opt/sonarr/sonarr.db": "SDB",
    "/scratch/sqlite/src/vol/kuma_data/kuma.db": "KDB",
    "/scratch/sqlite/src/thames-water/data/t.db": "TDB",
}


def test_dry_run_lists_the_plan_and_changes_nothing(world, mapfile):
    world.backup("vm100", "configs", VM100)
    world.live("opt/sonarr/config.xml", "existing")
    r = world.run("host", "--host", "vm100", "--map", mapfile, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "/src/opt/sonarr ->" in r.stdout and "exists, will be moved aside" in r.stdout
    assert "/root/thames-water-service/data" in r.stdout
    assert (world.root / "opt/sonarr/config.xml").read_text() == "existing"


def test_refuses_without_yes(world, mapfile):
    world.backup("vm100", "configs", VM100)
    r = world.run("host", "--host", "vm100", "--map", mapfile, stdin="no\n")
    assert r.returncode == 1
    assert not (world.root / "opt").exists()


def test_rebuild_lays_everything_down(world, mapfile):
    world.backup("vm100", "configs", VM100)
    world.live("opt/sonarr/config.xml", "existing")
    r = world.run("host", "--host", "vm100", "--map", mapfile, stdin="yes\nno\n")
    assert r.returncode == 0, r.stderr
    root = world.root
    assert (root / "opt/sonarr/config.xml").read_text() == "S"
    assert (root / "opt/sonarr/sonarr.db").read_text() == "SDB"
    assert (root / "opt/ofelia/config.ini").read_text() == "O"
    assert (root / "var/lib/docker/volumes/kuma_data/_data/kuma.db").read_text() == "KDB"
    assert (root / "var/lib/docker/volumes/portainer_data/_data/compose/37/docker-compose.yml").read_text() == "stack37"
    assert (root / "root/thames-water-service/data/f.csv").read_text() == "w"
    assert (root / "root/thames-water-service/data/t.db").read_text() == "TDB"
    (aside,) = world.aside("opt/sonarr")
    assert (aside / "config.xml").read_text() == "existing"
    assert [c for c in world.docker_calls() if c[:2] == ["volume", "create"]]
    assert "start each stack" in r.stdout and "37" in r.stdout
    assert not list((root / "var/tmp").glob("thinky-restore-*"))


def test_portainer_is_started_only_after_a_yes(world, mapfile):
    world.backup("vm100", "configs", VM100)
    world.run("host", "--host", "vm100", "--map", mapfile, stdin="yes\nno\n")
    assert not [c for c in world.docker_calls() if c[0] == "run"]
    other = world.tmp / "again"
    other.mkdir()
    w2 = World(other)       # a fresh machine, to answer yes to both questions
    w2.backup("vm100", "configs", VM100)
    w2.run("host", "--host", "vm100", "--map", mapfile, stdin="yes\nyes\n")
    run = next(c for c in w2.docker_calls() if c[0] == "run")
    assert "portainer_data:/data" in run and "--restart=always" in run


def test_unmapped_paths_are_kept_in_the_stage_not_lost(world):
    world.backup("vm100", "configs", {**VM100})
    r = world.run("host", "--host", "vm100", "--yes", "--stage", str(world.tmp / "big"))
    assert r.returncode == 0, r.stderr
    assert "/src/thames-water has no known live path" in r.stderr
    assert "still in" in r.stdout
    assert list((world.tmp / "big").glob("thinky-restore-*/src/thames-water/data/f.csv"))


def test_native_host_uses_real_paths(world):
    world.backup("adguard", "configs", {"/opt/AdGuardHome/AdGuardHome.yaml": "dns: {}"})
    r = world.run("host", "--host", "adguard", "--yes")
    assert r.returncode == 0, r.stderr
    assert (world.root / "opt/AdGuardHome/AdGuardHome.yaml").read_text() == "dns: {}"
