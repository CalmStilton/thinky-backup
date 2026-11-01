from restore_support import AWS_ID, AWS_SECRET, PASSWORD, SECRETS, World, gz  # noqa: F401

FILES = {"/src/opt/app/f.txt": "hello"}


def test_prompts_use_the_card_wording_and_never_echo_secrets(world, tmp_path):
    world.backup("vm100", "configs", FILES)
    conf = tmp_path / "restore.conf"
    conf.write_text(f"CONFIGS_REPOSITORY={world.repo}\n")
    r = world.run("snapshots", stdin=f"{PASSWORD}\n{AWS_ID}\n{AWS_SECRET}\n",
                  RESTIC_REPOSITORY=None, RESTIC_PASSWORD=None, AWS_ACCESS_KEY_ID=None,
                  AWS_SECRET_ACCESS_KEY=None, THINKY_RESTORE_CONF=str(conf))
    assert r.returncode == 0, r.stderr
    for label in ("Configs RESTIC_PASSWORD (card item 1)", "R2 Access Key ID (card item 2)",
                  "R2 Secret Access Key (card item 2)"):
        assert label in r.stderr
    assert f"Repository: {world.repo}" in r.stdout
    assert "Machine: vm100" in r.stdout
    for s in SECRETS:
        assert s not in r.stdout + r.stderr


def test_repository_url_is_shown_without_embedded_password():
    import subprocess
    from restore_support import SCRIPT
    r = subprocess.run(["bash", "-c", f"source {SCRIPT}; RESTIC_REPOSITORY=rest:https://user:hunter2@host/repo; tr_show_repo"],
                       capture_output=True, text=True)
    assert r.stdout.strip() == "rest:https://host/repo"


def test_missing_endpoint_points_at_the_card(world):
    r = world.run("snapshots", stdin="\n\n", RESTIC_REPOSITORY=None)
    assert r.returncode == 1 and "card, item 2" in r.stderr


def test_picks_the_running_backup_container(world):
    world.backup("vm100", "configs", FILES)
    world.set_running("backup-configs")
    world.mount("backup-configs", "/scratch", str(world.dock / "ctr-scratch"))
    r = world.run("snapshots", TR_BACKEND="", RESTIC_PASSWORD=None, RESTIC_REPOSITORY=None, AWS_ACCESS_KEY_ID=None,
                  AWS_SECRET_ACCESS_KEY=None, FAKE_CTR_RESTIC_PASSWORD=PASSWORD, FAKE_CTR_RESTIC_REPOSITORY=str(world.repo))
    assert r.returncode == 0, r.stderr
    assert "backup container backup-configs" in r.stdout
    assert ["exec", "backup-configs", "restic", "snapshots", "--compact", "--tag", "configs"] in world.docker_calls()
    assert "Repository:" not in r.stdout          # nothing was asked for


def test_image_backend_passes_secrets_by_name_only(world):
    world.backup("vm100", "configs", FILES)
    r = world.run("snapshots", TR_BACKEND="image")
    assert r.returncode == 0, r.stderr
    run_calls = [c for c in world.docker_calls() if c[0] == "run"]
    assert run_calls
    for c in run_calls:
        assert "-e" in c and "RESTIC_PASSWORD" in c
        assert not any(s in a for s in SECRETS for a in c)
    for s in SECRETS:
        assert s not in world.restic_log()


def test_unknown_backend_is_refused(world):
    r = world.run("snapshots", TR_BACKEND="carrier-pigeon")
    assert r.returncode == 1 and "unknown backend" in r.stderr
