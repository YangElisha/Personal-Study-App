"""GET /api/backups (list snapshots) and POST /api/backups/snapshot (take one now).

Neither endpoint ever deletes or restores anything; restoring stays the CLI."""
from __future__ import annotations

import sqlite3

import pytest
from server import snapshots

BAD_ORIGINS = ["null", "https://evil.example", "http://evil.example:8765",
               "http://localhost:9999", "https://localhost:8765", ""]


def names(settings):
    return sorted(p.name for p in settings.backups_dir.iterdir())


def test_list_shows_every_snapshot_newest_first(client, settings):
    # the start-up snapshot exists; add a safety snapshot the way an import makes one
    client.put("/api/store/deck%3A1", content=b'{"a":1}')
    snapshots.take_snapshot(settings, tag="pre-import")
    r = client.get("/api/backups")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["keep"] == settings.backup_keep
    got = {s["name"]: s for s in body["snapshots"]}
    assert set(got) == set(names(settings))
    kinds = sorted(s["kind"] for s in body["snapshots"])
    assert kinds == ["automatic", "pre-import"]
    for s in body["snapshots"]:
        assert s["size"] == (settings.backups_dir / s["name"]).stat().st_size
        assert len(s["time"]) == 19                      # YYYY-MM-DDTHH:MM:SS
    times = [s["time"] for s in body["snapshots"]]
    assert times == sorted(times, reverse=True)
    assert body["last_automatic"] == snapshots.newest_regular_time(
        settings.backups_dir).isoformat(timespec="seconds")


def test_list_with_no_backups_folder(make_client, settings):
    with make_client() as c:
        for p in settings.backups_dir.iterdir():        # our scratch folder only
            p.unlink()
        settings.backups_dir.rmdir()
        r = c.get("/api/backups")
    assert r.json() == {"ok": True, "snapshots": [], "keep": settings.backup_keep,
                        "last_automatic": None}


def test_snapshot_now_is_complete_and_never_prunes(client, settings):
    client.put("/api/store/deck%3A1", content=b'{"a":1}')
    # fill the automatic rotation to its limit
    from datetime import datetime, timedelta
    for i in range(settings.backup_keep + 2):
        snapshots.take_snapshot(settings, now=datetime(2026, 1, 1) + timedelta(days=i))
    before = names(settings)
    assert len(snapshots.regular_snapshots(settings.backups_dir)) == settings.backup_keep
    r = client.post("/api/backups/snapshot", headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200, r.text
    snap = r.json()["snapshot"]
    assert snap["kind"] == "manual" and snap["name"].endswith("-manual.db")
    after = names(settings)
    assert set(before) <= set(after)                     # nothing removed
    assert set(after) - set(before) == {snap["name"]}
    conn = sqlite3.connect(settings.backups_dir / snap["name"])
    try:
        assert conn.execute("SELECT value FROM kv WHERE key='deck:1'").fetchone()[0] == '{"a":1}'
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()
    # two in the same second get distinct names
    r2 = client.post("/api/backups/snapshot")
    assert r2.status_code == 200 and r2.json()["snapshot"]["name"] != snap["name"]
    assert set(after) <= set(names(settings))


@pytest.mark.parametrize("origin", BAD_ORIGINS)
def test_snapshot_from_another_origin_refused(client, settings, origin):
    before = names(settings)
    r = client.post("/api/backups/snapshot", headers={"Origin": origin})
    assert r.status_code == 403 and r.json()["error"] == "forbidden_origin"
    assert names(settings) == before


def test_no_delete_or_restore_routes(client, settings):
    name = names(settings)[0]
    before = names(settings)
    for method, path in [("DELETE", f"/api/backups/{name}"), ("DELETE", "/api/backups"),
                         ("POST", f"/api/backups/{name}/restore"), ("POST", "/api/backups/restore"),
                         ("PUT", f"/api/backups/{name}")]:
        r = client.request(method, path)
        assert r.status_code in (404, 405), (method, path, r.status_code)
    assert names(settings) == before
