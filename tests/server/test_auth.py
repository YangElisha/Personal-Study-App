"""Phase 9: Google sign-in, sessions, one database per person (server/accounts.py,
server/google_auth.py, the guard in server/app.py).

Google is faked: the token exchange is replaced (create_app(google_exchange=...)) by a function
that records what it was sent and answers with an id_token built from the test's claims.
Time is faked with an injected clock, so "7 days later" needs no waiting.
"""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import logging
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from server import accounts as acc_mod
from server import db, google_auth, phone
from server.settings import SettingsError, load_settings

CID = "test-client-id.apps.googleusercontent.com"
SECRET = "test-secret-value-not-real"
ELISHA = "yang.elishalee@gmail.com"
BOB = "bob.tester@example.com"
T0 = 1_790_000_000.0


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


def b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def jwt(claims: dict) -> str:
    return f"{b64({'alg': 'RS256', 'kid': 'x'})}.{b64(claims)}.c2ln"


class FakeGoogle:
    """Stands in for https://oauth2.googleapis.com/token."""

    def __init__(self, clock):
        self.clock = clock
        self.codes: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.offline = False

    def exchange(self, cfg, code, verifier, redirect_uri):
        self.calls.append({"client_id": cfg.client_id, "secret": cfg.client_secret,
                           "code": code, "verifier": verifier, "redirect_uri": redirect_uri})
        if self.offline:
            raise google_auth.SignInError("offline", "token endpoint unreachable (test)")
        if code not in self.codes:
            raise google_auth.SignInError("failed", "token endpoint answered 400 invalid_grant")
        return {"access_token": "x", "id_token": jwt(self.codes.pop(code)), "token_type": "Bearer"}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def google(clock):
    return FakeGoogle(clock)


@pytest.fixture
def gsettings(settings):
    return dataclasses.replace(settings, auth_mode="google", google_client_id=CID,
                               google_client_secret=SECRET)


@pytest.fixture
def accounts(gsettings, clock):
    return acc_mod.Accounts(gsettings.accounts_db, clock=clock)


@pytest.fixture
def gclient(make_client, gsettings, google, clock, tmp_path):
    """Factory for clients of one sign-in-enabled server app (they share its state)."""
    made = []
    cfg = google_auth.GoogleConfig(CID, SECRET, reach_host=None)

    def make(ip="127.0.0.1", host="127.0.0.1", app_dir=None, s=None, **kw):
        c = make_client(app_settings=s or gsettings, client_ip=ip,
                        base_url=f"http://{host}:8765", google_config=cfg,
                        google_exchange=google.exchange, clock=clock, app_dir=app_dir, **kw)
        c.__enter__()
        made.append(c)
        return c
    yield make
    for c in made:
        c.__exit__(None, None, None)


def start(c):
    r = c.get("/auth/google/start")
    assert r.status_code == 302, r.text
    return r, {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}


def claims_for(email, q, clock, **over):
    c = {"iss": "https://accounts.google.com", "aud": CID, "azp": CID, "sub": "sub-" + email,
         "email": email, "email_verified": True, "iat": int(clock()), "exp": int(clock()) + 3600,
         "nonce": q["nonce"]}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def sign_in(c, google, clock, email=ELISHA, **over):
    _, q = start(c)
    code = "code-" + q["state"][:8]
    google.codes[code] = claims_for(email, q, clock, **over)
    return c.get("/auth/google/callback", params={"code": code, "state": q["state"]})


def events(gsettings):
    conn = sqlite3.connect(gsettings.accounts_db)
    try:
        return conn.execute("SELECT event, method, email, reason FROM sign_in_events "
                            "ORDER BY id").fetchall()
    finally:
        conn.close()


