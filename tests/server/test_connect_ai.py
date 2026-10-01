"""Connecting other AIs (docs/CONNECT-AI.md): Codex / Gemini / any CLI online, any Ollama model or
an OpenAI-compatible local server (LM Studio, llama.cpp, Jan, vLLM). Fakes only."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from server import ai
from test_ai import PNG_1PX, ask, ai_client, closed_port, ollama, online  # noqa: F401 (fixtures)

FAKE_CLI = Path(__file__).resolve().parent / "fake_cli.py"
NO_FILE = Path("no-such-settings.env")


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    log_dir = tmp_path / "cli-log"
    log_dir.mkdir()
    wrapper = tmp_path / "fakecli.cmd"
    wrapper.write_text(f'@"{sys.executable}" "{FAKE_CLI}" %*\r\n', encoding="ascii")
    monkeypatch.setenv("FAKE_CLI_LOG", str(log_dir))
    monkeypatch.setenv("FAKE_CLI_MODE", "ok")

    class F:
        path = str(wrapper)

        @staticmethod
        def calls():
            return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(log_dir.glob("*.json"))]

        @staticmethod
        def mode(m):
            monkeypatch.setenv("FAKE_CLI_MODE", m)
    return F


def use(monkeypatch, **kv):
    for k, v in kv.items():
        monkeypatch.setenv(k, v)


def picture():
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": PNG_1PX}},
            {"type": "text", "text": "read this"}]


# ---- settings ------------------------------------------------------------------------------
def test_old_settings_still_mean_claude_and_qwen():
    c = ai.load_ai_config(environ={"CLAUDE_CLI": "on"}, env_file=NO_FILE)
    assert (c.online, c.online_name, c.local, c.local_name) == ("claude", "Claude", "ollama", "Qwen")
    c = ai.load_ai_config(environ={"CLAUDE_CLI": "off"}, env_file=NO_FILE)
    assert c.online == "off" and not c.claude_cli


def test_presets_and_names():
    c = ai.load_ai_config(environ={"ONLINE_AI": "codex", "OLLAMA_MODEL": "llama3.1:8b"}, env_file=NO_FILE)
    assert (c.online_name, c.online_path, c.reach_host, c.local_name) == \
        ("Codex", "codex", "api.openai.com", "Llama")
    c = ai.load_ai_config(environ={"ONLINE_AI": "gemini", "LOCAL_AI": "openai",
                                   "LOCAL_AI_MODEL": "gemma-3-12b", "LOCAL_AI_NUM_CTX": "32768",
                                   "LOCAL_AI_NAME": "My Gemma"}, env_file=NO_FILE)
    assert (c.online_name, c.online_images, c.local, c.local_name, c.num_ctx) == \
        ("Gemini", False, "openai", "My Gemma", 32768)
    c = ai.load_ai_config(environ={"ONLINE_AI": "custom", "ONLINE_AI_COMMAND": "mycli run -"},
                          env_file=NO_FILE)
    assert c.online_name == "Mycli"
    assert ai.local_display_name("qwen3.5:9b") == "Qwen" and ai.local_display_name("gemma3") == "Gemma"


# ---- Codex -----------------------------------------------------------------------------------
def test_codex_answers_through_its_own_cli(ai_client, fake_cli, online, monkeypatch):
    use(monkeypatch, ONLINE_AI="codex", ONLINE_AI_PATH=fake_cli.path, ONLINE_AI_REACH_HOST=online)
    c = ai_client()
    d = ask(c, "What is a process model? END").json()
    assert d["model_used"] == "claude" and d["ai_name"] == "Codex"
    text = d["content"][0]["text"]
    assert text.startswith("CLI:") and text.endswith("What is a process model? END")
    assert "progress noise" not in text                  # the answer file, not what it printed
    call = fake_cli.calls()[0]
    a = call["argv"]
    assert a[0] == "exec" and "--skip-git-repo-check" in a and a[a.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in a
    assert a[-1] == "-" and "What is a process model?" in call["stdin"]
    route = c.get("/api/ai/route").json()
    assert route["model"] == "claude" and route["cloud_name"] == "Codex"


def test_codex_reads_pictures_as_files(ai_client, fake_cli, online, monkeypatch):
    use(monkeypatch, ONLINE_AI="codex", ONLINE_AI_PATH=fake_cli.path, ONLINE_AI_REACH_HOST=online)
    assert ask(ai_client(), picture()).json()["ai_name"] == "Codex"
    call = fake_cli.calls()[0]
    assert "--image" in call["argv"] and call["images_exist"] == [True]


def test_signed_out_codex_pauses_and_says_how_to_sign_in(ai_client, fake_cli, online, monkeypatch):
    use(monkeypatch, ONLINE_AI="codex", ONLINE_AI_PATH=fake_cli.path, ONLINE_AI_REACH_HOST=online)
    fake_cli.mode("signedout")
    c = ai_client()
    d = ask(c, "hi").json()
    assert d["model_used"] == "qwen" and "Codex is signed out" in d["fallback_reason"]
    assert "codex login" in d["fallback_reason"]
    ask(c, "again")
    assert len(fake_cli.calls()) == 1                  # paused: not tried on every request
    r = c.get("/api/ai/route").json()
    assert r["pause_reason"] == "signin" and r["signin_help"] == "open a terminal and run: codex login"


def test_codex_usage_limit_pauses_it(ai_client, fake_cli, online, monkeypatch):
    use(monkeypatch, ONLINE_AI="codex", ONLINE_AI_PATH=fake_cli.path, ONLINE_AI_REACH_HOST=online)
    fake_cli.mode("limit")
    c = ai_client()
    assert ask(c, "hi").json()["model_used"] == "qwen"
    assert c.get("/api/ai/route").json()["pause_reason"] == "limit"


# ---- Gemini ----------------------------------------------------------------------------------
def test_gemini_text_on_stdin_and_pictures_go_to_the_local_ai(ai_client, fake_cli, online, ollama, monkeypatch):
    use(monkeypatch, ONLINE_AI="gemini", ONLINE_AI_PATH=fake_cli.path, ONLINE_AI_REACH_HOST=online)
    c = ai_client()
    d = ask(c, "Explain waterfall END").json()
    assert d["ai_name"] == "Gemini" and d["content"][0]["text"].endswith("Explain waterfall END")
    g = fake_cli.calls()[0]["argv"]
    assert "--prompt" in g and g[g.index("--output-format") + 1] == "text"
    d = ask(c, picture()).json()
    assert d["model_used"] == "qwen" and "can't read pictures" in d["fallback_reason"]


# ---- any other CLI ---------------------------------------------------------------------------
def test_custom_command_with_prompt_and_answer_files(ai_client, fake_cli, online, monkeypatch):
    use(monkeypatch, ONLINE_AI="custom", ONLINE_AI_NAME="My AI", ONLINE_AI_REACH_HOST=online,
        ONLINE_AI_COMMAND=f'"{fake_cli.path}" --prompt-file {{prompt_file}} --out {{output_file}}')
    d = ask(ai_client(), "custom question END").json()
    assert d["ai_name"] == "My AI" and d["content"][0]["text"].endswith("custom question END")
    assert fake_cli.calls()[0]["stdin"] == ""          # the prompt went in the file, not stdin


# ---- local: an OpenAI-compatible server ------------------------------------------------------
class FakeOpenAI:
    def __init__(self):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                last = body["messages"][-1]["content"]
                text = last if isinstance(last, str) else " ".join(p.get("text", "") for p in last)
                b = json.dumps({"choices": [{"message": {"role": "assistant",
                                                         "content": "<think>x</think>LOCAL:" + text[-20:]},
                                             "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 11, "completion_tokens": 5}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def test_openai_compatible_local_server(ai_client, monkeypatch):
    srv = FakeOpenAI()
    use(monkeypatch, LOCAL_AI="openai", LOCAL_AI_URL=srv.url, LOCAL_AI_MODEL="llama-3.1-8b-instruct")
    c = ai_client()
    d = ask(c, "hello local END").json()
    assert d["model_used"] == "qwen" and d["ai_name"] == "Llama"
    assert d["content"][0]["text"] == "LOCAL:hello local END"            # thinking stripped
    path, body = srv.requests[0]
    assert path == "/v1/chat/completions" and body["model"] == "llama-3.1-8b-instruct"
    ask(c, picture())
    parts = srv.requests[1][1]["messages"][-1]["content"]
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert c.get("/api/ai/route").json()["local_name"] == "Llama"
    srv.server.shutdown()


def test_no_ai_at_all_says_so(ai_client, monkeypatch):
    use(monkeypatch, LOCAL_AI="off")
    r = ask(ai_client(), "hi")
    assert r.status_code == 503 and "LOCAL_AI=off" in r.json()["error"]["message"]


def test_reload_picks_up_new_settings(ai_client, monkeypatch):
    c = ai_client()
    assert c.get("/api/ai/route").json()["local_name"] == "Qwen"
    use(monkeypatch, OLLAMA_MODEL="mistral:7b")
    assert c.post("/api/ai/reload").json()["local_name"] == "Mistral"


def test_route_says_whether_the_local_ai_is_running(ai_client, ollama, monkeypatch):
    assert ai_client().get("/api/ai/route").json()["local_ok"] is True       # the fake Ollama answers
    use(monkeypatch, LOCAL_AI="off")
    r = ai_client().get("/api/ai/route").json()
    assert r["local_ok"] is False and r["cloud_name"] == "Online AI"
