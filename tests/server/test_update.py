"""In-app update (server/update.py): offered only for a newer, complete build; installing takes a
snapshot, copies the installer out of dist and starts the silent install with /RELAUNCH=1."""
from __future__ import annotations

import base64
from pathlib import Path
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


# ---- GitHub Releases (a stand-in GitHub; the real one is never contacted) --------------------
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FakeGitHub:
    def __init__(self, repo="me/MonoSpace"):
        self.repo, self.hits, self.release = repo, [], None
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.hits.append(self.path)
                if outer.release is None:
                    return self._send(404, b'{"message": "Not Found"}')
                if self.path == f"/repos/{outer.repo}/releases/latest":
                    return self._send(200, json.dumps(outer.release["json"]).encode())
                body = outer.release["files"].get(self.path)
                return self._send(200, body) if body is not None else self._send(404, b"nope")

            def _send(self, code, body):
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def publish(self, build, built_at, installer=b"new installer", sha=None, notes="## What's new\n- Faster builds"):
        info = {"version": "1.1.0", "build": build, "built_at": built_at, "commit": "abc",
                "sha256": sha or hashlib.sha256(installer).hexdigest()}
        self.release = {"json": {"tag_name": "v1.1.0", "name": "MonoSpace 1.1", "body": notes,
                                 "published_at": "2026-10-02T00:00:00Z", "html_url": "https://example/rel",
                                 "assets": [{"name": update.SETUP_NAME, "browser_download_url": self.url + "/dl/setup.exe"},
                                            {"name": update.SETUP_INFO, "browser_download_url": self.url + "/dl/setup.json"}]},
                        "files": {"/dl/setup.exe": installer, "/dl/setup.json": json.dumps(info).encode()}}


@pytest.fixture
def github(monkeypatch):
    g = FakeGitHub()
    monkeypatch.setenv("MONOSPACE_UPDATE_API", g.url)
    update._gh_cache.update(at=0.0, repo="", result=None)
    yield g
    g.server.shutdown()
    update._gh_cache.update(at=0.0, repo="", result=None)


def gh_stamp(tmp_path):
    stamp(tmp_path, "b1", "2026-10-01T01:00:00Z", update_repo="me/MonoSpace", update_dir=str(tmp_path / "no-dist"))


def test_a_newer_github_release_is_offered_with_its_notes(tmp_path, github):
    gh_stamp(tmp_path)
    github.publish("b2", "2026-10-02T01:00:00Z")
    a = update.check(tmp_path)["available"]
    assert a["source"] == "github" and a["version"] == "1.1.0" and a["title"] == "MonoSpace 1.1"
    assert "Faster builds" in a["notes"] and "_setup_url" not in a and "_sha256" not in a


def test_same_or_older_release_and_offline_are_quiet(tmp_path, github):
    gh_stamp(tmp_path)
    github.publish("b1", "2026-10-01T01:00:00Z")
    assert update.check(tmp_path, force=True)["reason"] == "up_to_date"
    github.publish("b0", "2026-09-01T01:00:00Z")
    assert update.check(tmp_path, force=True)["reason"] == "up_to_date"
    github.release = None                                   # private repo / no release: 404
    assert update.check(tmp_path, force=True)["available"] is None
    github.server.shutdown()                                # offline
    assert update.check(tmp_path, force=True)["available"] is None


def test_checked_at_most_every_few_hours_and_never_when_online_is_off(tmp_path, github):
    gh_stamp(tmp_path)
    github.publish("b2", "2026-10-02T01:00:00Z")
    update.check(tmp_path); update.check(tmp_path); update.check(tmp_path)
    assert len([h for h in github.hits if h.endswith("/releases/latest")]) == 1
    update._gh_cache.update(at=0.0, repo="", result=None)
    n = len(github.hits)
    assert update.check(tmp_path, online=False)["available"] is None and len(github.hits) == n


def test_no_update_repo_means_no_online_check(tmp_path, github):
    stamp(tmp_path, "b1", "2026-10-01T01:00:00Z", update_dir=str(tmp_path / "no-dist"))
    assert update.check(tmp_path)["reason"] == "no_source" and not github.hits


def test_install_from_github_downloads_and_verifies(tmp_path, settings, github):
    gh_stamp(tmp_path)
    github.publish("b2", "2026-10-02T01:00:00Z", installer=b"the real new installer")
    ran = []
    r = update.install(settings, tmp_path, spawn=ran.append)
    assert r["ok"] and r["build"] == "b2" and ran
    script = base64.b64decode(ran[0][-1]).decode("utf-16-le")
    setup = script.split("& '", 1)[1].split("'", 1)[0]
    assert Path(setup).read_bytes() == b"the real new installer"


def test_a_tampered_download_is_refused(tmp_path, settings, github):
    gh_stamp(tmp_path)
    github.publish("b2", "2026-10-02T01:00:00Z", installer=b"evil", sha="0" * 64)
    ran = []
    with pytest.raises(update.UpdateError, match="doesn't match"):
        update.install(settings, tmp_path, spawn=ran.append)
    assert not ran


def test_the_project_folder_comes_before_github(tmp_path, github):
    dist = tmp_path / "dist"
    stamp(tmp_path, "b1", "2026-10-01T01:00:00Z", update_repo="me/MonoSpace", update_dir=str(dist))
    release(dist, "b3", "2026-10-03T01:00:00Z")
    github.publish("b2", "2026-10-02T01:00:00Z")
    assert update.check(tmp_path)["available"]["source"] == "local" and not github.hits
