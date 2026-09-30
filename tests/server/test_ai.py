"""POST /api/ai — the AI router (Phase 5), against a fake Ollama and a fake `claude` program.

Fake Ollama: a local HTTP server that behaves like Ollama 0.34's /api/chat (checked against
the real one): with truncate:false a prompt over num_ctx is refused with 400
exceed_context_size_error; a reply that hits num_predict ends with done_reason "length".
It "counts" 1 token per 4 characters and echoes the last 40 characters of the prompt, so a
test can see whether the end of a prompt arrived.

Fake claude: tests/server/fake_claude.py behind a .cmd wrapper, standing in for the real
program. It records its argv, working folder, stdin and environment, and prints a result
object shaped like `claude -p --output-format json` 2.1.258's.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FAKE_CLAUDE = HERE / "fake_claude.py"


# ---- fake Ollama -------------------------------------------------------------------------
class FakeOllama:
    def __init__(self):
        self.requests: list[dict] = []
        self.mode = "ok"          # ok | missing_model
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                if outer.mode == "missing_model":
                    return self._send(404, {"error": f"model '{body['model']}' not found"})
                prompt = "".join(m["content"] for m in body["messages"])
                n_prompt = len(prompt) // 4 + 258 * sum(len(m.get("images", []))
                                                        for m in body["messages"])
                ctx = body["options"]["num_ctx"]
                if n_prompt > ctx:
                    if body.get("truncate") is False:
                        inner = {"error": {"code": 400, "message":
                                           f"request ({n_prompt} tokens) exceeds the available "
                                           f"context size ({ctx} tokens), try increasing it",
                                           "type": "exceed_context_size_error",
                                           "n_prompt_tokens": n_prompt, "n_ctx": ctx}}
                        return self._send(400, {"error": json.dumps(inner)})
                    prompt = prompt[:ctx * 4]                 # what Ollama would do silently
                npred = body["options"].get("num_predict", 10**9)
                text = "<think>pondering</think>ECHO:" + prompt[-40:]
                done = "stop"
                if npred < 20:
                    text, done = text[:npred], "length"
                self._send(200, {"model": body["model"], "message": {"role": "assistant",
                                                                     "content": text},
                                 "done": True, "done_reason": done,
                                 "prompt_eval_count": n_prompt, "eval_count": 7})

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ollama():
    f = FakeOllama()
    yield f
    f.close()


@pytest.fixture
def online():
    """A listening socket standing in for api.anthropic.com:443."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(50)
    yield f"127.0.0.1:{s.getsockname()[1]}"
    s.close()


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    log_dir = tmp_path / "claude-log"
    log_dir.mkdir()
    wrapper = tmp_path / "fakeclaude.cmd"
    wrapper.write_text(f'@"{sys.executable}" "{FAKE_CLAUDE}" %*\r\n', encoding="ascii")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log_dir))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-must-not-reach-claude")

    class FC:
        path = str(wrapper)

        @staticmethod
        def calls() -> list[dict]:
            return [json.loads(p.read_text(encoding="utf-8"))
                    for p in sorted(log_dir.glob("*.json"))]

        @staticmethod
        def mode(m):
            monkeypatch.setenv("FAKE_CLAUDE_MODE", m)
    return FC


@pytest.fixture
def ai_client(make_client, monkeypatch, ollama):
    """make(claude=..., reach=..., num_ctx=...) -> TestClient with those AI settings."""
    clients = []

    def make(claude="off", reach=None, num_ctx=16384, claude_path="no-such-claude",
             ollama_url=None):
        monkeypatch.setenv("OLLAMA_URL", ollama_url or ollama.url)
        monkeypatch.setenv("OLLAMA_NUM_CTX", str(num_ctx))
        monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
        monkeypatch.setenv("CLAUDE_CLI", claude)
        monkeypatch.setenv("CLAUDE_CLI_PATH", claude_path)
        monkeypatch.setenv("CLAUDE_REACH_HOST", reach or f"127.0.0.1:{closed_port()}")
        c = make_client()
        c.__enter__()
        clients.append(c)
        return c
    yield make
    for c in clients:
        c.__exit__(None, None, None)


