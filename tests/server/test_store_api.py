"""GET/PUT/DELETE /api/store/{key}, GET /api/store?prefix=, /api/ai, /api/health, static."""
from __future__ import annotations

import time
from urllib.parse import quote

import pytest
from conftest import history, kv_full
from server.settings import BUNDLE_ROOT

ICON = BUNDLE_ROOT / "assets" / "monospace.ico"


def url(key: str) -> str:
    return "/api/store/" + quote(key, safe="")


# (Keys containing "%" are tested against a real uvicorn server in test_live_server.py:
# Starlette's TestClient decodes the path twice, real uvicorn decodes it once.)
KEYS = ["library", "deck:abc", "prog:p02x", "exam:x:y", "a/b/c", "sp ace?#&=+",
        "naïve ✓ 日本", "semi;colon,comma", "a.b..c", "back\\slash"]


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["app"] == "drill"


@pytest.mark.parametrize("key", KEYS)
def test_put_get_roundtrip_special_keys(client, key):
    body = '{"a": 1,  "b": [1, 2.50, "x"], "u": "✓ é"}'      # odd spacing kept verbatim
    r = client.put(url(key), content=body.encode("utf-8"))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "added" and r.json()["key"] == key
    g = client.get(url(key))
    assert g.status_code == 200
    assert g.content.decode("utf-8") == body
    assert g.headers["content-type"].startswith("application/json")
    assert g.headers["x-updated-at"] == r.json()["updated_at"]


def test_missing_is_204_and_stored_null_is_200(client):
    r = client.get(url("deck:none"))
    assert r.status_code == 204 and r.content == b""
    assert client.put(url("deck:null"), content=b"null").status_code == 200
    g = client.get(url("deck:null"))
    assert g.status_code == 200 and g.text == "null"


def test_prefix_list(client):
    for k in ["deck:1", "deck:2", "deckx", "prog:1", "library", "a+b", "a_b", "axb"]:
        client.put(url(k), content=b"1")
    assert client.get("/api/store", params={"prefix": "deck:"}).json() == {"keys": ["deck:1", "deck:2"]}
    assert client.get("/api/store", params={"prefix": "deck"}).json()["keys"] == ["deck:1", "deck:2", "deckx"]
    # _ is literal, not a wildcard (% is checked in test_live_server.py)
    assert client.get("/api/store", params={"prefix": "a+"}).json()["keys"] == ["a+b"]
    assert client.get("/api/store", params={"prefix": "a_"}).json()["keys"] == ["a_b"]
    assert len(client.get("/api/store").json()["keys"]) == 8
    assert client.get("/api/store", params={"prefix": "zzz"}).json() == {"keys": []}


def test_overwrite_keeps_history(client, settings):
    client.put(url("deck:h"), content=b'{"v":1}')
    t1 = client.get(url("deck:h")).headers["x-updated-at"]
    time.sleep(0.01)
    r = client.put(url("deck:h"), content=b'{"v":2}')
    assert r.json()["status"] == "changed"
    assert client.get(url("deck:h")).text == '{"v":2}'
    assert r.json()["updated_at"] > t1
    assert history(settings, "deck:h") == ['{"v":1}']


def test_identical_write_is_noop(client, settings):
    r1 = client.put(url("deck:same"), content=b'{"v":1}')
    time.sleep(0.01)
    r2 = client.put(url("deck:same"), content=b'{"v":1}')
    assert r2.json()["status"] == "unchanged"
    assert r2.json()["updated_at"] == r1.json()["updated_at"]
    assert history(settings, "deck:same") == []
    # a formatting difference is a different text, so it is a real (kept) write
    r3 = client.put(url("deck:same"), content=b'{"v": 1}')
    assert r3.json()["status"] == "changed"
    assert history(settings, "deck:same") == ['{"v":1}']


def test_delete_keeps_history(client, settings):
    client.put(url("exam:d"), content=b'{"paper":[1,2]}')
    r = client.delete(url("exam:d"))
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert client.get(url("exam:d")).status_code == 204
    assert history(settings, "exam:d") == ['{"paper":[1,2]}']
    r = client.delete(url("exam:d"))                      # deleting a missing key: unchanged,
    assert r.status_code == 404 and r.json()["error"] == "not_found"   # still 404
    assert history(settings, "exam:d") == ['{"paper":[1,2]}']


@pytest.mark.parametrize("body", [b"", b"{bad", b"NaN", b'{"x": Infinity}', b"\xff\xfe"])
def test_put_rejects_non_json(client, settings, body):
    r = client.put(url("deck:bad"), content=body)
    assert r.status_code == 400 and r.json()["error"] == "bad_json"
    assert client.get(url("deck:bad")).status_code == 204


def test_empty_key_rejected(client):
    assert client.put("/api/store/", content=b"1").status_code == 400
    assert client.get("/api/store/").status_code == 400


