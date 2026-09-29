"""Phase 8: phone access over Tailscale behind a PIN (server/phone.py, server/pin.py).

Simulated here: the client's IP address (Starlette's TestClient `client=(ip, port)`; a real
Tailscale address cannot be bound on this PC) and the PC's Tailscale names (HostList is
filled by hand instead of running `tailscale`). The live-socket test at the end uses real
loopback sockets only.
"""
from __future__ import annotations

import dataclasses
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest
import uvicorn
from server import phone, pin as pin_cli
from server.app import create_app

TS_IP = "100.101.102.103"          # this PC on the tailnet (simulated)
TS_NAME = "elisha-pc.tail1234.ts.net"
PHONE_IP = "100.88.1.2"            # the phone on the tailnet (simulated)
PIN = "482913"


@pytest.fixture
def on_settings(settings):
    return dataclasses.replace(settings, phone_access=True, phone_hosts=("drill.home",))


@pytest.fixture
def phone_client(make_client, on_settings):
    """Factory: a client at `ip` (default: the phone) talking to the PC's Tailscale name."""
    made = []

    def make(ip=PHONE_IP, host=TS_NAME, s=None):
        c = make_client(client_ip=ip, base_url=f"http://{host}:8765", app_settings=s or on_settings)
        c.__enter__()
        hl = c.app.state.phone_hosts
        hl.tailscale = {"installed": True, "ips": [TS_IP, "fd7a:115c:a1e0::1"],
                        "names": [TS_NAME, "elisha-pc"]}
        made.append(c)
        return c
    yield make
    for c in made:
        c.__exit__(None, None, None)


def set_pin(settings, value=PIN):
    return phone.PhoneAuth(settings.phone_db).set_pin(value)


def login(c, value=PIN, origin=None):
    h = {"content-type": "application/x-www-form-urlencoded"}
    if origin:
        h["origin"] = origin
    return c.post(phone.LOGIN_PATH, content=f"pin={value}".encode(), headers=h)


# ---- unit: address rules ------------------------------------------------------------------
@pytest.mark.parametrize("ip,on,lan,ok", [
    ("127.0.0.1", False, False, True), ("::1", False, False, True),
    ("100.64.0.1", False, False, False), ("192.168.1.5", False, True, False),
    ("100.64.0.1", True, False, True), ("100.127.255.254", True, False, True),
    ("100.128.0.1", True, False, False), ("100.63.255.255", True, False, False),
    ("fd7a:115c:a1e0::5", True, False, True), ("fd7a:115c:a1e1::5", True, False, False),
    ("::ffff:100.70.1.1", True, False, True),
    ("192.168.1.5", True, False, False), ("192.168.1.5", True, True, True),
    ("10.1.2.3", True, True, True), ("172.20.0.1", True, True, True),
    ("8.8.8.8", True, True, False), ("203.0.113.9", True, False, False),
    ("testclient", True, True, False), ("", True, True, False),
])
def test_client_rules(ip, on, lan, ok):
    assert phone.client_allowed(phone.client_ip(ip), on, lan) is ok


@pytest.mark.parametrize("hdr,host,port", [
    ("localhost:8765", "localhost", "8765"), ("Elisha-PC.tail1234.ts.net.:8765",
                                              "elisha-pc.tail1234.ts.net", "8765"),
    ("[fd7a:115c:a1e0::1]:8765", "fd7a:115c:a1e0::1", "8765"), ("100.1.2.3", "100.1.2.3", ""),
])
def test_split_host(hdr, host, port):
    assert phone.split_host(hdr) == (host, port)