# ---- settings -------------------------------------------------------------------------------
def test_settings_auth_mode(data_dir, tmp_path):
    env = tmp_path / "none.env"
    base = {"DATA_DIR": str(data_dir)}
    assert load_settings(env, base).auth_mode == "off"          # default: as before
    with pytest.raises(SettingsError, match="GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET"):
        load_settings(env, {**base, "AUTH_MODE": "google"})
    with pytest.raises(SettingsError, match="GOOGLE_CLIENT_SECRET"):
        load_settings(env, {**base, "AUTH_MODE": "google", "GOOGLE_CLIENT_ID": CID})
    with pytest.raises(SettingsError, match="AUTH_MODE must be"):
        load_settings(env, {**base, "AUTH_MODE": "maybe"})
    s = load_settings(env, {**base, "AUTH_MODE": "google", "GOOGLE_CLIENT_ID": CID,
                            "GOOGLE_CLIENT_SECRET": SECRET})
    assert s.auth_mode == "google" and s.google_client_secret == SECRET
    assert SECRET not in repr(s)                                 # never in a log line
    assert s.db_path == s.data_dir / "drill.db" and s.accounts_db == s.data_dir / "accounts.db"


# ---- the flow ---------------------------------------------------------------------------------
def test_authorize_request(gclient, accounts):
    c = gclient()
    r, q = start(c)
    loc = r.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == CID and q["response_type"] == "code"
    assert q["scope"] == "openid email" and q["prompt"] == "select_account"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["redirect_uri"] == "http://127.0.0.1:8765/auth/google/callback"
    assert len(q["state"]) >= 43 and len(q["nonce"]) >= 43
    assert SECRET not in loc
    ck = r.headers["set-cookie"]
    assert "drill_oauth=" in ck and "HttpOnly" in ck and "samesite=lax" in ck.lower()
    assert "Path=/auth/google/" in ck and "Max-Age=600" in ck
    # localhost works too (both redirect URIs are registered); other names cannot
    _, q2 = start(gclient(host="localhost"))
    assert q2["redirect_uri"] == "http://localhost:8765/auth/google/callback"
    r = gclient(host="[::1]").get("/auth/google/start")
    assert r.status_code == 400 and "http://localhost:8765/" in r.text


def test_happy_path_existing_data(gclient, google, clock, accounts, gsettings):
    # Elisha's existing database in DATA_DIR, before sign-in exists
    db.init_db(gsettings.db_path)
    c0 = db.connect(gsettings.db_path)
    db.put(c0, "library", '{"decks":[{"id":"d1","name":"IA Module 1"}]}')
    c0.close()
    db.checkpoint(gsettings.db_path)
    accounts.allow(ELISHA, existing_data=True)
    c = gclient()
    assert c.get("/api/store/library").status_code == 401
    r = sign_in(c, google, clock)
    assert r.status_code == 200 and 'http-equiv="refresh" content="0;url=/"' in r.text
    ck = [h for h in r.headers.get_list("set-cookie") if h.startswith("drill_session=")][0]
    assert "HttpOnly" in ck and "samesite=strict" in ck.lower() and "Path=/" in ck
    assert "Max-Age=604800" in ck and "Secure" not in ck
    # PKCE: the verifier went to the token endpoint and matches the challenge sent to Google
    call = google.calls[-1]
    assert call["redirect_uri"] == "http://127.0.0.1:8765/auth/google/callback"
    assert call["client_id"] == CID and call["secret"] == SECRET
    # the data is DATA_DIR's own drill.db, used in place
    assert c.get("/api/store/library").json()["decks"][0]["name"] == "IA Module 1"
    me = c.get("/api/auth/me").json()
    assert me["auth_mode"] == "google" and me["user"]["email"] == ELISHA
    assert me["user"]["existing_data"] is True and me["session"]["method"] == "google"
    assert not (gsettings.data_dir / "users").exists()           # nothing copied or created
    assert events(gsettings)[-1][:3] == ("signed_in", "google", ELISHA)
    # only the hash of the token is stored
    token = c.cookies.get("drill_session")
    raw = gsettings.accounts_db.read_bytes()
    assert token.encode() not in raw
    assert hashlib.sha256(token.encode()).hexdigest().encode() in raw


