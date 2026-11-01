import subprocess

from restore_support import SCRIPT


def bash(cmd, cwd):
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True)


def test_env_file_is_read_literally_never_executed(tmp_path):
    envf = tmp_path / "env"
    envf.write_text("RESTIC_PASSWORD=pw(abc)def;touch X\nexport AWS_ACCESS_KEY_ID='quoted id'\nOTHER=1\n")
    cmd = (f"source {SCRIPT}; confirm() {{ return 0; }}; THINKY_RESTORE_ENV_FILE={envf}; unset RESTIC_PASSWORD; "
           "tr_offer_env_file; printf '%s|%s|%s' \"$RESTIC_PASSWORD\" \"$AWS_ACCESS_KEY_ID\" \"${OTHER:-}\"")
    r = bash(cmd, tmp_path)
    assert r.stdout == "pw(abc)def;touch X|quoted id|" and r.stderr == ""
    assert not (tmp_path / "X").exists()


def test_a_signal_restarts_containers_stopped_before_anything_was_replaced(tmp_path):
    log = tmp_path / "docker.log"
    cmd = (f"source {SCRIPT}; docker() {{ echo \"$@\" >> {log}; }}; TR_STOPPED=(web db); kill -TERM $$")
    r = bash(cmd, tmp_path)
    assert r.returncode == 143
    assert "Starting the containers that were stopped: web db" in r.stderr
    assert log.read_text().splitlines() == ["start web db"]


def test_a_signal_after_replacement_warns_and_leaves_them_stopped(tmp_path):
    log = tmp_path / "docker.log"
    cmd = (f"source {SCRIPT}; docker() {{ echo \"$@\" >> {log}; }}; TR_STOPPED=(web); TR_ASIDE_LIST=(x); kill -INT $$")
    r = bash(cmd, tmp_path)
    assert r.returncode == 130
    assert "left stopped: web" in r.stderr
    assert not log.exists()


def test_env_file_keys_with_subscripts_are_not_evaluated(tmp_path):
    envf = tmp_path / "env"
    envf.write_text("RCLONE_CONFIG_GDRIVE_X[$(touch PWNED)]=1\nRESTIC_PASSWORD=\"abc\"\r\n")
    cmd = (f"source {SCRIPT}; confirm() {{ return 0; }}; THINKY_RESTORE_ENV_FILE={envf}; unset RESTIC_PASSWORD; "
           "tr_offer_env_file; printf '%s' \"$RESTIC_PASSWORD\"")
    r = bash(cmd, tmp_path)
    assert r.stdout == "abc" and r.stderr == ""
    assert not (tmp_path / "PWNED").exists()
