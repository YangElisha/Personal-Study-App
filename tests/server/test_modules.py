"""Module library (Phase 6): POST/GET /api/modules, POST /api/modules/{sha}/deck, MODULES.md,
the register CLI. Synthetic PDFs, scratch DATA_DIR."""
from __future__ import annotations

import hashlib
import http.client
import json
import sqlite3
import tracemalloc

import pytest
from conftest import kv_full
from server import modules
from test_live_server import live  # noqa: F401  (fixture)


def pdf(tag: str, pages: int = 3) -> bytes:
    body = b"".join(b"%d 0 obj << /Type /Page >> endobj\n" % i for i in range(pages))
    return b"%PDF-1.4\n% " + tag.encode() + b"\n" + body + b"%%EOF\n"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def concept(name, fact, topic="T", items=None):
    return {"id": name, "name": name, "topic": topic, "fact": fact, "items": items,
            "pages": [1], "star": False, "qs": []}


def put_deck(client, deck_id, name, concepts, coverage_pages=None):
    deck = {"id": deck_id, "name": name, "concepts": concepts, "cards": []}
    if coverage_pages:
        deck["coverage"] = {"pages": coverage_pages, "content": coverage_pages - 1, "empty": [],
                            "skipped": ["p1 Cover"], "terms": len(concepts), "rows": []}
    assert client.put(f"/api/store/deck:{deck_id}", content=json.dumps(deck)).status_code == 200


def upload(client, data: bytes, name="MODULE2_EXAMPLE.pdf", **kw):
    return client.post("/api/modules", params={"name": name}, content=data,
                       headers={"Content-Type": "application/pdf", **kw.pop("headers", {})}, **kw)


def mods_dir(settings):
    return settings.data_dir / "modules"


def events(settings):
    c = sqlite3.connect(settings.db_path)
    try:
        return c.execute("SELECT sha256, event FROM module_events ORDER BY id").fetchall()
    finally:
        c.close()


V1 = [concept("Risk", "Chance of loss"), concept("Threat", "Potential harm"),
      concept("Asset", "Anything of value")]


def first_version(client, data=None):
    data = data or pdf("v1")
    r = upload(client, data)
    assert r.status_code == 200, r.text
    put_deck(client, "d1", "IA Module 2", V1, coverage_pages=40)
    d = client.post(f"/api/modules/{sha(data)}/deck", json={"deck_id": "d1"})
    assert d.status_code == 200, d.text
    return data, r.json(), d.json()


def test_new_upload_is_stored_and_recorded(client, settings, tmp_path):
    data, up, dk = first_version(client)
    assert up["known"] is False and up["sha256"] == sha(data) and up["previous"] is None
    assert up["stored_name"] == "MODULE2_EXAMPLE.pdf"
    assert (mods_dir(settings) / "MODULE2_EXAMPLE.pdf").read_bytes() == data
    assert dk["first_upload"] is True and dk["terms"] == 3 and dk["pages"] == 40
    assert dk["added"] == ["Risk", "Threat", "Asset"] and dk["status"] == "recorded"
    lst = client.get("/api/modules").json()["modules"]
    assert len(lst) == 1 and lst[0]["deck_id"] == "d1" and lst[0]["deck_name"] == "IA Module 2"
    assert lst[0]["terms"] == 3 and lst[0]["deck_exists"] is True
    # no temp files left behind
    assert sorted(p.name for p in mods_dir(settings).iterdir()) == ["MODULE2_EXAMPLE.pdf"]


def test_same_pdf_again_is_known_no_changes(client, settings):
    data, _, _ = first_version(client)
    before = kv_full(settings)
    r = upload(client, data, name="renamed copy.pdf")
    j = r.json()
    assert r.status_code == 200 and j["known"] is True
    assert j["deck_id"] == "d1" and j["deck_name"] == "IA Module 2" and j["deck_exists"] is True
    assert kv_full(settings) == before                          # no deck, no kv write
    assert sorted(p.name for p in mods_dir(settings).iterdir()) == ["MODULE2_EXAMPLE.pdf"]
    assert len(client.get("/api/modules").json()["modules"]) == 1
    assert events(settings)[-1] == (sha(data), "reupload")
    assert "identical file, no changes" in (settings.data_dir / "MODULES.md").read_text("utf-8")


def test_upload_without_deck_is_not_known(client, settings):
    data = pdf("x")
    upload(client, data)
    j = upload(client, data).json()          # build was interrupted: build again
    assert j["known"] is False and j["resumed"] is True


