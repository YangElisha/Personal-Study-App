"""This PC only: loopback clients, localhost names, own-origin writes, security headers."""
from __future__ import annotations

import socket
import threading
import time
import urllib.request

import pytest
import uvicorn

from server.app import client_ip, create_app, split_host


@pytest.mark.parametrize("addr,ok", [
    ("127.0.0.1", True), ("127.5.5.5", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("100.64.0.1", False), ("192.168.1.5", False), ("10.1.2.3", False), ("8.8.8.8", False),
    ("fd7a:115c:a1e0::5", False), ("testclient", False), ("", False), (None, False),
])
def test_loopback_rule(addr, ok):
    ip = client_ip(addr)
    assert (ip is not None and ip.is_loopback) is ok


@pytest.mark.parametrize("hdr,host,port", [
    ("localhost:8765", "localhost", "8765"), ("LOCALHOST.:8765", "localhost", "8765"),
    ("[::1]:8765", "::1", "8765"), ("127.0.0.1", "127.0.0.1", ""),
])
def test_split_host(hdr, host, port):
    assert split_host(hdr) == (host, port)


@pytest.mark.parametrize("ip", ["100.88.1.2", "192.168.1.5", "8.8.8.8", "fd7a:115c:a1e0::5"])
def test_non_loopback_client_refused(make_client, ip):
    with make_client(client_ip=ip) as c:
        for r in (c.get("/api/health"), c.get("/"), c.put("/api/store/k", content=b"1")):
            assert r.status_code == 403 and r.json()["error"] == "forbidden_client"
            assert r.headers["x-frame-options"] == "DENY"
        assert c.get("/api/store/k").status_code == 403


def test_loopback_names_allowed(make_client):
    for base in ("http://127.0.0.1:8765", "http://localhost:8765", "http://[::1]:8765"):
        with make_client(base_url=base) as c:
            assert c.get("/api/health").status_code == 200, base


def test_no_sign_in_or_phone_routes(client):
    for p in ("/api/auth/me", "/auth/google/start", "/auth/signin"):
        assert client.get(p).status_code in (404, 405), p
    assert client.post("/api/phone/login", content=b"pin=123456").status_code in (404, 405)


def test_security_headers(make_client, tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
    with make_client(app_dir=app_dir) as c:
        for p in ("/", "/api/store/x", "/api/health", "/favicon.ico", "/no-such-file"):
            h = c.get(p).headers
            csp = h["content-security-policy"]
            assert csp.startswith("default-src 'self'; script-src 'self' 'unsafe-inline'"), p
            for part in ("connect-src 'self'", "img-src 'self' data: blob:",
                         "worker-src 'self' blob:", "font-src 'self'", "frame-ancestors 'none'",
                         "object-src 'none'", "base-uri 'none'", "form-action 'self'"):
                assert part in csp, (p, part)
            assert "google" not in csp
            assert h["x-content-type-options"] == "nosniff"
            assert h["referrer-policy"] == "no-referrer"
            assert h["x-frame-options"] == "DENY"
            if p.startswith("/api/"):
                assert h["cache-control"] == "no-store", p
        # refusals carry them too
        r = c.get("/api/health", headers={"host": "evil.example"})
        assert r.status_code == 403 and "content-security-policy" in r.headers


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


def test_binds_loopback_only(monkeypatch, settings):
    import server.__main__ as m
    seen = {}
    monkeypatch.setattr(m, "load_settings", lambda: settings)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(kw))
    assert m.main([]) == 0
    assert seen["host"] == "127.0.0.1" and seen["proxy_headers"] is False


def test_live_forwarded_header_cannot_fake_the_client(settings, tmp_path):
    """The client address comes from the socket only: X-Forwarded-For is ignored."""
    app = create_app(settings, app_dir=tmp_path / "no-app", modules_md_paths=[tmp_path / "M.md"])
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
    try:
        for xff in ("100.88.1.2", "8.8.8.8"):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/health",
                                         headers={"X-Forwarded-For": xff, "X-Real-IP": xff})
            with urllib.request.urlopen(req, timeout=5) as r:
                assert r.status == 200
    finally:
        srv.should_exit = True
        t.join(10)