def test_ai_no_model_available(client):
    # conftest: Ollama on a closed port, CLAUDE_CLI=off -> no model at all
    r = client.post("/api/ai", json={"max_tokens": 16,
                                     "messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 503
    body = r.json()
    assert body["type"] == "error" and body["error"]["type"] == "ai_not_configured"
    assert body["error"]["message"]


def test_placeholder_when_no_app(client):
    r = client.get("/")
    assert r.status_code == 200 and "MonoSpace server is running" in r.text


def test_serves_app_dir(make_client, tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "vendor" / "fonts").mkdir(parents=True)
    (app_dir / "index.html").write_text("<p>hello drill</p>", encoding="utf-8")
    (app_dir / "x.js").write_text("1", encoding="utf-8")
    (app_dir / "vendor" / "fonts" / "f.woff2").write_bytes(b"wOF2fake")
    with make_client(app_dir=app_dir) as c:
        r = c.get("/")
        assert "hello drill" in r.text and r.headers["cache-control"] == "no-cache"
        assert c.get("/x.js").text == "1"
        f = c.get("/vendor/fonts/f.woff2")
        assert f.status_code == 200 and f.headers["content-type"] == "font/woff2"
        assert c.get("/api/health").json()["ok"] is True       # API still wins over static
        fav = c.get("/favicon.ico")                  # no icon in app/: the MonoSpace icon
        assert fav.status_code == 200 and fav.content == ICON.read_bytes()


def test_favicon_default_icon_without_app_and_app_icon_when_present(make_client, tmp_path):
    with make_client() as c:
        r = c.get("/favicon.ico")
        assert r.status_code == 200 and r.headers["content-type"] == "image/x-icon"
        assert r.content == ICON.read_bytes() and r.content[:4] == b"\x00\x00\x01\x00"
    app_dir = tmp_path / "app2"
    app_dir.mkdir()
    (app_dir / "index.html").write_text("x", encoding="utf-8")
    (app_dir / "favicon.ico").write_bytes(b"ICO")
    with make_client(app_dir=app_dir) as c:
        r = c.get("/favicon.ico")
        assert r.status_code == 200 and r.content == b"ICO"


def test_api_responses_are_never_cached(client):
    client.put(url("deck:c"), content=b"1")
    for r in (client.get(url("deck:c")), client.get(url("deck:none")),
              client.get("/api/store"), client.get("/api/health"),
              client.put(url("deck:c"), content=b"2"), client.delete(url("deck:c")),
              client.delete(url("deck:c")), client.post("/api/ai"),
              client.put(url("deck:x"), content=b"{bad")):
        assert r.headers["cache-control"] == "no-store", (r.request.method, r.request.url)


def test_foreign_host_refused(client):
    assert client.get("/api/health", headers={"host": "evil.example:8765"}).status_code == 403
    assert client.get("/api/health", headers={"host": "localhost.evil.example"}).status_code == 403


BAD_ORIGINS = ["null", "https://evil.example", "http://evil.example:8765",
               "http://localhost:9999", "https://localhost:8765", "http://127.0.0.1.evil.example",
               ""]


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_state_changes_from_other_origins_refused(client, settings, origin):
    from synth import simple_backup, write_backup
    write_backup(settings.import_dir, "drill-backup-1.json", simple_backup())
    client.put(url("deck:keep"), content=b'{"v":1}')
    h = {"origin": origin}
    r = client.put(url("deck:o"), content=b"1", headers=h)
    assert r.status_code == 403 and r.json()["error"] == "forbidden_origin"
    assert client.get(url("deck:o")).status_code == 204
    r = client.delete(url("deck:keep"), headers=h)
    assert r.status_code == 403
    assert client.get(url("deck:keep")).text == '{"v":1}'
    r = client.post("/api/import", headers=h)
    assert r.status_code == 403
    assert client.get(url("library")).status_code == 204       # nothing imported
    assert client.post("/api/ai", headers=h).status_code == 403
    # reading is not blocked by the server (the browser's CORS rules stop foreign reads)
    assert client.get(url("deck:keep"), headers=h).status_code == 200


@pytest.mark.parametrize("origin", ["http://localhost:8765", "http://127.0.0.1:8765",
                                    "HTTP://LOCALHOST:8765/", None])
def test_own_origin_or_no_origin_may_write(client, origin):
    h = {"origin": origin} if origin is not None else {}
    assert client.put(url("deck:o"), content=b"1", headers=h).status_code == 200
    assert client.delete(url("deck:o"), headers=h).status_code == 200


def test_writes_are_transactions_and_wal(client, settings):
    import sqlite3
    client.put(url("k"), content=b"1")
    conn = sqlite3.connect(settings.db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    assert kv_full(settings)[0][:2] == ("k", "1")


def test_builds_are_counted_per_page_so_the_window_can_ask_before_closing(client):
    assert client.get("/api/builds").json() == {"active": 0}
    assert client.post("/api/builds", json={"page": "a", "active": 2}).json() == {"active": 2}
    assert client.post("/api/builds", json={"page": "b", "active": 1}).json() == {"active": 3}
    assert client.post("/api/builds", json={"page": "a", "active": 0}).json() == {"active": 1}
    assert client.get("/api/builds").json() == {"active": 1}
    assert client.post("/api/builds", content=b"nope").status_code == 400


def test_activity_log_is_appended_and_read_back_newest_first(client, settings):
    assert client.get("/api/logs").json()["events"] == []
    client.post("/api/logs", json={"events": [{"id": "a", "type": "ai"}, {"id": "b", "type": "build"}]})
    client.post("/api/logs", json={"events": [{"id": "c", "type": "crash"}]})
    ev = client.get("/api/logs").json()["events"]
    assert [e["id"] for e in ev] == ["c", "b", "a"]
    assert list((settings.data_dir / "logs").glob("activity-*.jsonl"))
    assert client.post("/api/logs", content=b"{}").status_code == 400


def test_crash_reports_are_saved_listed_and_read(client, settings):
    r = client.post("/api/logs/crash", json={"markdown": "# MonoSpace report: Build stopped\n\nboom"}).json()
    assert (settings.data_dir / "logs" / r["file"]).read_text(encoding="utf-8").endswith("boom")
    listed = client.get("/api/logs/crashes").json()["crashes"]
    assert listed[0]["file"] == r["file"] and listed[0]["title"] == "MonoSpace report: Build stopped"
    assert client.get("/api/logs/crashes/" + r["file"]).text.endswith("boom")
    assert client.get("/api/logs/crashes/..%2F..%2Fdrill.db").status_code == 404
    assert client.get("/api/logs/crashes/drill.db").status_code == 404