def test_settings_read_phone_keys(tmp_path):
    from server.settings import SettingsError, load_settings
    d = tmp_path / "data"
    d.mkdir()
    env = tmp_path / ".env"
    env.write_text(f"DATA_DIR={d}\n", encoding="utf-8")
    s = load_settings(env_file=env, environ={})
    assert (s.phone_access, s.phone_allow_lan, s.phone_hosts) == (False, False, ())
    env.write_text(f"DATA_DIR={d}\nPHONE_ACCESS=on\nPHONE_ALLOW_LAN=on\n"
                   "PHONE_HOSTS=Drill.Home, other.name.\n", encoding="utf-8")
    s = load_settings(env_file=env, environ={})
    assert (s.phone_access, s.phone_allow_lan, s.phone_hosts) == (True, True,
                                                                  ("drill.home", "other.name"))
    env.write_text(f"DATA_DIR={d}\nPHONE_ACCESS=maybe\n", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(env_file=env, environ={})


# ---- off: exactly as before, this PC only ------------------------------------------------
def test_off_local_only(make_client):
    with make_client() as c:
        assert c.get("/api/health").status_code == 200
    for ip in (PHONE_IP, "192.168.1.5", "8.8.8.8"):
        with make_client(client_ip=ip) as c:
            r = c.get("/api/health")
            assert r.status_code == 403 and r.json()["error"] == "forbidden_client"
    # the Tailscale name is not a known host when off, even from this PC
    with make_client(base_url=f"http://{TS_NAME}:8765") as c:
        c.app.state.phone_hosts.tailscale = {"installed": True, "ips": [TS_IP], "names": [TS_NAME]}
        assert c.get("/api/health").json()["error"] == "forbidden_host"


def test_off_binds_loopback(monkeypatch, settings):
    import server.__main__ as m
    seen = {}
    monkeypatch.setattr(m, "load_settings", lambda: settings)
    import uvicorn as uv
    monkeypatch.setattr(uv, "run", lambda app, **kw: seen.update(kw))
    assert m.main([]) == 0
    assert seen["host"] == "127.0.0.1" and seen["proxy_headers"] is False
    monkeypatch.setattr(m, "load_settings", lambda: dataclasses.replace(settings, phone_access=True))
    monkeypatch.setattr(phone, "detect_tailscale", lambda: {"installed": False, "ips": [], "names": []})
    assert m.main([]) == 0
    assert seen["host"] == "0.0.0.0"


# ---- on: who may connect ---------------------------------------------------------------
def test_on_tailscale_allowed_others_refused(phone_client, on_settings):
    set_pin(on_settings)
    assert phone_client().get("/api/health").status_code == 401        # allowed, needs PIN
    assert phone_client(ip="fd7a:115c:a1e0:ab12::9").get("/api/health").status_code == 401
    for ip in ("192.168.1.5", "10.0.0.7", "8.8.8.8", "100.128.0.1"):
        r = phone_client(ip=ip).get("/")
        assert r.status_code == 403 and r.json()["error"] == "forbidden_client", ip


def test_lan_only_when_allowed(phone_client, on_settings):
    set_pin(on_settings)
    lan = dataclasses.replace(on_settings, phone_allow_lan=True)
    assert phone_client(ip="192.168.1.5", host="drill.home", s=lan).get("/api/health").status_code == 401
    assert phone_client(ip="8.8.8.8", host="drill.home", s=lan).get("/api/health").status_code == 403


def test_unknown_host_refused_when_on(phone_client, on_settings):
    set_pin(on_settings)
    for host in ("evil.example", "elisha-pc.evil.example", "100.101.102.104"):
        r = phone_client(host=host).get("/api/health")
        assert r.status_code == 403 and r.json()["error"] == "forbidden_host", host
    # known names: MagicDNS full + short name, Tailscale IPs (v4, v6), PHONE_HOSTS
    for host in (TS_NAME, "elisha-pc", TS_IP, "[fd7a:115c:a1e0::1]", "drill.home"):
        assert phone_client(host=host).get("/api/health").status_code == 401, host


def test_localhost_needs_no_pin(phone_client, on_settings):
    set_pin(on_settings)
    for host in ("127.0.0.1", "localhost", TS_NAME):
        c = phone_client(ip="127.0.0.1", host=host)
        assert c.get("/api/health").status_code == 200
        assert c.put("/api/store/k", content=b"1").json()["ok"] is True


# ---- the PIN flow ------------------------------------------------------------------------
def test_no_pin_set_page(phone_client):
    c = phone_client()
    r = c.get("/")
    assert r.status_code == 403 and "Set a PIN on the PC first" in r.text
    assert c.get("/api/store").json()["error"] == "pin_not_set"
    r = login(c)
    assert r.status_code == 403 and "Set a PIN on the PC first" in r.text


def test_login_page_is_self_contained(phone_client, on_settings):
    set_pin(on_settings)
    r = phone_client().get("/")
    assert r.status_code == 200 and 'name="pin"' in r.text and phone.LOGIN_PATH in r.text
    assert 'name="viewport"' in r.text
    for ext in ("http://", "https://", "<script src", "<link"):
        assert ext not in r.text
    assert r.headers["cache-control"] == "no-store"
    # other pages send the phone to the login page; the API answers 401 JSON
    r2 = phone_client().get("/some/page.html")
    assert r2.status_code == 303 and r2.headers["location"] == "/"
    r3 = phone_client().get("/api/store/k")
    assert r3.status_code == 401 and r3.json()["error"] == "pin_required"
    assert phone_client().put("/api/store/k", content=b"1").status_code == 401


def test_wrong_pin_then_correct(phone_client, on_settings):
    set_pin(on_settings)
    c = phone_client()
    r = login(c, "000000")
    assert r.status_code == 401 and "Wrong PIN" in r.text and phone.COOKIE not in r.cookies
    r = login(c, "abc")
    assert r.status_code == 401
    r = login(c, origin=f"http://{TS_NAME}:8765")
    assert r.status_code == 303 and r.headers["location"] == "/"
    sc = r.headers["set-cookie"].lower()
    for part in ("httponly", "samesite=strict", "path=/", "max-age=2592000"):
        assert part in sc, part
    token = r.cookies[phone.COOKIE]
    assert len(token) >= 40
    # stored hashed, never the token itself
    import sqlite3
    db = sqlite3.connect(on_settings.phone_db)
    try:
        rows = db.execute("SELECT token_sha256 FROM sessions").fetchall()
        pins = db.execute("SELECT salt, hash FROM pin").fetchall()
    finally:
        db.close()
    assert len(rows) == 1 and rows[0][0] != token and PIN not in str(pins)
    # the cookie opens the app and the API
    c.cookies.set(phone.COOKIE, token)
    assert c.get("/").status_code == 200 and "Drill server is running" in c.get("/").text
    assert c.put("/api/store/deck:1", content=b'{"a":1}',
                 headers={"origin": f"http://{TS_NAME}:8765"}).json()["status"] == "added"
    assert c.get("/api/store/deck:1").json() == {"a": 1}


def test_lockout_after_five(phone_client, on_settings, caplog):
    set_pin(on_settings)
    c = phone_client()
    for i in range(4):
        assert login(c, "111111").status_code == 401
    r = login(c, "111111")
    assert r.status_code == 429 and "15 minutes" in r.text
    # locked: even the right PIN is refused now
    r = login(c)
    assert r.status_code == 429 and phone.COOKIE not in r.cookies
    assert "locked out" in caplog.text
    # another tailnet device is not affected
    assert login(phone_client(ip="100.88.1.3")).status_code == 303
    # after 15 minutes it works again
    auth = c.app.state.phone_auth
    auth._fails[PHONE_IP][1] = time.monotonic() - 1
    assert login(c).status_code == 303
    import sqlite3
    db = sqlite3.connect(on_settings.phone_db)
    try:
        events = [e for (e,) in db.execute("SELECT event FROM auth_events")]
    finally:
        db.close()
    assert events.count("wrong PIN") == 4 and any("locked out" in e for e in events)


def test_revoke_all_and_pin_change(phone_client, on_settings, monkeypatch, capsys):
    set_pin(on_settings)
    c = phone_client()
    token = login(c).cookies[phone.COOKIE]
    c.cookies.set(phone.COOKIE, token)
    assert c.get("/api/health").status_code == 200
    # the CLI works on the same DATA_DIR (the data_dir fixture sets it in the environment)
    assert pin_cli.main(["revoke-all"]) == 0
    assert "Signed out 1" in capsys.readouterr().out
    assert c.get("/api/health").status_code == 401
    # sign in again, then change the PIN from the CLI: every session ends, old PIN is dead
    token = login(c).cookies[phone.COOKIE]
    c.cookies.set(phone.COOKIE, token)
    assert c.get("/api/health").status_code == 200
    answers = iter(["7654321", "7654321"])
    assert pin_cli.main(["set"], ask=lambda _p: next(answers)) == 0
    assert "1 phone session(s) signed out" in capsys.readouterr().out
    assert c.get("/api/health").status_code == 401
    c.cookies.clear()
    assert login(c).status_code == 401
    assert login(c, "7654321").status_code == 303


def test_pin_cli_rules(data_dir, capsys):
    for pair in (["12345", "12345"], ["12a456", "12a456"], ["123456", "123457"]):
        it = iter(pair)
        assert pin_cli.main(["set"], ask=lambda _p: next(it)) == 1
    assert "NOT set" in (pin_cli.main(["status"]) or capsys.readouterr().out)
    it = iter(["123456", "123456"])
    assert pin_cli.main(["set"], ask=lambda _p: next(it)) == 0
    # stored in DATA_DIR, outside the repo
    assert (data_dir / "phone-access.db").is_file()


def test_logout(phone_client, on_settings):
    set_pin(on_settings)
    c = phone_client()
    c.cookies.set(phone.COOKIE, login(c).cookies[phone.COOKIE])
    assert c.get("/api/health").status_code == 200
    r = c.post(phone.LOGOUT_PATH)
    assert r.status_code == 303
    assert c.get("/api/health").status_code == 401


def test_expired_session_refused(phone_client, on_settings):
    set_pin(on_settings)
    c = phone_client()
    c.cookies.set(phone.COOKIE, login(c).cookies[phone.COOKIE])
    import sqlite3
    db = sqlite3.connect(on_settings.phone_db)
    db.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00+00:00'")
    db.commit()
    db.close()
    assert c.get("/api/health").status_code == 401


# ---- Origin rules with the Tailscale host -------------------------------------------------
@pytest.mark.parametrize("origin,ok", [
    (f"http://{TS_NAME}:8765", True), (None, True),
    ("http://localhost:8765", False), ("http://127.0.0.1:8765", False),
    (f"http://{TS_NAME}:9999", False), (f"https://{TS_NAME}:8765", False),
    ("http://elisha-pc:8765", False), ("https://evil.example", False), ("null", False),
])
def test_origin_is_the_host_used(phone_client, on_settings, origin, ok):
    set_pin(on_settings)
    c = phone_client()
    c.cookies.set(phone.COOKIE, login(c).cookies[phone.COOKIE])
    h = {"origin": origin} if origin else {}
    r = c.put("/api/store/o", content=b"1", headers=h)
    assert (r.status_code == 200) is ok, r.text
    if not ok:
        assert r.json()["error"] == "forbidden_origin"


def test_login_from_foreign_origin_refused(phone_client, on_settings):
    set_pin(on_settings)
    r = login(phone_client(), origin="https://evil.example")
    assert r.status_code == 403 and r.json()["error"] == "forbidden_origin"


def test_local_origin_rules_unchanged_when_on(phone_client, on_settings):
    c = phone_client(ip="127.0.0.1", host="127.0.0.1")
    assert c.put("/api/store/x", content=b"1", headers={"origin": "http://localhost:8765"}).status_code == 200
    assert c.put("/api/store/x", content=b"2",
                 headers={"origin": f"http://{TS_NAME}:8765"}).status_code == 403


# ---- a real socket: uvicorn on loopback, off vs on ------------------------------------------
def _serve(app):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                       proxy_headers=False))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    end = time.time() + 10
    while not srv.started and time.time() < end:
        time.sleep(0.05)
    return srv, t, port


def test_live_forwarded_header_cannot_fake_the_client(settings, on_settings, tmp_path):
    """A request from 127.0.0.1 with X-Forwarded-For: <phone> is still treated as local
    (no PIN), and one with X-Forwarded-For of a foreign address is not refused because of it:
    the client address comes from the socket only."""
    app = create_app(on_settings, app_dir=tmp_path / "no-app",
                     modules_md_paths=[tmp_path / "M.md"], detect_tailscale=False)
    srv, t, port = _serve(app)
    try:
        for xff in (PHONE_IP, "8.8.8.8"):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health",
                                         headers={"X-Forwarded-For": xff, "X-Real-IP": xff})
            with urllib.request.urlopen(req, timeout=5) as r:
                assert r.status == 200
    finally:
        srv.should_exit = True
        t.join(10)
