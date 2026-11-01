from restore_support import PASSWORD, SECRETS  # noqa: F401

MEDIA = {
    "/src/audiobooks/Some Author/A Good Title/part1.m4b": "audio1",
    "/src/audiobooks/Some Author/A Good Title/cover.jpg": "img",
    "/src/audiobooks/Other Person/Dull Book/x.m4b": "audio2",
    "/src/calibre-library/Some Author/A Good Title (7)/book.epub": "epub",
    "/scratch/sqlite/src/calibre-library/metadata.db": "META",
}


def test_one_title_is_copied_into_a_folder_and_nothing_else_changes(world, tmp_path):
    world.backup("vm100", "media", MEDIA)
    dest = tmp_path / "out"
    r = world.run("media", "--filter", "good title", "--into", str(dest), "--kind", "media", "--yes")
    assert r.returncode == 0, r.stderr
    assert (dest / "audiobooks/Some Author/A Good Title/part1.m4b").read_text() == "audio1"
    assert (dest / "calibre-library/Some Author/A Good Title (7)/book.epub").read_text() == "epub"
    assert not (dest / "audiobooks/Other Person").exists()
    assert "Nothing in your library was changed" in r.stdout


def test_existing_files_are_kept(world, tmp_path):
    world.backup("vm100", "media", MEDIA)
    dest = tmp_path / "out"
    keep = dest / "audiobooks/Some Author/A Good Title/part1.m4b"
    keep.parent.mkdir(parents=True)
    keep.write_text("MINE")
    world.run("media", "--filter", "good title", "--into", str(dest))
    assert keep.read_text() == "MINE"


def test_no_match_says_so(world, tmp_path):
    world.backup("vm100", "media", MEDIA)
    r = world.run("media", "--filter", "zzzz", "--into", str(tmp_path / "o"))
    assert r.returncode == 1 and "matches 'zzzz'" in r.stderr


def test_everything_restore_uses_a_one_off_container_and_the_maps(world, tmp_path):
    world.backup("vm100", "media", MEDIA)
    world.set_running("backup-media")
    world.mount("backup-media", "/scratch", str(world.dock / "ctr-scratch"))
    mp = tmp_path / "m"
    mp.write_text("/src/audiobooks=/srv/media/audiobooks\n/src/calibre-library=/opt/calibre/config/Calibre Library\n")
    world.live("opt/calibre/config/Calibre Library/metadata.db", "OLD-META")
    big = tmp_path / "big"
    r = world.run("media", "--all", "--into", str(big), "--map", str(mp), "--yes", TR_BACKEND="",
                  RESTIC_PASSWORD=None, RESTIC_REPOSITORY=None, FAKE_CTR_RESTIC_PASSWORD=PASSWORD,
                  FAKE_CTR_RESTIC_REPOSITORY=str(world.repo))
    assert r.returncode == 0, r.stderr
    assert (world.root / "srv/media/audiobooks/Some Author/A Good Title/part1.m4b").read_text() == "audio1"
    assert (world.root / "opt/calibre/config/Calibre Library/metadata.db").read_text() == "META"
    assert world.aside("opt/calibre/config/Calibre Library")
    runs = [c for c in world.docker_calls() if c[0] == "run"]
    assert runs and not any(s in " ".join(c) for c in runs for s in SECRETS)
    assert not list(big.glob("thinky-restore-*"))


def test_media_prompts_name_the_card_item(world, tmp_path):
    world.backup("vm100", "media", MEDIA)
    gone = dict.fromkeys(["RESTIC_PASSWORD", "RCLONE_CONFIG_GDRIVE_CLIENT_ID", "RCLONE_CONFIG_GDRIVE_CLIENT_SECRET",
                          "RCLONE_CONFIG_GDRIVE_TOKEN", "RCLONE_CONFIG_GDRIVE_ROOT_FOLDER_ID"])
    r = world.run("media", "--filter", "x", "--into", str(tmp_path / "o"), **gone,
                  stdin="\n".join([PASSWORD, "cid", "csecret", "{tok}", "folder"]) + "\n")
    assert "Media RESTIC_PASSWORD (card item 3)" in r.stderr
    assert PASSWORD not in r.stdout + r.stderr