def test_name_clash_gets_suffix_and_identical_file_reused(client, settings):
    d = mods_dir(settings)
    d.mkdir(exist_ok=True)
    other = pdf("someone else's file")
    (d / "MODULE2_EXAMPLE.pdf").write_bytes(other)
    data = pdf("v1")
    j = upload(client, data).json()
    assert j["stored_name"] == f"MODULE2_EXAMPLE-{sha(data)[:8]}.pdf"
    assert (d / "MODULE2_EXAMPLE.pdf").read_bytes() == other          # not overwritten
    assert (d / j["stored_name"]).read_bytes() == data
    # an identical file already in place (e.g. copied by hand) is reused, not duplicated
    same = pdf("module3")
    (d / "MODULE3_EXAMPLE.pdf").write_bytes(same)
    j3 = upload(client, same, name="MODULE3_EXAMPLE.pdf").json()
    assert j3["stored_name"] == "MODULE3_EXAMPLE.pdf"
    assert len(list(d.glob("MODULE3*"))) == 1


def test_revised_pdf_lists_added_changed_removed(client, settings):
    first_version(client)
    v2 = pdf("v2")
    up = upload(client, v2).json()
    assert up["known"] is False
    assert up["previous"]["deck_id"] == "d1" and up["previous"]["terms"] == ["Risk", "Threat", "Asset"]
    put_deck(client, "d2", "IA Module 2 (rev)", [
        concept("risk", "Chance of loss", topic="Moved"),       # same by norm, only topic moved
        concept("Threat", "Potential  harm to\nassets"),         # content changed
        concept("Vulnerability", "A weakness"),                  # added
    ])                                                           # Asset removed
    d = client.post(f"/api/modules/{sha(v2)}/deck", json={"deck_id": "d2"}).json()
    assert d["first_upload"] is False and d["previous"]["sha256"] == sha(pdf("v1"))
    assert d["added"] == ["Vulnerability"] and d["changed"] == ["Threat"]
    assert d["removed"] == ["Asset"] and d["unchanged"] == 1
    md = (settings.data_dir / "MODULES.md").read_text("utf-8")
    assert "Added (1): Vulnerability" in md and "Changed (1): Threat" in md
    assert "Removed (1): Asset" in md


def test_whitespace_only_difference_is_not_a_change():
    a = concept("X", "one two", items=["a  b"])
    b = concept("x", " one\n two ", items=["a b"])
    assert modules.diff_terms([{"name": "X", "hash": modules.term_hash(a)}],
                              [{"name": "x", "hash": modules.term_hash(b)}])["unchanged"] == 1
    assert modules.norm("Risk-Assessment (RA)") == "riskassessmentra"
    assert modules.norm(None) == ""


def test_deck_report_twice_is_unchanged_and_replacement_is_kept(client, settings):
    data, _, _ = first_version(client)
    again = client.post(f"/api/modules/{sha(data)}/deck", json={"deck_id": "d1"}).json()
    assert again["status"] == "unchanged"
    n = len(events(settings))
    put_deck(client, "d9", "Rebuilt", V1)
    r = client.post(f"/api/modules/{sha(data)}/deck", json={"deck_id": "d9"}).json()
    assert r["status"] == "recorded" and len(events(settings)) == n + 1
    c = sqlite3.connect(settings.db_path)
    detail = json.loads(c.execute("SELECT detail FROM module_events ORDER BY id DESC").fetchone()[0])
    c.close()
    assert detail["replaced"]["deck_id"] == "d1"                  # the old record is kept


def test_deck_report_errors(client):
    assert client.post("/api/modules/" + "0" * 64 + "/deck", json={"deck_id": "d1"}).status_code == 404
    data = pdf("e")
    upload(client, data)
    assert client.post(f"/api/modules/{sha(data)}/deck", json={"deck_id": "nope"}).status_code == 404
    assert client.post(f"/api/modules/{sha(data)}/deck", json={}).status_code == 400
    assert client.post(f"/api/modules/{sha(data)}/deck", content=b"x").status_code == 400


def test_upload_errors(client, settings):
    assert client.post("/api/modules", content=pdf("n")).status_code == 400        # no name
    r = upload(client, b"not a pdf at all")
    assert r.status_code == 415 and r.json()["error"] == "not_pdf"
    r = upload(client, pdf("big"), headers={"Content-Length": str(modules.MAX_UPLOAD + 1)})
    assert r.status_code == 413
    assert [p.name for p in mods_dir(settings).iterdir()] == []    # temp files cleaned up


def test_file_name_header_and_sanitising(client, settings):
    r = client.post("/api/modules", content=pdf("h"),
                    headers={"X-File-Name": "..%5Cevil%3A%20name"})
    assert r.status_code == 200
    assert r.json()["stored_name"] == "evil_ name.pdf"
    assert (mods_dir(settings) / "evil_ name.pdf").is_file()


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:9999"])
def test_foreign_origin_refused(client, settings, origin):
    r = upload(client, pdf("o"), headers={"Origin": origin})
    assert r.status_code == 403 and r.json()["error"] == "forbidden_origin"
    r = client.post("/api/modules/" + "0" * 64 + "/deck", json={"deck_id": "d"},
                    headers={"Origin": origin})
    assert r.status_code == 403
    assert not mods_dir(settings).exists() or not any(mods_dir(settings).iterdir())
    ok = upload(client, pdf("o"), headers={"Origin": "http://127.0.0.1:8765"})
    assert ok.status_code == 200


