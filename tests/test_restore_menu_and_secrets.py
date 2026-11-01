import os

from restore_support import AWS_ID, AWS_SECRET, PASSWORD, SECRETS, gz  # noqa: F401


def test_menu_quits_and_rejects_nonsense(world):
    r = world.run(stdin="9\n0\n")
    assert r.returncode == 0
    assert "Rebuild a whole machine" in r.stderr and "Please type a number" in r.stdout


def test_menu_shows_what_is_in_the_backups(world):
    world.backup("vm100", "configs", {"/src/opt/a/f": "1"})
    r = world.run(stdin="5\n0\n")
    assert r.returncode == 0, r.stderr
    assert "Machine: vm100" in r.stdout


def test_menu_walks_through_an_app_restore(world):
    world.backup("vm100", "configs", {"/src/opt/sonarr/config.xml": "NEW", "/src/opt/other/x": "1"})
    world.live("opt/sonarr/config.xml", "OLD")
    # 1 = app, 1 = vm100, 1 = newest backup, 1 = first app (opt/other), then 2nd run picks sonarr
    r = world.run(stdin="1\n1\n1\nopt/sonarr\nyes\n0\n")
    assert r.returncode == 0, r.stderr
    assert (world.root / "opt/sonarr/config.xml").read_text() == "NEW"
    assert world.aside("opt/sonarr")


def test_a_stop_in_the_menu_returns_to_the_menu(world):
    world.backup("vm100", "configs", {"/src/opt/sonarr/config.xml": "NEW"})
    r = world.run(stdin="1\n1\n1\nopt/sonarr\nno\n0\n")
    assert r.returncode == 0
    assert "not confirmed" in r.stderr and not world.aside("opt/sonarr")


def test_no_secret_reaches_output_logs_or_disk_on_any_path(world, tmp_path, mapfile):
    files = {"/src/opt/sonarr/config.xml": "NEW", "/scratch/sqlite/src/opt/sonarr/sonarr.db": "DB",
             "/src/opt/bookstack/db/backups/bookstack-nightly.sql.gz": gz("x")}
    world.backup("vm100", "configs", files)
    results = []
    for backend in ("local", "image"):
        results.append(world.run("app", "--host", "vm100", "--app", "sonarr", "--yes", TR_BACKEND=backend))
        results.append(world.run("db", "--host", "vm100", "--db", "bookstack", "--scratch", TR_BACKEND=backend))
        results.append(world.run("snapshots", TR_BACKEND=backend))
    for r in results:
        assert r.returncode == 0, r.stderr
        blob = world.everything(r)
        for s in SECRETS:
            assert s not in blob


def test_menu_asks_where_an_unmapped_folder_goes(world):
    world.backup("frigate", "configs", {"/src/opt/x/f": "1", "/src/frigate/config/c.yml": "cfg"})
    r = world.run(stdin="1\n1\n1\n/src/frigate/config\n/opt/frigate-new\nyes\n0\n")
    assert r.returncode == 0, r.stderr
    assert "Where on this machine should /src/frigate/config go?" in r.stderr
    assert (world.root / "opt/frigate-new/c.yml").read_text() == "cfg"


def test_menu_unmapped_folder_can_be_skipped_and_dotdot_is_refused(world):
    world.backup("frigate", "configs", {"/src/opt/x/f": "1", "/src/frigate/config/c.yml": "cfg"})
    r = world.run(stdin="1\n1\n1\n/src/frigate/config\n/opt/../etc\n0\n")
    assert "'..' is not allowed" in r.stderr and not (world.root / "etc").exists()


def test_rebuild_in_the_menu_asks_for_unmapped_folders(world):
    world.backup("vm100", "configs", {"/src/opt/a/f": "1", "/src/mystery/data/d": "m"})
    r = world.run(stdin="3\n1\n1\n/srv/mystery\nyes\n0\n")
    assert r.returncode == 0, r.stderr
    assert (world.root / "srv/mystery/data/d").read_text() == "m"
    assert (world.root / "opt/a/f").read_text() == "1"
