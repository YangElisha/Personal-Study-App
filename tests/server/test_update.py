"""In-app update (server/update.py): offered only for a newer, complete build; installing takes a
snapshot, copies the installer out of dist and starts the silent install with /RELAUNCH=1."""
from __future__ import annotations

import base64
import json

from server import update


def stamp(folder, build, built_at, **extra):
    info = {"version": "1.0.0", "build": build, "built_at": built_at, "commit": "abc1234", **extra}
    (folder / update.INFO_NAME).write_text(json.dumps(info), encoding="utf-8")
    return info


def release(dist, build, built_at, body=b"installer"):
    dist.mkdir(exist_ok=True)
    (dist / update.SETUP_NAME).write_bytes(body)
    info = {"version": "1.0.0", "build": build, "built_at": built_at, "commit": "def5678",
            "sha256": update.sha256(dist / update.SETUP_NAME)}
    (dist / update.SETUP_INFO).write_text(json.dumps(info), encoding="utf-8")


def test_running_from_source_has_nothing_to_update(tmp_path):
    assert update.check(tmp_path)["reason"] == "source"


def test_a_newer_build_is_offered_the_same_or_older_is_not(tmp_path):
    dist = tmp_path / "dist"
    stamp(tmp_path, "b1", "2026-10-01T01:00:00Z", update_dir=str(dist))
    assert update.check(tmp_path)["reason"] == "no_source"
    release(dist, "b1", "2026-10-01T01:00:00Z")
    assert update.check(tmp_path)["reason"] == "up_to_date"
    release(dist, "b0", "2026-09-30T01:00:00Z")
    assert update.check(tmp_path)["reason"] == "up_to_date"
    release(dist, "b2", "2026-10-01T02:00:00Z")
    r = update.check(tmp_path)
    assert r["reason"] == "" and r["available"]["build"] == "b2" and r["current"]["build"] == "b1"


def test_the_build_record_may_have_a_bom(tmp_path):
    info = {"build": "b1", "built_at": "x"}
    (tmp_path / update.INFO_NAME).write_bytes(b"\xef\xbb\xbf" + json.dumps(info).encode())
    assert update.current_build(tmp_path)["build"] == "b1"


def test_install_snapshots_copies_and_starts_the_silent_installer(tmp_path, settings):
    dist = tmp_path / "dist"
    stamp(tmp_path, "b1", "2026-10-01T01:00:00Z", update_dir=str(dist))
    release(dist, "b2", "2026-10-01T02:00:00Z")
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.db_path.write_bytes(b"")                       # a database to snapshot
    ran = []
    r = update.install(settings, tmp_path, spawn=ran.append)
    assert r["ok"] and r["build"] == "b2" and "pre-update" in r["snapshot"]
    script = base64.b64decode(ran[0][-1]).decode("utf-16-le")
    assert "/VERYSILENT" in script and "/RELAUNCH=1" in script and "Wait-Process" in script
    assert str(dist) not in script                           # runs a copy, not the file in dist


def test_a_half_copied_installer_is_refused(tmp_path, settings):
    dist = tmp_path / "dist"
    stamp(tmp_path, "b1", "2026-10-01T01:00:00Z", update_dir=str(dist))
    release(dist, "b2", "2026-10-01T02:00:00Z")
    (dist / update.SETUP_NAME).write_bytes(b"still copying")
    ran = []
    try:
        update.install(settings, tmp_path, spawn=ran.append)
        assert False, "should refuse"
    except update.UpdateError as e:
        assert "still be building" in str(e)
    assert not ran


def test_update_endpoints_from_source(client):
    assert client.get("/api/update").json()["reason"] == "source"
    r = client.post("/api/update/install")
    assert r.status_code == 409 and "source" in r.json()["message"]