def test_modules_md_generated_in_both_places(client, settings, tmp_path):
    first_version(client)
    repo_md = (tmp_path / "repo-MODULES.md").read_text("utf-8")
    assert repo_md == (settings.data_dir / "MODULES.md").read_text("utf-8")
    assert repo_md.startswith("# MODULES")
    assert "| MODULE2_EXAMPLE.pdf | IA Module 2 | 3 | 40 |" in repo_md
    assert "first upload" in repo_md and sha(pdf("v1")) in repo_md
    assert "Chance of loss" not in repo_md                     # no study content, names only


def test_default_md_paths_are_repo_and_data_dir(settings):
    from server.settings import REPO_ROOT
    assert modules.default_md_paths(settings) == [REPO_ROOT / "MODULES.md",
                                                  settings.data_dir / "MODULES.md"]


# ---- register CLI -----------------------------------------------------------------------

def test_register_cli(client, settings, tmp_path, capsys):
    put_deck(client, "m2", "IA Module 2", V1, coverage_pages=40)
    d = mods_dir(settings)
    d.mkdir(exist_ok=True)
    data = pdf("backfill", pages=7)
    (d / "MODULE2_EXAMPLE.pdf").write_bytes(data)
    md = [tmp_path / "cli-MODULES.md"]
    out = modules.register(settings, d / "MODULE2_EXAMPLE.pdf", "m2", md_paths=md)
    assert out["sha256"] == sha(data) and out["terms"] == 3 and out["pages"] == 40
    assert out["first_upload"] is True
    assert "IA Module 2" in md[0].read_text("utf-8")
    assert sorted(p.name for p in d.iterdir()) == ["MODULE2_EXAMPLE.pdf"]   # used in place
    # through main(): same file again is a no-op; a different deck is refused
    import server.modules as m
    orig = m.default_md_paths
    m.default_md_paths = lambda s: md
    try:
        assert m.main(["register", str(d / "MODULE2_EXAMPLE.pdf"), "--deck", "m2"]) == 0
        assert "unchanged" in capsys.readouterr().out
        assert m.main(["register", str(d / "MODULE2_EXAMPLE.pdf"), "--deck", "other"]) == 1
        # a PDF outside modules\ is copied in; missing deck refused before any write
        ext = tmp_path / "Module3.pdf"
        ext.write_bytes(pdf("m3", pages=5))
        assert m.main(["register", str(ext), "--deck", "missing"]) == 1
        assert not (d / "Module3.pdf").exists()
        # no coverage in the deck: page count from the PDF itself
        c = sqlite3.connect(settings.db_path)
        c.execute("INSERT INTO kv VALUES('deck:m3', ?, 'x')",
                  (json.dumps({"id": "m3", "name": "IA Module 3", "concepts": V1[:1]}),))
        c.commit()
        c.close()
        assert m.main(["register", str(ext), "--deck", "m3"]) == 0
        assert (d / "Module3.pdf").read_bytes() == ext.read_bytes()
        assert ext.exists()
        lst = {x["deck_id"]: x for x in modules.list_modules(settings)}
        assert lst["m3"]["pages"] == 5 and lst["m2"]["pages"] == 40
        assert m.main(["list"]) == 0
    finally:
        m.default_md_paths = orig


def test_register_refused_while_server_runs(client, settings):
    put_deck(client, "m2", "IA Module 2", V1)
    p = settings.data_dir / "x.pdf"
    p.write_bytes(pdf("x"))
    from server.instance_lock import InstanceLock
    with InstanceLock(settings.lock_file, "server"):
        assert modules.main(["register", str(p), "--deck", "m2"]) == 2


# ---- large upload over real HTTP, streamed ------------------------------------------------

def test_large_upload_streamed(live, settings):  # noqa: F811
    size = 150 * 1024 * 1024
    head = b"%PDF-1.7\n"
    chunk = b"\0" * (1024 * 1024)
    h = hashlib.sha256(head)
    for _ in range(150):
        h.update(chunk)
    want = h.hexdigest()
    host, port = live.split("//")[1].split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=120)
    tracemalloc.start()
    try:
        conn.putrequest("POST", "/api/modules?name=Big.pdf")
        conn.putheader("Content-Length", str(len(head) + size))
        conn.putheader("Content-Type", "application/pdf")
        conn.endheaders()
        conn.send(head)
        for _ in range(150):
            conn.send(chunk)
        r = conn.getresponse()
        body = json.loads(r.read())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        conn.close()
    assert r.status == 200, body
    assert body["sha256"] == want and body["size"] == len(head) + size
    f = mods_dir(settings) / "Big.pdf"
    assert f.stat().st_size == len(head) + size
    assert peak < 64 * 1024 * 1024, peak        # streamed to disk, never held whole
