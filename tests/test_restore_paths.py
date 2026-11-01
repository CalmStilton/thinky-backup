import subprocess

import pytest

from restore_support import SCRIPT


def live_for(script, path, mapfile=None):
    cmd = f'source {script}; tr_load_default_map; tr_live_for "$1"'
    return subprocess.run(["bash", "-c", cmd, "x", path], capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin:/usr/local/bin", "THINKY_RESTORE_MAP": mapfile or ""})


def test_opt_and_volume_paths(script):
    assert live_for(script, "/src/opt/sonarr/config.xml").stdout.strip() == "/opt/sonarr/config.xml"
    assert live_for(script, "/src/vol/kuma_data").stdout.strip() == "/var/lib/docker/volumes/kuma_data/_data"
    assert live_for(script, "/src/vol/kuma_data/kuma.db").stdout.strip() == "/var/lib/docker/volumes/kuma_data/_data/kuma.db"


def test_map_file_entries_apply_including_names_with_spaces(script, tmp_path):
    m = tmp_path / "m"
    m.write_text("# c\n/src/calibre-library=/opt/calibre/config/Calibre Library\n/src/audiobooks=/srv/media/audiobooks\n")
    assert live_for(script, "/src/calibre-library/a/b", str(m)).stdout.strip() == "/opt/calibre/config/Calibre Library/a/b"
    assert live_for(script, "/src/audiobooks", str(m)).stdout.strip() == "/srv/media/audiobooks"


def test_unmapped_src_path_has_no_live_path(script):
    assert live_for(script, "/src/mystery/x").returncode == 1


def test_native_paths_are_taken_as_they_are(script):
    assert live_for(script, "/opt/AdGuardHome/AdGuardHome.yaml").stdout.strip() == "/opt/AdGuardHome/AdGuardHome.yaml"


@pytest.mark.parametrize("bad", ["/src/opt/../etc/passwd", "/src/opt/x/..", "/opt/a/../../etc"])
def test_dotdot_is_refused(script, bad):
    assert live_for(script, bad).returncode == 1


def test_bad_map_lines_are_refused(script, tmp_path):
    m = tmp_path / "m"
    m.write_text("relative=/abs\n")
    r = live_for(script, "/src/x", str(m))
    assert r.returncode != 0 and "absolute" in r.stderr


def test_the_shipped_map_sits_beside_the_script_and_covers_the_stack():
    expected = {"/src/thames-water/data/f": "/root/thames-water-service/data/f",
                "/src/frigate/config/c": "/opt/frigate/config/c",
                "/src/alfiecodes/projects": "/docker/alfiecodes/projects",
                "/src/audiobooks/A": "/srv/media/audiobooks/A",
                "/src/calibre-library/m.db": "/opt/calibre/config/Calibre Library/m.db"}
    for snap, live in expected.items():
        assert live_for(SCRIPT, snap).stdout.strip() == live
