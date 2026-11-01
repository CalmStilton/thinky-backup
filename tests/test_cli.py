import pytest

from thinky_backup import cli, config, kuma

BASE = {"RESTIC_REPOSITORY": "/r", "RESTIC_PASSWORD": "p", "BACKUP_HOST": "h", "BACKUP_TAG": "t"}


def test_crontab_lists_each_configured_job():
    cfg = config.load(dict(BASE, BACKUP_CRON="30 3 * * *", CHECK_CRON="0 5 * * 0"))
    assert cli.crontab(cfg) == "30 3 * * * thinky-backup backup\n0 5 * * 0 thinky-backup check\n"


def test_crontab_needs_a_schedule():
    with pytest.raises(config.ConfigError, match="BACKUP_CRON"):
        cli.crontab(config.load(dict(BASE)))


def test_usage(capsys):
    assert cli.main(["nonsense"]) == 2
    assert "usage" in capsys.readouterr().err


def test_missing_config_exits_2(monkeypatch):
    for key in BASE:
        monkeypatch.delenv(key, raising=False)
    assert cli.main(["backup"]) == 2


def test_config_error_in_job_pushes_down(monkeypatch):
    for k, v in dict(BASE, KUMA_PUSH_BACKUP="http://kuma/b").items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BACKUP_SOURCES", raising=False)
    calls = []
    monkeypatch.setattr(kuma, "push", lambda url, ok, msg: calls.append((url, ok, msg)))
    assert cli.main(["backup"]) == 2
    assert calls and calls[0][0] == "http://kuma/b" and calls[0][1] is False
    assert "BACKUP_SOURCES" in calls[0][2]


def test_crash_in_job_pushes_down_and_reraises(monkeypatch):
    for k, v in dict(BASE, KUMA_PUSH_CHECK="http://kuma/c").items():
        monkeypatch.setenv(k, v)
    calls = []
    monkeypatch.setattr(kuma, "push", lambda url, ok, msg: calls.append((url, ok, msg)))

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(cli.jobs, "check", boom)
    with pytest.raises(RuntimeError):
        cli.main(["check"])
    assert calls == [("http://kuma/c", False, "check crashed: disk on fire")]
