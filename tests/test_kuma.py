from urllib.parse import parse_qs, urlsplit

from thinky_backup import kuma


def test_push_url_strips_existing_query_and_encodes():
    url = kuma.push_url("http://k:3001/api/push/abc?status=up&msg=OK&ping=", False, "a b&c")
    parts = urlsplit(url)
    assert parts.path == "/api/push/abc"
    q = parse_qs(parts.query, keep_blank_values=True)
    assert q == {"status": ["down"], "msg": ["a b&c"], "ping": [""]}


def test_push_url_truncates_long_messages():
    q = parse_qs(urlsplit(kuma.push_url("http://k/p", True, "x" * 500)).query)
    assert q["status"] == ["up"] and len(q["msg"][0]) == 200


class FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"{}"


def test_push_calls_opener():
    calls = []
    kuma.push("http://k/p", True, "ok", opener=lambda url, timeout: calls.append((url, timeout)) or FakeResp())
    assert len(calls) == 1 and calls[0][1] == 10 and "status=up" in calls[0][0]


def test_push_without_url_does_nothing():
    kuma.push("", True, "ok", opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("called")))


def test_push_swallows_errors(caplog):
    def boom(url, timeout):
        raise OSError("network down")

    kuma.push("http://k/p", False, "bad", opener=boom)
    assert "Kuma push failed" in caplog.text