def ask(client, content, max_tokens=1000):
    return client.post("/api/ai", json={"model": "claude-sonnet-4-6", "max_tokens": max_tokens,
                                        "messages": [{"role": "user", "content": content}]})


PNG_1PX = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()


# ---- shape and stop_reason ---------------------------------------------------------------
def test_qwen_answer_has_anthropic_shape(ai_client, ollama):
    c = ai_client()
    r = ask(c, [{"type": "text", "text": "Say hello END-OF-PROMPT"}])
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "message" and d["role"] == "assistant"
    assert d["content"] == [{"type": "text", "text": "ECHO:Say hello END-OF-PROMPT"}]
    assert "<think>" not in d["content"][0]["text"]                # thinking stripped
    assert d["stop_reason"] == "end_turn" and d["model_used"] == "qwen"
    sent = ollama.requests[-1]
    assert sent["options"]["num_ctx"] == 16384 and sent["options"]["num_predict"] == 1000
    assert sent["think"] is False and sent["truncate"] is False and sent["shift"] is False
    assert sent["stream"] is False and sent["model"] == "qwen3.5:9b"


def test_qwen_length_maps_to_max_tokens(ai_client):
    d = ask(ai_client(), "Count to a thousand", max_tokens=5).json()
    assert d["stop_reason"] == "max_tokens" and d["model_used"] == "qwen"


@pytest.mark.parametrize("mode,expected", [("ok", "end_turn"), ("max_tokens", "max_tokens"),
                                           ("no_stop_reason", "end_turn")])
def test_claude_stop_reason_mapping(ai_client, fake_claude, online, mode, expected):
    fake_claude.mode(mode)
    d = ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path), "hi").json()
    assert d["model_used"] == "claude" and d["stop_reason"] == expected
    assert d["content"][0]["type"] == "text"


# ---- routing -------------------------------------------------------------------------------
def test_claude_off_goes_to_qwen(ai_client, fake_claude, online, ollama):
    d = ask(ai_client(claude="off", reach=online, claude_path=fake_claude.path), "hi").json()
    assert d["model_used"] == "qwen" and fake_claude.calls() == [] and len(ollama.requests) == 1


def test_online_claude_on_goes_to_claude(ai_client, fake_claude, online, ollama):
    d = ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path),
            "Reply ok END").json()
    assert d["model_used"] == "claude" and d["content"][0]["text"] == "CLAUDE:Reply ok END"
    assert len(fake_claude.calls()) == 1 and ollama.requests == []


def test_offline_goes_to_qwen(ai_client, fake_claude, ollama):
    # reachability check fails (closed port) = offline
    t = time.time()
    d = ask(ai_client(claude="on", claude_path=fake_claude.path), "hi").json()
    assert d["model_used"] == "qwen" and fake_claude.calls() == []
    assert time.time() - t < 10


def test_image_goes_to_claude_when_online(ai_client, fake_claude, online, ollama):
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    d = ask(c, [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                              "data": PNG_1PX}},
                {"type": "text", "text": "What is on this slide?"}]).json()
    assert d["model_used"] == "claude" and ollama.requests == []
    assert d["content"][0]["text"] == "CLAUDE-SEES:image,text:What is on this slide?"
    call = fake_claude.calls()[0]
    assert "--input-format" in call["argv"] and "stream-json" in call["argv"]
    assert PNG_1PX in call["stdin"] and PNG_1PX not in " ".join(call["argv"])


def test_image_goes_to_qwen_when_offline(ai_client, fake_claude, ollama):
    c = ai_client(claude="on", claude_path=fake_claude.path)     # reach check fails = offline
    d = ask(c, [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                              "data": PNG_1PX}},
                {"type": "text", "text": "What is on this slide?"}]).json()
    assert d["model_used"] == "qwen" and fake_claude.calls() == []
    m = ollama.requests[-1]["messages"][-1]
    assert m["images"] == [PNG_1PX] and m["content"] == "What is on this slide?"


