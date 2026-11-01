from restore_support import World  # noqa: F401


def two_snapshots(world):
    world.backup("vm100", "configs", {"/src/opt/old/f": "1"})
    world.backup("vm100", "configs", {"/src/opt/new/f": "2", "/src/vol/kuma/k": "3"})
    world.backup("frigate", "configs", {"/src/frigate/config/c": "4"})


def test_snapshots_lists_each_machine_with_date_and_size(world):
    two_snapshots(world)
    r = world.run("snapshots")
    assert r.returncode == 0, r.stderr
    assert "Server: vm100" in r.stdout and "Server: frigate" in r.stdout
    assert r.stdout.count("20") >= 3          # a date on every line


def test_snapshots_can_be_limited_to_a_machine_and_filtered(world):
    two_snapshots(world)
    r = world.run("snapshots", "--host", "vm100", "--filter", "kuma")
    assert "Server: frigate" not in r.stdout
    assert "/src/vol/kuma/k" in r.stdout


def test_wrong_password_shows_restic_error(world):
    two_snapshots(world)
    r = world.run("snapshots", RESTIC_PASSWORD="wrong")
    assert r.returncode != 0 and "password" in r.stderr.lower()
