import http.server
import os
import pathlib
import subprocess
import threading
from urllib.parse import parse_qs, urlsplit

import pytest

SCRIPT = pathlib.Path(__file__).parent.parent / "native" / "thinky-backup-native.sh"


@pytest.fixture
def kuma_server():
    hits = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(parse_qs(urlsplit(self.path).query, keep_blank_values=True))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/api/push/x?status=up&msg=OK&ping=", hits
    srv.shutdown()


def run_native(tmp_path, repo, push):
    conf = tmp_path / "conf"
    conf.mkdir(exist_ok=True)
    data = tmp_path / "adguard"
    (data / "data").mkdir(parents=True, exist_ok=True)
    (data / "AdGuardHome.yaml").write_text("dns: {}")
    (data / "data" / "stats.db").write_text("big")
    (conf / "sources.txt").write_text(f"# AdGuard\n{data}\n")
    (conf / "excludes.txt").write_text(f"{data}/data/stats.db\n")
    env = {**os.environ, "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD": "test",
           "RESTIC_CACHE_DIR": str(tmp_path / "cache"), "BACKUP_HOST": "adguard", "BACKUP_TAG": "configs",
           "KUMA_PUSH_BACKUP": push, "CONF_DIR": str(conf)}
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True), env, data


def test_native_ok(tmp_path, kuma_server):
    url, hits = kuma_server
    repo = tmp_path / "repo"
    subprocess.run(["restic", "init"], check=True, capture_output=True,
                   env={**os.environ, "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD": "test"})
    result, env, data = run_native(tmp_path, repo, url)
    assert result.returncode == 0, result.stderr
    assert hits[-1]["status"] == ["up"] and hits[-1]["msg"] == ["adguard/configs backup ok"]
    listing = subprocess.run(["restic", "ls", "latest"], env=env, capture_output=True, text=True).stdout
    assert str(data / "AdGuardHome.yaml") in listing and "stats.db" not in listing


def test_native_reports_down_on_failure(tmp_path, kuma_server):
    url, hits = kuma_server
    result, _, _ = run_native(tmp_path, tmp_path / "not-a-repo", url)
    assert result.returncode == 1
    assert hits[-1]["status"] == ["down"]