def test_pkce_verifier_sent(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    c = gclient()
    _, q = start(c)
    google.codes["abc"] = claims_for(ELISHA, q, clock)
    assert c.get("/auth/google/callback", params={"code": "abc", "state": q["state"]}).status_code == 200
    v = google.calls[-1]["verifier"]
    assert 43 <= len(v) <= 128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"]


def test_email_case_insensitive(gclient, google, clock, accounts):
    accounts.allow("Yang.ElishaLee@Gmail.com")
    c = gclient()
    assert sign_in(c, google, clock, email="YANG.elishalee@gmail.COM").status_code == 200
    assert c.get("/api/auth/me").json()["user"]["email"] == ELISHA


def test_refused_email(gclient, google, clock, accounts, gsettings):
    accounts.allow(ELISHA)
    c = gclient()
    r = sign_in(c, google, clock, email="stranger@example.com")
    assert r.status_code == 403 and "not approved" in r.text
    assert "drill_session" not in c.cookies
    assert c.get("/api/store/x").status_code == 401
    assert events(gsettings)[-1] == ("refused", "google", "stranger@example.com",
                                     "email not approved")


@pytest.mark.parametrize("over,reason", [
    ({"nonce": "someone-elses-nonce"}, "nonce mismatch"),
    ({"exp": T0 - 61}, "id_token expired"),
    ({"iat": T0 + 3600}, "issued in the future"),
    ({"email_verified": False}, "email not verified"),
    ({"email_verified": None}, "email not verified"),
    ({"aud": "another-app.apps.googleusercontent.com"}, "audience"),
    ({"aud": [CID, "other"], "azp": "other"}, "azp"),
    ({"iss": "https://evil.example.com"}, "wrong issuer"),
    ({"sub": None}, "email or sub missing"),
])
def test_bad_id_token_refused(gclient, google, clock, accounts, gsettings, over, reason):
    accounts.allow(ELISHA)
    c = gclient()
    r = sign_in(c, google, clock, **over)
    assert r.status_code == 400 and "did not complete" in r.text
    assert "drill_session" not in c.cookies
    ev = events(gsettings)[-1]
    assert ev[0] == "refused" and reason in ev[3]


def test_id_token_within_skew_accepted(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    assert sign_in(gclient(), google, clock, exp=T0 - 30, iat=T0 + 30).status_code == 200


def test_bad_state(gclient, google, clock, accounts, gsettings):
    accounts.allow(ELISHA)
    c = gclient()
    _, q = start(c)
    google.codes["k"] = claims_for(ELISHA, q, clock)
    r = c.get("/auth/google/callback", params={"code": "k", "state": "forged-state"})
    assert r.status_code == 400 and "expired or was already used" in r.text
    assert google.calls == []                     # no code is exchanged without a valid state
    assert "drill_session" not in c.cookies
    assert events(gsettings)[-1][3] == "unknown or already used state"


def test_state_is_single_use(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    c = gclient()
    _, q = start(c)
    google.codes["k1"] = claims_for(ELISHA, q, clock)
    assert c.get("/auth/google/callback", params={"code": "k1", "state": q["state"]}).status_code == 200
    google.codes["k2"] = claims_for(ELISHA, q, clock)
    r = c.get("/auth/google/callback", params={"code": "k2", "state": q["state"]})
    assert r.status_code == 400 and len(google.calls) == 1


def test_state_bound_to_browser(gclient, google, clock, accounts, gsettings):
    """Login CSRF: a callback link started in another browser does not sign this one in."""
    accounts.allow(ELISHA)
    c = gclient()
    _, q = start(c)                 # the attacker starts a sign-in ...
    google.codes["k"] = claims_for(ELISHA, q, clock)
    c.cookies.clear()               # ... and the victim's browser (no flow cookie) opens the link
    r = c.get("/auth/google/callback", params={"code": "k", "state": q["state"]})
    assert r.status_code == 400 and "drill_session" not in c.cookies
    assert events(gsettings)[-1][3] == "state was not started by this browser"


def test_flow_expires_after_10_minutes(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    c = gclient()
    _, q = start(c)
    google.codes["k"] = claims_for(ELISHA, q, clock)
    clock.t += 601
    google.codes["k"].update(iat=int(clock()), exp=int(clock()) + 3600)
    r = c.get("/auth/google/callback", params={"code": "k", "state": q["state"]})
    assert r.status_code == 400 and "expired" in r.text


def test_cancelled_and_offline(gclient, google, clock, accounts, gsettings, make_client):
    accounts.allow(ELISHA)
    c = gclient()
    _, q = start(c)
    r = c.get("/auth/google/callback", params={"error": "access_denied", "state": q["state"]})
    assert r.status_code == 400 and "cancelled" in r.text
    google.offline = True
    r = sign_in(c, google, clock)
    assert r.status_code == 503 and "reach Google" in r.text
    # offline before leaving for Google: a friendly page, not a browser error
    off = make_client(app_settings=gsettings, google_config=google_auth.GoogleConfig(
        CID, SECRET, reach_host="127.0.0.1:9"), google_exchange=google.exchange, clock=clock)
    with off:
        r = off.get("/auth/google/start")
    assert r.status_code == 503 and "reach Google" in r.text


def test_account_bound_to_google_sub(gclient, google, clock, accounts, gsettings):
    accounts.allow(ELISHA)
    assert sign_in(gclient(), google, clock, sub="sub-1").status_code == 200
    r = sign_in(gclient(), google, clock, sub="sub-2")       # same email, other Google account
    assert r.status_code == 403 and "different Google account" in r.text
    assert sign_in(gclient(), google, clock, sub="sub-1").status_code == 200


def test_rate_limit_failures(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    c = gclient()
    for i in range(google_auth.FAIL_MAX - 1):
        assert c.get("/auth/google/callback", params={"state": f"bad{i}", "code": "x"}).status_code == 400
    r = c.get("/auth/google/callback", params={"state": "bad-last", "code": "x"})
    assert r.status_code == 429 and "Too many sign-in attempts" in r.text
    assert c.get("/auth/google/start").status_code == 429
    assert sign_in_blocked(c)


def sign_in_blocked(c):
    return c.get("/auth/google/callback", params={"state": "s", "code": "x"}).status_code == 429


def test_rate_limit_callback_hits(gclient, accounts, google, clock):
    accounts.allow(ELISHA)
    c = gclient()
    codes = []
    for i in range(google_auth.CALLBACK_MAX):
        _, q = start(c)
        google.codes[f"c{i}"] = claims_for(ELISHA, q, clock)
        codes.append(c.get("/auth/google/callback",
                           params={"code": f"c{i}", "state": q["state"]}).status_code)
    assert codes == [200] * google_auth.CALLBACK_MAX
    _, q = start(c)
    assert c.get("/auth/google/callback", params={"code": "z", "state": q["state"]}).status_code == 429


def test_secret_never_logged(gclient, google, clock, accounts, caplog):
    caplog.set_level(logging.DEBUG)
    accounts.allow(ELISHA)
    c = gclient()
    sign_in(c, google, clock)
    sign_in(c, google, clock, email="nobody@example.com")
    sign_in(c, google, clock, nonce="x")
    assert SECRET not in caplog.text


# ---- sessions ---------------------------------------------------------------------------------
def test_session_lasts_exactly_7_days(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    c = gclient()
    sign_in(c, google, clock)
    assert c.get("/api/store/k").status_code == 204
    clock.t += 7 * 86400 - 1                     # used right up to the end: still valid
    assert c.get("/api/store/k").status_code == 204
    clock.t += 2                                 # absolute expiry: use never extended it
    r = c.get("/api/store/k")
    assert r.status_code == 401 and r.json()["error"] == "auth_required"
    r = c.get("/")
    assert r.status_code == 200 and "Your sign-in has ended" in r.text
    assert any(h.startswith('drill_session=""') for h in r.headers.get_list("set-cookie"))


def test_revoke_this_others_all(gclient, google, clock, accounts, gsettings):
    accounts.allow(ELISHA)
    a, b, c = gclient(), gclient(), gclient()
    for x in (a, b, c):
        assert sign_in(x, google, clock).status_code == 200
    ss = a.get("/api/auth/sessions").json()["sessions"]
    assert len(ss) == 3 and sum(s["current"] for s in ss) == 1
    assert set(ss[0]) >= {"id", "method", "device", "user_agent", "client_ip", "created_at",
                          "last_seen_at", "expires_at", "current"}
    # sign out one other device by id: instant
    b_id = b.get("/api/auth/me").json()["session"]["id"]
    r = a.post(f"/api/auth/sessions/{b_id}/revoke")
    assert r.json() == {"ok": True, "revoked": 1, "signed_out_here": False}
    assert b.get("/api/store/k").status_code == 401
    # sign out others
    sign_in(b, google, clock)
    r = a.post("/api/auth/signout-others")
    assert r.json()["revoked"] == 2
    assert b.get("/api/store/k").status_code == 401 and c.get("/api/store/k").status_code == 401
    assert a.get("/api/store/k").status_code == 204
    # sign out this device
    r = a.post("/api/auth/signout")
    assert r.json()["signed_out_here"] is True
    assert any(h.startswith('drill_session=""') for h in r.headers.get_list("set-cookie"))
    assert a.get("/api/store/k").status_code == 401
    # sign out everywhere
    sign_in(a, google, clock)
    sign_in(b, google, clock)
    r = b.post("/api/auth/signout-all")
    assert r.json()["revoked"] == 2
    assert a.get("/api/store/k").status_code == 401 and b.get("/api/store/k").status_code == 401
    evs = [e for e in events(gsettings) if e[0] == "signed_out"]
    assert len(evs) == 4


def test_account_events_api(gclient, google, clock, accounts):
    accounts.allow(ELISHA)
    c = gclient()
    sign_in(c, google, clock, nonce="bad")          # a refused attempt for her email
    sign_in(c, google, clock)
    ev = c.get("/api/auth/events").json()["events"]
    assert [e["event"] for e in ev[:2]] == ["signed_in", "refused"]
    assert ev[1]["reason"] == "nonce mismatch" and ev[0]["client_ip"] == "127.0.0.1"


def test_disallow_signs_out_instantly(gclient, google, clock, accounts, gsettings):
    accounts.allow(ELISHA)
    c = gclient()
    sign_in(c, google, clock)
    assert c.get("/api/store/k").status_code == 204
    accounts.disallow(ELISHA)
    assert c.get("/api/store/k").status_code == 401
    assert sign_in(c, google, clock).status_code == 403


# ---- one database per person -------------------------------------------------------------------
def test_per_user_isolation(gclient, google, clock, accounts, gsettings):
    accounts.allow(ELISHA, existing_data=True)
    bob, _ = accounts.allow(BOB)
    a, b = gclient(), gclient()
    sign_in(a, google, clock, email=ELISHA)
    sign_in(b, google, clock, email=BOB)
    assert a.put("/api/store/secret", content=b'"elisha only"').status_code == 200
    assert b.put("/api/store/mine", content=b'"bob only"').status_code == 200
    assert b.get("/api/store/secret").status_code == 204
    assert a.get("/api/store/mine").status_code == 204
    assert b.get("/api/store").json() == {"keys": ["mine"]}
    assert a.get("/api/store").json() == {"keys": ["secret"]}
    assert b.delete("/api/store/secret").status_code == 404
    assert a.get("/api/store/secret").text == '"elisha only"'
    bob_dir = gsettings.data_dir / "users" / bob.id
    assert (bob_dir / "drill.db").is_file() and (bob_dir / "backups").is_dir()
    k = sqlite3.connect(bob_dir / "drill.db").execute("SELECT key FROM kv").fetchall()
    assert k == [("mine",)]
    # modules go to the account's own folder; the repo's MODULES.md is not touched
    r = b.post("/api/modules?name=bob.pdf", content=b"%PDF-1.4 bob")
    assert r.status_code == 200 and (bob_dir / "modules" / "bob.pdf").is_file()
    assert not (gsettings.data_dir / "modules" / "bob.pdf").exists()
    assert (bob_dir / "MODULES.md").is_file()
    assert a.get("/api/modules").json()["modules"] == []
    # Bob cannot sign out Elisha's session
    a_id = a.get("/api/auth/me").json()["session"]["id"]
    assert b.post(f"/api/auth/sessions/{a_id}/revoke").status_code == 404
    assert a.get("/api/store/secret").status_code == 200
    assert [s["id"] for s in b.get("/api/auth/sessions").json()["sessions"]] != [a_id]


def test_new_account_snapshots(make_client, gsettings, accounts, clock):
    bob, _ = accounts.allow(BOB)
    us = accounts.settings_for(gsettings, bob)
    acc_mod.Accounts.prepare(us)
    with make_client(app_settings=gsettings, clock=clock):
        pass
    # each database is snapshotted into its own backups folder
    assert len(list(us.backups_dir.glob("drill-*.db"))) == 1
    assert len(list(gsettings.backups_dir.glob("drill-*.db"))) == 1     # DATA_DIR's, as before


def test_accounts_rules(accounts, gsettings):
    u, st = accounts.allow(ELISHA, existing_data=True)
    assert st == "added" and u.existing_data
    assert accounts.allow(ELISHA, existing_data=True)[1] == "unchanged"
    with pytest.raises(acc_mod.AccountError, match="Only one account"):
        accounts.allow(BOB, existing_data=True)
    b, _ = accounts.allow(BOB)
    with pytest.raises(acc_mod.AccountError, match="not done automatically"):
        accounts.allow(BOB, existing_data=True)
    with pytest.raises(acc_mod.AccountError, match="not an email"):
        accounts.allow("not-an-email")
    accounts.disallow(BOB)
    b2, st = accounts.allow(BOB)
    assert st == "re-allowed" and b2.id == b.id                 # same folder, same data
    assert accounts.settings_for(gsettings, u).db_path == gsettings.data_dir / "drill.db"
    assert accounts.settings_for(gsettings, b).db_path == \
        gsettings.data_dir / "users" / b.id / "drill.db"


def test_accounts_cli(data_dir, monkeypatch, capsys):
    from server.accounts import main
    assert main(["list"]) == 0 and "No accounts" in capsys.readouterr().out
    assert main(["allow", ELISHA, "--existing-data"]) == 0
    assert "used in place" in capsys.readouterr().out
    assert main(["allow", BOB, "--existing-data"]) == 1
    assert main(["allow", BOB]) == 0
    out = capsys.readouterr().out
    assert "users" in out and not (data_dir / "drill.db").exists()
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert ELISHA in out and "DATA_DIR (existing data)" in out and BOB in out
    assert main(["sessions"]) == 0 and "Active sessions: 0" in capsys.readouterr().out
    assert main(["revoke-all", "--email", BOB]) == 0
    assert main(["disallow", BOB]) == 0 and "data is kept" in capsys.readouterr().out
    assert main(["events"]) == 0


def test_cli_user_flag(data_dir, capsys):
    """--user routes the CLI tools to that account; without it, DATA_DIR as before."""
    from server import accounts as a, modules
    from server.settings import load_settings
    assert a.main(["allow", BOB]) == 0
    s = load_settings()
    assert a.settings_for_email(s, None) is s
    bs = a.settings_for_email(s, BOB)
    assert bs.root.parent == data_dir.resolve() / "users" and bs.db_path.is_file()
    with pytest.raises(a.AccountError):
        a.settings_for_email(s, "nobody@example.com")
    assert modules.main(["list", "--user", BOB]) == 0
    assert modules.main(["list", "--user", "nobody@example.com"]) == 2
    from server.restore import main as restore_main
    capsys.readouterr()
    assert restore_main(["--user", BOB]) == 0
    assert str(bs.backups_dir) in capsys.readouterr().out
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_import", str(a.Path(__file__).resolve().parents[2] / "tools" / "verify_import.py"))
    vi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vi)
    assert vi.user_data_dir(data_dir, BOB) == data_dir / "users" / bs.root.name
    assert vi.user_data_dir(data_dir, "x@y.z") is None


# ---- every route needs a session ---------------------------------------------------------------
@pytest.mark.parametrize("method,path", [
    ("GET", "/api/health"), ("GET", "/api/store"), ("GET", "/api/store/library"),
    ("PUT", "/api/store/library"), ("DELETE", "/api/store/library"), ("POST", "/api/ai"),
    ("GET", "/api/ai/route"), ("GET", "/api/modules"), ("POST", "/api/modules?name=a.pdf"),
    ("POST", "/api/modules/abc/deck"), ("POST", "/api/import"), ("GET", "/api/auth/me"),
    ("GET", "/api/auth/sessions"), ("POST", "/api/auth/signout-all"),
    ("POST", "/api/phone/login"),
])
def test_api_requires_session_even_from_this_pc(gclient, tmp_path, method, path):
    c = gclient()
    r = c.request(method, path, content=b'"x"')
    assert r.status_code == 401
    assert r.json() == {"ok": False, "error": "auth_required", "message": "Sign in first",
                        "sign_in": "google"}
    assert r.headers["cache-control"] == "no-store"


def test_pages_require_session(gclient, tmp_path, google, clock, accounts):
    app_dir = tmp_path / "app"
    (app_dir / "vendor").mkdir(parents=True)
    (app_dir / "index.html").write_text("<h1>THE APP</h1>", encoding="utf-8")
    (app_dir / "vendor" / "x.js").write_text("secret()", encoding="utf-8")
    (app_dir / "favicon.ico").write_bytes(b"ico")
    c = gclient(app_dir=app_dir)
    r = c.get("/")
    assert r.status_code == 200 and "THE APP" not in r.text
    assert "Sign in with Google" in r.text and "<svg" in r.text and "2-Step Verification" in r.text
    assert 'href="/auth/google/start"' in r.text and "http" not in r.text.split("<body>")[1]
    for p in ("/index.html", "/vendor/x.js", "/favicon.ico", "/anything"):
        r = c.get(p)
        assert r.status_code == 303 and r.headers["location"] == "/", p
    assert c.get("/auth/signin?error=not_approved").text.count("not approved") == 1
    assert "&lt;" not in c.get("/auth/signin?error=<script>").text     # unknown code: no message
    accounts.allow(ELISHA)
    sign_in(c, google, clock)
    assert "THE APP" in c.get("/").text and c.get("/vendor/x.js").text == "secret()"


def test_security_headers(gclient, make_client, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
    for c, paths in ((gclient(app_dir=app_dir), ("/", "/api/store/x", "/auth/google/start",
                                                 "/auth/signin")),
                     (make_client(app_dir=app_dir), ("/", "/api/store/x", "/api/health",
                                                     "/favicon.ico"))):
        with c:
            for p in paths:
                h = c.get(p).headers
                assert h["content-security-policy"].startswith("default-src 'self'; script-src "
                                                               "'self' 'unsafe-inline'"), p
                for part in ("connect-src 'self'", "img-src 'self' data: blob:",
                             "worker-src 'self' blob:", "font-src 'self'",
                             "frame-ancestors 'none'", "object-src 'none'", "base-uri 'none'",
                             "form-action 'self' https://accounts.google.com"):
                    assert part in h["content-security-policy"], (p, part)
                assert h["x-content-type-options"] == "nosniff"
                assert h["referrer-policy"] == "no-referrer"
                assert h["x-frame-options"] == "DENY"
                if p.startswith(("/api/", "/auth/")):
                    assert h["cache-control"] == "no-store", p


# ---- AUTH_MODE=off: as before -----------------------------------------------------------------
def test_auth_off_unchanged(client, settings):
    assert client.get("/api/store/k").status_code == 204
    assert client.get("/api/auth/me").json() == {"ok": True, "auth_mode": "off", "user": None,
                                                 "session": None}
    assert client.get("/api/auth/sessions").json()["error"] == "auth_off"
    assert client.post("/api/auth/signout-all").status_code == 404
    assert client.get("/auth/google/start").status_code == 404
    assert not settings.accounts_db.exists()


# ---- phone PIN when AUTH_MODE=google ------------------------------------------------------------
TS_NAME = "elisha-pc.tail1234.ts.net"
PHONE_IP = "100.88.1.2"
PIN = "482913"


def test_phone_pin_bound_to_account(gclient, gsettings, google, clock, accounts):
    s = dataclasses.replace(gsettings, phone_access=True, phone_hosts=(TS_NAME,))
    bob, _ = accounts.allow(BOB)
    ph = gclient(ip=PHONE_IP, host=TS_NAME, s=s)
    auth = phone.PhoneAuth(s.phone_db)
    # a PIN without an account: the phone is told to bind it
    auth.set_pin(PIN)
    r = ph.get("/")
    assert r.status_code == 403 and "--email" in r.text
    auth.set_pin(PIN, BOB)
    r = ph.get("/")
    assert r.status_code == 200 and 'name="pin"' in r.text
    assert ph.get("/api/store/k").json()["sign_in"] == "pin"
    # Google sign-in is for this PC only (Google cannot redirect to a tailnet name)
    assert ph.get("/auth/google/start").status_code == 303
    r = ph.post(phone.LOGIN_PATH, content=b"pin=000000",
                headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 401
    r = ph.post(phone.LOGIN_PATH, content=f"pin={PIN}".encode(),
                headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 303 and "samesite=strict" in r.headers["set-cookie"].lower()
    assert ph.put("/api/store/from-phone", content=b"1").status_code == 200
    me = ph.get("/api/auth/me").json()
    assert me["user"]["email"] == BOB and me["session"]["method"] == "pin"
    us = accounts.settings_for(s, bob)
    assert sqlite3.connect(us.db_path).execute("SELECT key FROM kv").fetchall() == [("from-phone",)]
    # the PC itself still needs a Google session, even with phone access on
    pc = gclient(s=s)
    assert pc.get("/api/store/from-phone").status_code == 401
    # PIN sessions last 7 days too, and a PIN change signs them out
    assert accounts.revoke_all(reason="PIN changed", method="pin") == 1
    assert ph.get("/api/store/from-phone").status_code == 401
    # disallowing the account makes its PIN useless
    accounts.disallow(BOB)
    r = ph.post(phone.LOGIN_PATH, content=f"pin={PIN}".encode(),
                headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code == 403


def test_pin_cli_email(data_dir, monkeypatch, capsys):
    from server import pin as pin_cli
    from server.accounts import main as acc_main
    from server.settings import load_settings
    answers = iter([PIN, PIN, PIN, PIN])
    ask = lambda prompt: next(answers)                      # noqa: E731
    monkeypatch.setenv("AUTH_MODE", "google")
    assert pin_cli.main(["set"], ask=ask) == 1              # google: must name the account
    assert "--email" in capsys.readouterr().out
    assert pin_cli.main(["set", "--email", BOB], ask=ask) == 1     # not approved
    assert acc_main(["allow", BOB]) == 0
    assert pin_cli.main(["set", "--email", BOB.upper()], ask=ask) == 0
    assert f"PIN set for {BOB}" in capsys.readouterr().out
    s = load_settings()
    assert phone.PhoneAuth(s.phone_db).pin_email() == BOB
    assert pin_cli.main(["status"]) == 0 and f"signs in as {BOB}" in capsys.readouterr().out
    monkeypatch.setenv("AUTH_MODE", "off")                  # off: as before, no email needed
    assert pin_cli.main(["set"], ask=ask) == 0


def test_unhandled_error_still_has_security_headers(make_client):
    from fastapi.testclient import TestClient
    c = make_client()
    app = c.app

    @app.get("/api/boom-for-test")
    def boom():
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50000),
                    base_url="http://127.0.0.1:8765") as tc:
        r = tc.get("/api/boom-for-test")
    assert r.status_code == 500
    assert "content-security-policy" in r.headers and r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