def test_image_claude_failure_falls_back_to_qwen(ai_client, fake_claude, online, ollama):
    fake_claude.mode("error")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    d = ask(c, [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                              "data": PNG_1PX}},
                {"type": "text", "text": "What is on this slide?"}]).json()
    assert d["model_used"] == "qwen" and d["fallback_from"] == "claude"
    assert ollama.requests[-1]["messages"][-1]["images"] == [PNG_1PX]


def test_claude_failure_retried_once_on_qwen(ai_client, fake_claude, online, ollama):
    fake_claude.mode("error")
    d = ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path), "hi").json()
    assert d["model_used"] == "qwen" and d["fallback_from"] == "claude"
    assert "error" in d["fallback_reason"] and len(fake_claude.calls()) == 1
    assert len(ollama.requests) == 1


def test_usage_limit_pauses_claude_and_goes_straight_to_qwen(ai_client, fake_claude, online, ollama):
    fake_claude.mode("limit")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    d = ask(c, "first").json()
    assert d["model_used"] == "qwen" and "usage limit" in d["fallback_reason"]
    d2 = ask(c, "second").json()
    assert d2["model_used"] == "qwen" and d2["fallback_from"] == "claude"
    assert len(fake_claude.calls()) == 1          # the second request never tried Claude
    r = c.get("/api/ai/route").json()
    assert r["model"] == "qwen" and r["claude_paused"] is True


def test_ordinary_claude_error_does_not_pause(ai_client, fake_claude, online, ollama):
    fake_claude.mode("error")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    ask(c, "first"); ask(c, "second")
    assert len(fake_claude.calls()) == 2
    assert c.get("/api/ai/route").json()["claude_paused"] is False


def test_fast_tier_uses_haiku(ai_client, fake_claude, online):
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    c.post("/api/ai", json={"model": "x", "max_tokens": 50, "tier": "fast",
                            "messages": [{"role": "user", "content": "hi"}]})
    argv = fake_claude.calls()[0]["argv"]
    assert argv[argv.index("--model") + 1] == "haiku"


def test_claude_runs_at_low_effort(ai_client, fake_claude, online):
    ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path), "hi")
    argv = fake_claude.calls()[0]["argv"]
    assert argv[argv.index("--effort") + 1] == "low"
    assert fake_claude.calls()[0]["thinking"] == "0"          # thinking switched off


def test_claude_uses_sonnet_by_default(ai_client, fake_claude, online):
    ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path), "hi")
    argv = fake_claude.calls()[0]["argv"]
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_claude_missing_program_falls_back(ai_client, online):
    d = ask(ai_client(claude="on", reach=online, claude_path="drill-no-such-claude"), "hi").json()
    assert d["model_used"] == "qwen" and "not found" in d["fallback_reason"]


# ---- claude -p invocation ------------------------------------------------------------------
def test_40000_char_prompt_reaches_claude_whole_on_stdin(ai_client, fake_claude, online):
    marker = "UNIQUE-MARKER-7f3a9c"
    prompt = ("Drill study text. " * 3000)[:40000 - len(marker)] + marker
    assert len(prompt) == 40000
    d = ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path), prompt).json()
    assert d["model_used"] == "claude" and d["content"][0]["text"].endswith(marker)
    (call,) = fake_claude.calls()
    assert call["stdin"] == prompt                                # whole, byte for byte
    assert not any(marker in a for a in call["argv"])             # never on the command line
    argv = call["argv"]
    assert argv[:1] == ["-p"] and argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--tools") + 1] == ""                  # no tools
    assert "--no-session-persistence" in argv
    assert call["cwd_listing"] == []                              # empty working folder
    assert Path(call["cwd"]).resolve() != Path.cwd().resolve()
    assert call["has_api_key"] is False                           # no API key passed on


