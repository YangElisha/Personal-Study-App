"""End to end over real HTTP: uvicorn on 127.0.0.1, a free port, a scratch DATA_DIR.

Checks URL decoding exactly as a browser's encodeURIComponent + real uvicorn do it
(Starlette's TestClient decodes paths twice, so "%" keys can only be checked here).
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest
import uvicorn
from server.app import create_app


@pytest.fixture
def live(settings, tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, app_dir=tmp_path / "no-app",
                                                      modules_md_paths=[tmp_path / "MODULES.md"]),
                                           host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(10)


def call(method, url, body=None):
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def enc(key):
    # what JavaScript's encodeURIComponent produces
    return quote(key, safe="-_.!~*'()")


KEYS = ["deck:abc", "100%", "a%25b", "%", "sp ace?#&=+%", "naïve ✓ 日本", "a/b", "q'(x)*!~"]


@pytest.mark.parametrize("key", KEYS)
def test_real_http_roundtrip(live, key):
    body = '{"k": %s}' % json.dumps(key)
    st, txt = call("PUT", f"{live}/api/store/{enc(key)}", body.encode("utf-8"))
    assert st == 200 and json.loads(txt)["key"] == key
    st, txt = call("GET", f"{live}/api/store/{enc(key)}")
    assert st == 200 and txt == body
    st, txt = call("GET", f"{live}/api/store?prefix={enc(key)}")
    assert st == 200 and key in json.loads(txt)["keys"]
    st, _ = call("DELETE", f"{live}/api/store/{enc(key)}")
    assert st == 200
    assert call("GET", f"{live}/api/store/{enc(key)}") == (204, "")


def test_real_http_prefix_percent_is_literal(live):
    for k in ["a%b", "axb", "a%c"]:
        call("PUT", f"{live}/api/store/{enc(k)}", b"1")
    st, txt = call("GET", f"{live}/api/store?prefix={enc('a%')}")
    assert json.loads(txt)["keys"] == ["a%b", "a%c"]


def test_real_http_missing_vs_null_and_ai(live):
    assert call("GET", f"{live}/api/store/{enc('deck:x')}") == (204, "")
    assert call("GET", f"{live}/favicon.ico") == (204, "")
    call("PUT", f"{live}/api/store/{enc('deck:x')}", b"null")
    assert call("GET", f"{live}/api/store/{enc('deck:x')}") == (200, "null")
    st, txt = call("POST", f"{live}/api/ai",
                   b'{"max_tokens":16,"messages":[{"role":"user","content":"hi"}]}')
    assert st == 503 and json.loads(txt)["error"]["type"] == "ai_not_configured"
