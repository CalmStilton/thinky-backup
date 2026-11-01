import shutil
import subprocess

import pytest

from restore_support import SCRIPT


def run(*args, **kw):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, **kw)


def test_help_lists_every_command():
    r = run("--help")
    assert r.returncode == 0
    for word in ("snapshots", "app", "db", "host", "media", "before-restore"):
        assert word in r.stdout


def test_unknown_command_is_refused():
    r = run("explode")
    assert r.returncode == 1 and "unknown command" in r.stderr


def test_unknown_option_is_refused():
    r = run("app", "--nonsense")
    assert r.returncode == 1 and "unknown option" in r.stderr


def test_refuses_to_run_with_xtrace_on():
    r = subprocess.run(["bash", "-x", str(SCRIPT), "--help"], capture_output=True, text=True)
    assert r.returncode == 2 and "xtrace" in r.stderr



def test_non_root_is_told_to_use_sudo():
    cmd = f"id() {{ echo 1000; }}; source {SCRIPT}; TR_ROOT=''; tr_need_root"
    r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    assert r.returncode == 1 and "sudo" in r.stderr


def test_the_tool_holds_no_site_specific_values():
    text = SCRIPT.read_text().lower()
    for word in ("lukmor", "192.168", "daa7be88", "thinky-configs", "cloudflarestorage"):
        assert word not in text, word