def test_non_ascii_prompt_survives_stdin(ai_client, fake_claude, online):
    prompt = "Définition: naïve café — 日本語 ✓ END"
    d = ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path), prompt).json()
    assert fake_claude.calls()[0]["stdin"] == prompt
    assert d["content"][0]["text"] == "CLAUDE:" + prompt[-40:]


def test_at_most_four_claude_calls_at_once(ai_client, fake_claude, online):
    fake_claude.mode("slow")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    results = []
    ts = [threading.Thread(target=lambda: results.append(ask(c, "hi").json()))
          for _ in range(7)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(60)
    assert len(results) == 7 and all(r["model_used"] == "claude" for r in results)
    spans = [(x["start"], x["end"]) for x in fake_claude.calls()]
    most = max(sum(1 for s, e in spans if s <= t < e) for t, _ in spans)
    assert most <= 4


# ---- context limit -------------------------------------------------------------------------
def test_prompt_over_qwen_context_is_refused_loudly(ai_client, ollama):
    c = ai_client(num_ctx=2048)
    r = ask(c, "x" * (2048 * 4 + 400) + "MARKER")
    assert r.status_code == 400
    e = r.json()
    assert e["type"] == "error" and e["error"]["type"] == "invalid_request_error"
    msg = e["error"]["message"]
    assert "too long" in msg and "2048" in msg and len(msg) <= 160
    # must not look like something the app retries or calls "file too large"
    import re
    assert not re.search(r"internal|overloaded|timeout|too large|request entity", msg, re.I)


def test_prompt_just_under_qwen_context_arrives_whole(ai_client, ollama):
    c = ai_client(num_ctx=2048)
    prompt = "y" * (2048 * 4 - 40) + "MARKER-AT-END"
    d = ask(c, prompt).json()
    assert d["model_used"] == "qwen" and d["content"][0]["text"].endswith("MARKER-AT-END")
    assert ollama.requests[-1]["messages"][-1]["content"] == prompt


# ---- nothing available -----------------------------------------------------------------------
def test_no_model_at_all_is_503_ai_not_configured(ai_client):
    r = ask(ai_client(ollama_url=f"http://127.0.0.1:{closed_port()}"), "hi")
    assert r.status_code == 503
    e = r.json()["error"]
    assert e["type"] == "ai_not_configured" and "CLAUDE_CLI=off" in e["message"]


def test_claude_fails_and_no_ollama_is_503(ai_client, fake_claude, online):
    fake_claude.mode("error")
    r = ask(ai_client(claude="on", reach=online, claude_path=fake_claude.path,
                      ollama_url=f"http://127.0.0.1:{closed_port()}"), "hi")
    assert r.status_code == 503 and r.json()["error"]["type"] == "ai_not_configured"


def test_model_not_installed_is_503(ai_client, ollama):
    ollama.mode = "missing_model"
    r = ask(ai_client(), "hi")
    assert r.status_code == 503 and "not installed" in r.json()["error"]["message"]


# ---- bad requests ----------------------------------------------------------------------------
def test_pdf_document_block_refused(ai_client):
    r = ask(ai_client(), [{"type": "document", "source": {"type": "base64",
                                                           "media_type": "application/pdf",
                                                           "data": "JVBERi0="}}])
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"


def test_malformed_body(ai_client):
    c = ai_client()
    assert c.post("/api/ai", content=b"not json").status_code == 400
    assert c.post("/api/ai", json={"messages": []}).status_code == 400


# ---- GET /api/ai/route: lets the app size a prompt for Qwen -------------------------------
def test_route_says_qwen_with_its_context_when_claude_off(ai_client, online):
    d = ai_client(claude="off", reach=online, num_ctx=8192).get("/api/ai/route").json()
    assert d == {"model": "qwen", "num_ctx": 8192, "claude_paused": False, "pause_reason": ""}


def test_route_says_qwen_when_offline(ai_client, fake_claude):
    d = ai_client(claude="on", claude_path=fake_claude.path, num_ctx=8192).get("/api/ai/route").json()
    assert d["model"] == "qwen"


def test_route_says_claude_when_online(ai_client, fake_claude, online):
    d = ai_client(claude="on", reach=online, claude_path=fake_claude.path).get("/api/ai/route").json()
    assert d["model"] == "claude" and fake_claude.calls() == []


# ---- supervisor requests: Claude only, never Qwen ------------------------------------------
def only_claude(client, text):
    return client.post("/api/ai", json={"model": "x", "max_tokens": 50, "only": "claude",
                                        "messages": [{"role": "user", "content": text}]})


def test_only_claude_is_answered_by_claude(ai_client, fake_claude, online, ollama):
    d = only_claude(ai_client(claude="on", reach=online, claude_path=fake_claude.path), "check").json()
    assert d["model_used"] == "claude" and d["elapsed_ms"] >= 0
    assert not ollama.requests


def test_only_claude_never_falls_back_to_qwen(ai_client, fake_claude, online, ollama):
    fake_claude.mode("error")
    r = only_claude(ai_client(claude="on", reach=online, claude_path=fake_claude.path), "check")
    assert r.status_code == 503 and r.json()["error"]["type"] == "claude_unavailable"
    assert not ollama.requests


def test_only_claude_refused_while_paused_or_switched_off(ai_client, fake_claude, online, ollama):
    fake_claude.mode("limit")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    ask(c, "first")                                    # hits the limit, pauses Claude
    r = only_claude(c, "check")
    assert r.status_code == 503 and "paused" in r.json()["error"]["message"]
    r = only_claude(ai_client(claude="off"), "check")
    assert r.status_code == 503 and r.json()["error"]["type"] == "claude_unavailable"


def test_every_reply_says_how_long_it_took(ai_client, ollama):
    assert ask(ai_client(), "hi").json()["elapsed_ms"] >= 0


def test_a_failed_reach_check_is_retried_soon_a_good_one_is_cached(monkeypatch):
    import asyncio
    from server import ai as aim
    r = aim.Router(aim.load_ai_config())
    answers = iter([False, True])
    monkeypatch.setattr(r, "_connect", lambda: next(answers))
    clock = [1000.0]
    monkeypatch.setattr(aim.time, "monotonic", lambda: clock[0])
    assert asyncio.run(r.claude_reachable()) is False
    clock[0] += aim.REACH_FAIL_CACHE_SECONDS + 0.1          # a blip: asked again, now reachable
    assert asyncio.run(r.claude_reachable()) is True
    clock[0] += 5                                           # a success is remembered
    assert asyncio.run(r.claude_reachable()) is True


# ---- Claude Code signed out ----------------------------------------------------------------
def test_signed_out_pauses_claude_and_says_how_to_sign_in(ai_client, fake_claude, online, ollama):
    fake_claude.mode("signedout")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    d = ask(c, "first").json()
    assert d["model_used"] == "qwen" and "/login" in d["fallback_reason"]
    d2 = ask(c, "second").json()
    assert d2["model_used"] == "qwen" and "signed out" in d2["fallback_reason"]
    assert len(fake_claude.calls()) == 1              # not tried again on every request
    r = c.get("/api/ai/route").json()
    assert r["claude_paused"] is True and r["pause_reason"] == "signin"


def test_try_claude_again_lifts_the_pause(ai_client, fake_claude, online, ollama):
    fake_claude.mode("signedout")
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    ask(c, "first")
    fake_claude.mode("ok")                            # signed in again
    r = c.post("/api/ai/claude/retry").json()
    assert r["model"] == "claude" and r["claude_paused"] is False and r["pause_reason"] == ""
    assert ask(c, "again").json()["model_used"] == "claude"


def test_only_qwen_never_asks_claude(ai_client, fake_claude, online, ollama):
    c = ai_client(claude="on", reach=online, claude_path=fake_claude.path)
    d = c.post("/api/ai", json={"model": "x", "max_tokens": 50, "only": "qwen",
                                "messages": [{"role": "user", "content": "hi"}]}).json()
    assert d["model_used"] == "qwen" and "fallback_from" not in d
    assert not fake_claude.calls()
