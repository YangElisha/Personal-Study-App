"""The AI router behind POST /api/ai (Phase 5). See docs/ARCHITECTURE.md, docs/OFFLINE-AI.md.

Per request (2026-09-29: Claude whenever online, Qwen only offline):
  1. CLAUDE_CLI=on and api.anthropic.com reachable within 2 s -> Claude via `claude -p`,
     text AND pictures (pictures go in as image blocks via --input-format stream-json).
  2. otherwise (offline, or CLAUDE_CLI=off) -> Qwen.
If Claude fails for any reason (e.g. usage limit) the request is retried once on Qwen; the
reply then says model_used "qwen" with fallback_from "claude" and the reason. A usage/rate
limit also pauses Claude for CLAUDE_LIMIT_PAUSE seconds, so the requests after it go straight
to Qwen instead of each failing on Claude first (GET /api/ai/route says claude_paused).
Claude runs Sonnet unless CLAUDE_MODEL says otherwise: building decks does not need the
largest model, and it spends far less of the user's Claude usage. A request with
"tier": "fast" runs CLAUDE_FAST_MODEL (Haiku) instead — available, but the app does not use it
for page images: Haiku misread small print on a real module and was no faster. Up to MAX_CLAUDE_AT_ONCE run in parallel.
Every call runs with --effort CLAUDE_CLI_EFFORT (low; not CLAUDE_EFFORT, which Claude Code itself uses): at Claude Code's default effort about three
quarters of each reply was hidden thinking — measured on a 4-concept teaching request, 7,038
tokens and 66 s against 1,809 tokens and 22 s at low, for nearly the same visible answer.
Thinking is switched off too (MAX_THINKING_TOKENS=0 for the child): Haiku still spent up to
11,000 tokens and 100 s "thinking" over one maths-heavy page it had ~800 characters to copy.

Claude is reached ONLY by running the official `claude` program: prompt on stdin, from an
empty temporary folder, no tools, one turn, JSON output. Claude Code's login is never read
here, and ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are removed from the child's environment
so it always uses the user's own Claude Code sign-in.

Qwen: options.num_ctx from OLLAMA_NUM_CTX on every request, think:false (Qwen3.5 is a
thinking model; the app wants the plain answer), truncate:false and shift:false so Ollama
refuses a prompt that doesn't fit (with its exact token count) instead of silently cutting
it, and ends a reply that runs out of room with done_reason "length" (-> "max_tokens").

If Claude Code is signed out ("Failed to authenticate: OAuth session expired…"), Claude is paused
for CLAUDE_SIGNIN_PAUSE seconds the same way, route says pause_reason "signin", and the reason
tells the user to sign in again; POST /api/ai/claude/retry lifts any pause at once.
A request with "only": "qwen" (the student picked Qwen in Ask the teacher) goes to Qwen and
never to Claude.
A request with "only": "claude" (the supervisor checking Qwen's work) never falls back: if
Claude is paused, unreachable or fails, it gets error claude_unavailable (503) instead.
Every reply carries elapsed_ms (whole request, fallback included) for the activity log.

Other AIs (MonoSpace 2026-10-01, docs/CONNECT-AI.md). The two slots are not tied to Claude and Qwen:
  ONLINE_AI = claude | codex | gemini | custom | off — the AI used when online, always through that
    company's own command-line program and the user's own sign-in (no API keys). Unset, it is
    "claude" when CLAUDE_CLI=on, else "off" (settings written before this keep working).
  LOCAL_AI = ollama | openai | off — the AI on this PC: any Ollama model (OLLAMA_MODEL), or any
    OpenAI-compatible local server (LM Studio, llama.cpp, Jan, vLLM) at LOCAL_AI_URL.
Replies keep model_used "claude" (the online slot) / "qwen" (the local slot), which the app and
saved decks already use, and add ai_name — what to call it on screen ("Codex", "Llama"...).
GET /api/ai/route gives both names.

Every answer has Anthropic's shape: {content:[{type:"text",text}], stop_reason, ...} plus
model_used "claude"|"qwen". Errors use Anthropic's error shape
{type:"error", error:{type, message}}.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from .settings import ENV_FILE, read_env_file

log = logging.getLogger("monospace.ai")

AI_KEYS = ("OLLAMA_URL", "OLLAMA_MODEL", "OLLAMA_NUM_CTX", "OLLAMA_TIMEOUT", "CLAUDE_CLI",
           "CLAUDE_CLI_PATH", "CLAUDE_MODEL", "CLAUDE_FAST_MODEL", "CLAUDE_CLI_EFFORT",
           "CLAUDE_TIMEOUT", "CLAUDE_REACH_HOST",
           "ONLINE_AI", "ONLINE_AI_NAME", "ONLINE_AI_PATH", "ONLINE_AI_MODEL", "ONLINE_AI_COMMAND",
           "ONLINE_AI_IMAGES", "ONLINE_AI_REACH_HOST", "ONLINE_AI_SIGNIN",
           "LOCAL_AI", "LOCAL_AI_NAME", "LOCAL_AI_URL", "LOCAL_AI_MODEL", "LOCAL_AI_NUM_CTX")
AI_DEFAULTS = {
    "OLLAMA_URL": "http://localhost:11434",
    "OLLAMA_MODEL": "qwen3.5:9b",
    "OLLAMA_NUM_CTX": "8192",
    "OLLAMA_TIMEOUT": "900",          # seconds; an 8000-token transcription takes minutes
    "CLAUDE_CLI": "off",
    "CLAUDE_CLI_PATH": "claude",
    "CLAUDE_MODEL": "sonnet",         # "" = Claude Code's own default (often the largest model)
    "CLAUDE_FAST_MODEL": "haiku",     # "tier": "fast" requests (page transcription)
    "CLAUDE_CLI_EFFORT": "low",           # low | medium | high ... ; "" = Claude Code's default
    "CLAUDE_TIMEOUT": "600",
    # host:port the 2-second reachability check connects to. Only change it to simulate
    # being offline (e.g. 127.0.0.1:9) — the real check is api.anthropic.com:443.
    "CLAUDE_REACH_HOST": "api.anthropic.com:443",
    # other AIs (docs/CONNECT-AI.md); "" = the preset's own value
    "ONLINE_AI": "", "ONLINE_AI_NAME": "", "ONLINE_AI_PATH": "", "ONLINE_AI_MODEL": "",
    "ONLINE_AI_COMMAND": "", "ONLINE_AI_IMAGES": "", "ONLINE_AI_REACH_HOST": "", "ONLINE_AI_SIGNIN": "",
    "LOCAL_AI": "ollama", "LOCAL_AI_NAME": "", "LOCAL_AI_URL": "http://localhost:1234/v1",
    "LOCAL_AI_MODEL": "", "LOCAL_AI_NUM_CTX": "",
}

# The online AIs MonoSpace knows how to run. Each is the company's own CLI, signed in by the user.
ONLINE_PRESETS = {
    "claude": {"name": "Claude", "path": "claude", "reach": "api.anthropic.com:443", "images": True,
               "signin": "open a terminal, run claude, then type /login"},
    "codex":  {"name": "Codex", "path": "codex", "reach": "api.openai.com:443", "images": True,
               "signin": "open a terminal and run: codex login"},
    "gemini": {"name": "Gemini", "path": "gemini", "reach": "generativelanguage.googleapis.com:443",
               "images": False, "signin": "open a terminal, run gemini and sign in again"},
    "custom": {"name": "", "path": "", "reach": "1.1.1.1:443", "images": False,
               "signin": "sign in to it again"},
}


def local_display_name(model: str) -> str:
    """'qwen3.5:9b' -> 'Qwen', 'llama3.1:8b' -> 'Llama', 'gemma3' -> 'Gemma'."""
    m = re.match(r"[A-Za-z]+", (model or "").split("/")[-1])
    return m.group(0).capitalize() if m else (model or "Local AI")

CLAUDE_SYSTEM = ("You are answering a request from MonoSpace, a personal study app. Reply to the "
                 "user's message directly, following its instructions exactly. You have no "
                 "tools; answer from the message alone.")

REACH_TIMEOUT = 2.0
REACH_CACHE_SECONDS = 15.0
REACH_FAIL_CACHE_SECONDS = 3.0      # a failed check is retried soon: one network blip is not "offline"
MAX_CLAUDE_AT_ONCE = 4        # parallel `claude -p` processes; same usage, less waiting


@dataclass(frozen=True)
class AIConfig:
    ollama_url: str
    ollama_model: str
    num_ctx: int
    ollama_timeout: float
    claude_cli: bool
    claude_cli_path: str
    claude_model: str
    claude_fast_model: str
    claude_effort: str
    claude_timeout: float
    reach_host: str
    reach_port: int
    online: str = "claude"          # claude | codex | gemini | custom | off
    online_name: str = "Claude"
    online_path: str = ""
    online_model: str = ""
    online_command: str = ""
    online_images: bool = True
    online_signin: str = ""
    local: str = "ollama"           # ollama | openai | off
    local_name: str = "Qwen"
    local_url: str = ""
    local_model: str = ""


def load_ai_config(env_file=None, environ=None) -> AIConfig:
    """.env values; a process environment variable of the same name overrides them."""
    environ = os.environ if environ is None else environ
    v = dict(AI_DEFAULTS)
    v.update({k: x for k, x in read_env_file(ENV_FILE if env_file is None else env_file).items()
              if k in AI_KEYS})
    for k in AI_KEYS:
        if environ.get(k):
            v[k] = environ[k]
    claude_on = v["CLAUDE_CLI"].strip().lower() in ("on", "1", "true", "yes")
    online = v["ONLINE_AI"].strip().lower() or ("claude" if claude_on else "off")
    if online not in ONLINE_PRESETS:
        online = "off"
    pre = ONLINE_PRESETS.get(online, {})
    if online == "claude":
        reach = v["CLAUDE_REACH_HOST"]
    else:
        reach = v["ONLINE_AI_REACH_HOST"].strip() or pre.get("reach", "1.1.1.1:443")
    host, _, port = reach.rpartition(":")
    custom_name = "Online AI"
    if v["ONLINE_AI_COMMAND"].split():
        custom_name = v["ONLINE_AI_COMMAND"].split()[0].strip('"').replace("\\", "/").split("/")[-1]
        custom_name = re.sub(r"\.(exe|cmd|bat)$", "", custom_name, flags=re.I).capitalize()
    images = v["ONLINE_AI_IMAGES"].strip().lower()
    local = v["LOCAL_AI"].strip().lower() or "ollama"
    if local not in ("ollama", "openai", "off"):
        local = "ollama"
    local_model = v["LOCAL_AI_MODEL"].strip() if local == "openai" else v["OLLAMA_MODEL"]
    num_ctx = v["LOCAL_AI_NUM_CTX"].strip() if local == "openai" and v["LOCAL_AI_NUM_CTX"].strip() \
        else v["OLLAMA_NUM_CTX"]
    return AIConfig(
        ollama_url=v["OLLAMA_URL"].rstrip("/"),
        ollama_model=v["OLLAMA_MODEL"],
        num_ctx=int(num_ctx),
        ollama_timeout=float(v["OLLAMA_TIMEOUT"]),
        claude_cli=online != "off",          # "the online AI is switched on" (any of them)
        claude_cli_path=v["CLAUDE_CLI_PATH"],
        claude_model=v["CLAUDE_MODEL"].strip(),
        claude_fast_model=v["CLAUDE_FAST_MODEL"].strip(),
        claude_effort=v["CLAUDE_CLI_EFFORT"].strip().lower(),
        claude_timeout=float(v["CLAUDE_TIMEOUT"]),
        reach_host=host or reach,
        reach_port=int(port) if port else 443,
        online=online,
        online_name=v["ONLINE_AI_NAME"].strip() or pre.get("name") or custom_name,
        online_path=v["ONLINE_AI_PATH"].strip() or pre.get("path", ""),
        online_model=v["ONLINE_AI_MODEL"].strip(),
        online_command=v["ONLINE_AI_COMMAND"].strip(),
        online_images=(images in ("on", "1", "true", "yes")) if images else bool(pre.get("images")),
        online_signin=v["ONLINE_AI_SIGNIN"].strip() or pre.get("signin", "sign in to it again"),
        local=local,
        local_name=v["LOCAL_AI_NAME"].strip() or (local_display_name(local_model) if local != "off" else "Local AI"),
        local_url=v["LOCAL_AI_URL"].strip().rstrip("/"),
        local_model=local_model,
    )


class AIError(Exception):
    """Becomes an Anthropic-style error body with this HTTP status."""

    def __init__(self, status: int, kind: str, message: str):
        super().__init__(message)
        self.status, self.kind, self.message = status, kind, message

    def body(self) -> dict:
        return {"type": "error", "error": {"type": self.kind, "message": self.message}}


class ClaudeFailed(Exception):
    pass


class QwenUnavailable(Exception):
    """Ollama is not running, or the model is not installed."""


# ---- request parsing --------------------------------------------------------------------
def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    raise AIError(400, "invalid_request_error", "message content must be a string or a list")


def parse_request(body: Any) -> tuple[list[dict], str, int]:
    """-> (messages with block lists, system text, max_tokens)."""
    if not isinstance(body, dict) or not isinstance(body.get("messages"), list) \
            or not body["messages"]:
        raise AIError(400, "invalid_request_error", "Body must be a Messages request with "
                      "a non-empty 'messages' list")
    msgs = []
    for m in body["messages"]:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            raise AIError(400, "invalid_request_error", "Each message needs role user/assistant")
        msgs.append({"role": m["role"], "blocks": _blocks(m.get("content"))})
    system = body.get("system") or ""
    if isinstance(system, list):
        system = "\n\n".join(b.get("text", "") for b in system if isinstance(b, dict))
    try:
        max_tokens = int(body.get("max_tokens") or 1000)
    except (TypeError, ValueError):
        raise AIError(400, "invalid_request_error", "max_tokens must be a number") from None
    return msgs, str(system), max(1, max_tokens)


def has_image(msgs) -> bool:
    return any(b.get("type") == "image" for m in msgs for b in m["blocks"])


def _check_blocks(msgs):
    for m in msgs:
        for b in m["blocks"]:
            t = b.get("type")
            if t == "document":
                raise AIError(400, "invalid_request_error",
                              "A whole PDF can't be sent to the AI on this PC. Open it so the "
                              "app can read it page by page (pages are sent as pictures).")
            if t not in ("text", "image"):
                raise AIError(400, "invalid_request_error", f"Unsupported content block {t!r}")
            if t == "image":
                src = b.get("source") or {}
                if src.get("type") != "base64" or not src.get("data"):
                    raise AIError(400, "invalid_request_error",
                                  "Images must be base64 image blocks")


def _text_of(blocks) -> str:
    return "\n\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def prompt_for_claude(msgs) -> str:
    """One text prompt for `claude -p`. Drill sends a single user message: its text as is."""
    if len(msgs) == 1:
        return _text_of(msgs[0]["blocks"])
    parts = []
    for m in msgs:
        parts.append(("User: " if m["role"] == "user" else "Assistant: ") + _text_of(m["blocks"]))
    return "\n\n".join(parts)


def ollama_messages(msgs, system: str) -> list[dict]:
    out = [{"role": "system", "content": system}] if system else []
    for m in msgs:
        om = {"role": m["role"], "content": _text_of(m["blocks"])}
        imgs = [b["source"]["data"] for b in m["blocks"] if b.get("type") == "image"]
        if imgs:
            om["images"] = imgs
        out.append(om)
    return out


# ---- response shape ---------------------------------------------------------------------
_THINK = re.compile(r"<think>.*?</think>\s*", re.S)


def anthropic_reply(text: str, stop_reason: str, model_used: str, model: str,
                    usage: dict | None = None, **extra) -> dict:
    out = {"id": "msg_local_" + uuid.uuid4().hex, "type": "message", "role": "assistant",
           "model": model, "content": [{"type": "text", "text": text}],
           "stop_reason": stop_reason, "stop_sequence": None,
           "usage": usage or {"input_tokens": 0, "output_tokens": 0},
           "model_used": model_used}
    out.update(extra)
    return out


def from_ollama(d: dict, model: str) -> dict:
    text = _THINK.sub("", (d.get("message") or {}).get("content") or "")
    stop = "max_tokens" if d.get("done_reason") == "length" else "end_turn"
    usage = {"input_tokens": int(d.get("prompt_eval_count") or 0),
             "output_tokens": int(d.get("eval_count") or 0)}
    return anthropic_reply(text, stop, "qwen", model, usage)


def from_claude(d: dict) -> dict:
    if not isinstance(d, dict) or d.get("type") != "result":
        raise ClaudeFailed("claude -p gave no result object")
    if d.get("is_error") or d.get("subtype") != "success":
        raise ClaudeFailed(f"claude -p reported an error ({d.get('subtype')}, "
                           f"api status {d.get('api_error_status')}): "
                           f"{str(d.get('result') or '')[:200]}")
    text = d.get("result")
    if not isinstance(text, str):
        raise ClaudeFailed("claude -p result has no text")
    stop = "max_tokens" if d.get("stop_reason") == "max_tokens" else "end_turn"
    u = d.get("usage") or {}
    usage = {"input_tokens": int((u.get("input_tokens") or 0)
                                 + (u.get("cache_creation_input_tokens") or 0)
                                 + (u.get("cache_read_input_tokens") or 0)),
             "output_tokens": int(u.get("output_tokens") or 0)}
    models = list((d.get("modelUsage") or {}).keys())
    return anthropic_reply(text, stop, "claude", models[-1] if models else "claude", usage)


# ---- Qwen via Ollama ----------------------------------------------------------------------
def call_ollama(cfg: AIConfig, msgs, system: str, max_tokens: int) -> dict:
    body = {"model": cfg.ollama_model, "stream": False, "think": False,
            "truncate": False, "shift": False,
            "messages": ollama_messages(msgs, system),
            "options": {"num_ctx": cfg.num_ctx, "num_predict": max_tokens}}
    req = urllib.request.Request(cfg.ollama_url + "/api/chat", json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.ollama_timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        n = re.search(r"request \((\d+) tokens\) exceeds the available context size", raw)
        if n or "exceed_context_size" in raw:
            got = n.group(1) if n else "?"
            raise AIError(400, "invalid_request_error",
                          f"Prompt is too long for Qwen: {got} tokens, limit {cfg.num_ctx} "
                          f"(OLLAMA_NUM_CTX). Nothing was cut or sent; use smaller pieces.") \
                from None
        if e.code == 404 and "not found" in raw.lower():
            raise QwenUnavailable(f"model {cfg.ollama_model} is not installed in Ollama") from None
        raise AIError(502, "api_error", f"Ollama error {e.code}: {raw[:200]}") from None
    except (urllib.error.URLError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise AIError(504, "api_error", "Qwen took too long to answer (timeout)") from None
        raise QwenUnavailable(f"Ollama is not reachable at {cfg.ollama_url} ({reason})") from None
    except (TimeoutError, socket.timeout):
        raise AIError(504, "api_error", "Qwen took too long to answer (timeout)") from None
    if d.get("error"):
        raise AIError(502, "api_error", f"Ollama error: {str(d['error'])[:200]}")
    return from_ollama(d, cfg.ollama_model)


# ---- an OpenAI-compatible local server (LM Studio, llama.cpp, Jan, vLLM, Ollama's /v1) ------
def openai_messages(msgs, system: str) -> list[dict]:
    out = [{"role": "system", "content": system}] if system else []
    for m in msgs:
        imgs = [b["source"] for b in m["blocks"] if b.get("type") == "image"]
        if not imgs:
            out.append({"role": m["role"], "content": _text_of(m["blocks"])})
            continue
        parts = [{"type": "text", "text": _text_of(m["blocks"])}]
        parts += [{"type": "image_url", "image_url": {
            "url": f"data:{s.get('media_type') or 'image/jpeg'};base64,{s['data']}"}} for s in imgs]
        out.append({"role": m["role"], "content": parts})
    return out


def call_openai_local(cfg: AIConfig, msgs, system: str, max_tokens: int, no_thinking: bool = True) -> dict:
    # reasoning_effort "none": a thinking model (Qwen3.5, DeepSeek-R1…) otherwise spends the whole
    # reply thinking and returns no answer — measured on Ollama's /v1 with qwen3.5:9b: empty at
    # 300 tokens; with "none", a full answer in 3.5 s. A server that rejects it is asked again without.
    body = {"model": cfg.local_model or "local-model", "stream": False, "max_tokens": max_tokens,
            "messages": openai_messages(msgs, system)}
    if no_thinking:
        body["reasoning_effort"] = "none"
    req = urllib.request.Request(cfg.local_url + "/chat/completions", json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.ollama_timeout) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if no_thinking and e.code in (400, 422) and "reasoning" in raw.lower():
            return call_openai_local(cfg, msgs, system, max_tokens, no_thinking=False)
        if e.code == 404:
            raise QwenUnavailable(f"model {cfg.local_model or '?'} not found at {cfg.local_url} ({raw[:120]})") from None
        raise AIError(502, "api_error", f"{cfg.local_name} error {e.code}: {raw[:200]}") from None
    except (urllib.error.URLError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise AIError(504, "api_error", f"{cfg.local_name} took too long to answer (timeout)") from None
        raise QwenUnavailable(f"{cfg.local_name} is not reachable at {cfg.local_url} ({reason})") from None
    except (TimeoutError, socket.timeout):
        raise AIError(504, "api_error", f"{cfg.local_name} took too long to answer (timeout)") from None
    try:
        choice = d["choices"][0]
        text = _THINK.sub("", choice["message"].get("content") or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise AIError(502, "api_error", f"{cfg.local_name} gave an unexpected reply: {str(d)[:200]}") from None
    if not text.strip() and choice["message"].get("reasoning"):
        raise AIError(502, "api_error", f"{cfg.local_name} spent the whole reply thinking and gave no answer — "
                      "use a non-thinking model, or turn thinking off in the server's settings")
    u = d.get("usage") or {}
    return anthropic_reply(text, "max_tokens" if choice.get("finish_reason") == "length" else "end_turn",
                           "qwen", cfg.local_model, {"input_tokens": int(u.get("prompt_tokens") or 0),
                                                     "output_tokens": int(u.get("completion_tokens") or 0)},
                           ai_name=cfg.local_name)


def call_local(cfg: AIConfig, msgs, system: str, max_tokens: int) -> dict:
    """The AI on this PC: Ollama (any model) or an OpenAI-compatible local server."""
    if cfg.local == "off":
        raise QwenUnavailable("no local AI is set up (LOCAL_AI=off)")
    if cfg.local == "openai":
        return call_openai_local(cfg, msgs, system, max_tokens)
    r = call_ollama(cfg, msgs, system, max_tokens)
    r["ai_name"] = cfg.local_name
    return r


# ---- other online AIs: their own CLI, the user's own sign-in (codex, gemini, custom) --------
def cli_command(cfg: AIConfig, workdir: str, prompt_file: str, output_file: str,
                images: list[str]) -> tuple[list[str], bool, bool]:
    """(argv, prompt on stdin?, answer in output_file?) for the configured online CLI."""
    exe = shutil.which(cfg.online_path) or cfg.online_path
    model = ["--model", cfg.online_model] if cfg.online_model else []
    if cfg.online == "codex":
        # options checked against OpenAI's non-interactive docs (2026-10-01): "-" = prompt on stdin,
        # read-only sandbox, --ephemeral = no session files kept, -o = the final answer in a file
        argv = [exe, "exec", "--skip-git-repo-check", "--sandbox", "read-only", "--ephemeral", "--cd", workdir, *model]
        for im in images:
            argv += ["--image", im]
        return argv + ["--output-last-message", output_file, "-"], True, True
    if cfg.online == "gemini":
        # Gemini CLI docs: --prompt "is appended to stdin input" and forces non-interactive mode;
        # headless runs reuse the cached Google sign-in
        return [exe, *model, "--output-format", "text",
                "--prompt", "Follow the request given on standard input exactly."], True, False
    # custom: ONLINE_AI_COMMAND, with {prompt_file} {output_file} {workdir} {model} {images}
    import shlex
    argv: list[str] = []
    for tok in shlex.split(cfg.online_command, posix=True):
        if tok == "{images}":
            argv += images
            continue
        argv.append(tok.replace("{prompt_file}", prompt_file).replace("{output_file}", output_file)
                       .replace("{workdir}", workdir).replace("{model}", cfg.online_model))
    if argv:
        argv[0] = shutil.which(argv[0]) or argv[0]
    return argv, "{prompt_file}" not in cfg.online_command, "{output_file}" in cfg.online_command


def call_cli(cfg: AIConfig, msgs, system: str) -> dict:
    if has_image(msgs) and not cfg.online_images:
        raise ClaudeFailed(f"{cfg.online_name} can't read pictures here (ONLINE_AI_IMAGES=off)")
    if cfg.online == "custom" and not cfg.online_command:
        raise ClaudeFailed("ONLINE_AI=custom needs ONLINE_AI_COMMAND (see docs/CONNECT-AI.md)")
    workdir = tempfile.mkdtemp(prefix="monospace-ai-")
    t0 = time.monotonic()
    try:
        prompt = (CLAUDE_SYSTEM + ("\n\n" + system if system else "") + "\n\n" + prompt_for_claude(msgs))
        pf, of = os.path.join(workdir, "prompt.txt"), os.path.join(workdir, "answer.txt")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt)
        images = []
        for m in msgs:
            for b in m["blocks"]:
                if b.get("type") == "image":
                    ext = ".png" if "png" in (b["source"].get("media_type") or "") else ".jpg"
                    ip = os.path.join(workdir, f"image{len(images) + 1}{ext}")
                    with open(ip, "wb") as f:
                        f.write(base64.b64decode(b["source"]["data"]))
                    images.append(ip)
        argv, stdin, to_file = cli_command(cfg, workdir, pf, of, images)
        try:
            p = subprocess.run(argv, input=prompt.encode("utf-8") if stdin else None, capture_output=True,
                               cwd=workdir, env=child_env(), timeout=cfg.claude_timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise ClaudeFailed(f"{cfg.online_name} program not found ({argv[0] if argv else '?'})") from None
        except subprocess.TimeoutExpired:
            raise ClaudeFailed(f"{cfg.online_name} took longer than {cfg.claude_timeout:.0f}s") from None
        out = p.stdout.decode("utf-8", "replace").strip()
        err = p.stderr.decode("utf-8", "replace").strip()
        text = ""
        if to_file and os.path.exists(of):
            with open(of, encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
        elif not to_file:
            text = out
        if p.returncode != 0 or not text:
            raise ClaudeFailed(f"{cfg.online_name} exit {p.returncode}: {(err or out or 'no answer')[:300]}")
        log.info("%s: %.1fs", cfg.online_name, time.monotonic() - t0)
        return anthropic_reply(_THINK.sub("", text), "end_turn", "claude", cfg.online_model or cfg.online,
                               ai_name=cfg.online_name)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---- Claude via `claude -p` -------------------------------------------------------------
def claude_command(cfg: AIConfig, system: str, stream: bool = False,
                   model: str | None = None) -> list[str]:
    exe = shutil.which(cfg.claude_cli_path) or cfg.claude_cli_path
    io = (["--input-format", "stream-json",    # a full message with image blocks on stdin
           "--output-format", "stream-json", "--verbose"] if stream
          else ["--output-format", "json"])    # one JSON result object
    cmd = [exe, "-p", *io,                     # headless print mode; prompt comes on stdin
           "--max-turns", "1",                 # a single turn
           "--tools", "",                      # no tools at all
           "--no-session-persistence",         # nothing saved to resume
           "--strict-mcp-config",              # no MCP servers
           "--disable-slash-commands",         # no skills
           "--system-prompt", CLAUDE_SYSTEM + ("\n\n" + system if system else "")]
    model = model or cfg.claude_model
    if model:
        cmd += ["--model", model]
    if cfg.claude_effort:
        cmd += ["--effort", cfg.claude_effort]
    return cmd


def child_env() -> dict:
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):   # never an API key
        env.pop(k, None)
    env.pop("CLAUDE_EFFORT", None)          # --effort decides, not a Claude Code session around us
    env["MAX_THINKING_TOKENS"] = "0"        # no hidden thinking: the tasks are structured, not puzzles
    return env


def stream_input_for_claude(msgs) -> str:
    """One stream-json user message for `claude -p --input-format stream-json`: the request's
    image and text blocks, in order (earlier turns, if any, go first as labelled text)."""
    blocks = []
    for m in msgs[:-1]:
        blocks.append({"type": "text", "text": ("User: " if m["role"] == "user" else
                                                "Assistant: ") + _text_of(m["blocks"])})
    for b in msgs[-1]["blocks"]:
        if b.get("type") == "image":
            s = b["source"]
            blocks.append({"type": "image", "source": {"type": "base64",
                           "media_type": s.get("media_type") or "image/jpeg", "data": s["data"]}})
        elif b.get("type") == "text":
            blocks.append({"type": "text", "text": b.get("text", "")})
    return json.dumps({"type": "user", "message": {"role": "user", "content": blocks}}) + "\n"


def call_claude(cfg: AIConfig, prompt: str, system: str, stream: bool = False,
                model: str | None = None) -> dict:
    """prompt: plain text (stream=False) or one stream-json line (stream=True)."""
    workdir = tempfile.mkdtemp(prefix="monospace-claude-")      # empty: no CLAUDE.md to load
    t0 = time.monotonic()
    try:
        try:
            p = subprocess.run(claude_command(cfg, system, stream, model), input=prompt.encode("utf-8"),
                               capture_output=True, cwd=workdir, env=child_env(),
                               timeout=cfg.claude_timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except FileNotFoundError:
            raise ClaudeFailed(f"claude program not found ({cfg.claude_cli_path})") from None
        except subprocess.TimeoutExpired:
            raise ClaudeFailed(f"claude -p took longer than {cfg.claude_timeout:.0f}s") from None
        out = p.stdout.decode("utf-8", "replace").strip()
        try:
            if stream:   # one JSON event per line; the answer is the "result" event
                d = next((e for e in map(json.loads, filter(None, out.splitlines()))
                          if isinstance(e, dict) and e.get("type") == "result"), None)
                if d is None:
                    raise ValueError("no result event")
            else:
                d = json.loads(out)
        except ValueError:
            err = p.stderr.decode("utf-8", "replace").strip()
            raise ClaudeFailed(f"claude -p exit {p.returncode}, no JSON: "
                               f"{(err or out)[:200]}") from None
        reply = from_claude(d)
        log.info("claude %s: %.1fs, %d tokens out", model or cfg.claude_model or "default",
                 time.monotonic() - t0, reply["usage"]["output_tokens"])
        return reply
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---- routing ------------------------------------------------------------------------------
CLAUDE_LIMIT_PAUSE = 1800          # seconds Claude is skipped after a usage / rate limit
_LIMIT = re.compile(r"usage limit|session limit|rate limit|limit reached|quota|too many requests|"
                    r"api status 429|\b429\b", re.I)
# Claude Code signed out (its sign-in expired). Every request would fail the same way until the
# user signs in again, so Claude is paused for a few minutes (or until "Try Claude again").
CLAUDE_SIGNIN_PAUSE = 300
_SIGNIN = re.compile(r"failed to authenticate|oauth|not logged in|please (run )?/?login|log in again|"
                     r"authentication_error|invalid (api )?key|unauthori[sz]ed|api status 401|\b401\b", re.I)

class Router:
    def __init__(self, cfg: AIConfig):
        self.cfg = cfg
        self._claude_paused_until = 0.0
        self._pause_reason = ""                # "limit" | "signin" while paused
        self._claude_slots = asyncio.Semaphore(MAX_CLAUDE_AT_ONCE)
        self._reach: tuple[float, bool] | None = None
        self._local: tuple[float, bool] | None = None

    def _connect(self) -> bool:
        try:
            with socket.create_connection((self.cfg.reach_host, self.cfg.reach_port),
                                          timeout=REACH_TIMEOUT):
                return True
        except OSError:
            return False

    async def claude_reachable(self) -> bool:
        now = time.monotonic()
        if self._reach and now - self._reach[0] < (REACH_CACHE_SECONDS if self._reach[1]
                                                    else REACH_FAIL_CACHE_SECONDS):
            return self._reach[1]
        try:   # DNS can hang when offline; the whole check gets 2 seconds
            ok = await asyncio.wait_for(asyncio.to_thread(self._connect), REACH_TIMEOUT + 0.2)
        except asyncio.TimeoutError:
            ok = False
        self._reach = (now, ok)
        return ok

    async def route_for_text(self) -> dict:
        """Which model would answer a text-only request right now, and Qwen's context size,
        so the app can size a prompt for Qwen (GET /api/ai/route). Also what each AI is called
        and how to sign in to the online one again."""
        paused = self.claude_paused()
        claude = self.cfg.claude_cli and not paused and await self.claude_reachable()
        return {"model": "claude" if claude else "qwen", "num_ctx": self.cfg.num_ctx,
                "claude_paused": paused, "pause_reason": self._pause_reason if paused else "",
                "cloud_name": self.cfg.online_name, "local_name": self.cfg.local_name,
                "online": self.cfg.online, "local": self.cfg.local,
                "local_model": self.cfg.local_model, "signin_help": self.cfg.online_signin,
                "local_ok": await self.local_reachable()}

    def signin_text(self) -> str:
        c = self.cfg
        return f"{c.online_name} is signed out — sign in again ({c.online_signin}); {c.local_name} answers until then"

    async def call_online(self, msgs, system: str, model: str | None) -> dict:
        if self.cfg.online == "claude":
            if has_image(msgs):
                return await asyncio.to_thread(call_claude, self.cfg, stream_input_for_claude(msgs),
                                               system, True, model)
            return await asyncio.to_thread(call_claude, self.cfg, prompt_for_claude(msgs), system,
                                           False, model)
        return await asyncio.to_thread(call_cli, self.cfg, msgs, system)

    def _local_check(self) -> bool:
        c = self.cfg
        if c.local == "off":
            return False
        url = c.local_url + "/models" if c.local == "openai" else c.ollama_url + "/api/tags"
        try:
            with urllib.request.urlopen(url, timeout=1.5) as r:
                return r.status == 200
        except (OSError, ValueError):
            return False

    async def local_reachable(self) -> bool:
        now = time.monotonic()
        if self._local and now - self._local[0] < (REACH_CACHE_SECONDS if self._local[1] else REACH_FAIL_CACHE_SECONDS):
            return self._local[1]
        ok = await asyncio.to_thread(self._local_check)
        self._local = (now, ok)
        return ok

    def claude_paused(self) -> bool:
        return time.monotonic() < self._claude_paused_until

    def pause_claude(self, reason: str, seconds: float) -> None:
        self._claude_paused_until = time.monotonic() + seconds
        self._pause_reason = reason

    def resume_claude(self) -> None:
        """Try Claude again now (POST /api/ai/claude/retry): after signing in again, say."""
        self._claude_paused_until = 0.0
        self._pause_reason = ""
        self._reach = None
        self._local = None

    def _pause_text(self) -> str:
        c = self.cfg
        return self.signin_text() if self._pause_reason == "signin" else \
            f"{c.online_name} usage limit reached earlier; using {c.local_name} for now"

    async def handle(self, body: Any) -> dict:
        t0 = time.monotonic()
        reply = await self._handle(body)
        reply["elapsed_ms"] = round((time.monotonic() - t0) * 1000)
        return reply

    async def _handle(self, body: Any) -> dict:
        msgs, system, max_tokens = parse_request(body)
        _check_blocks(msgs)
        model = (self.cfg.claude_fast_model or None) if isinstance(body, dict) and \
            body.get("tier") == "fast" else None
        only_claude = isinstance(body, dict) and body.get("only") == "claude"
        only_qwen = isinstance(body, dict) and body.get("only") == "qwen"     # the student chose Qwen
        on, lo = self.cfg.online_name, self.cfg.local_name
        if only_claude:
            if not self.cfg.claude_cli:
                raise AIError(503, "claude_unavailable", "No online AI is switched on (ONLINE_AI / CLAUDE_CLI).")
            if self.claude_paused():
                raise AIError(503, "claude_unavailable",
                              self.signin_text() if self._pause_reason == "signin" else f"{on} is paused after a usage limit.")
            if not await self.claude_reachable():
                raise AIError(503, "claude_unavailable", f"{on} is not reachable (offline?).")
        fallback = {}
        if self.claude_paused():
            fallback = {"fallback_from": "claude", "fallback_reason": self._pause_text()}
        elif not only_qwen and self.cfg.claude_cli and await self.claude_reachable():
            try:
                async with self._claude_slots:
                    reply = await self.call_online(msgs, system, model)
                    reply.setdefault("ai_name", on)
                    return reply
            except ClaudeFailed as e:
                log.warning("%s failed, retrying on %s: %s", on, lo, e)
                if _SIGNIN.search(str(e)):
                    self.pause_claude("signin", CLAUDE_SIGNIN_PAUSE)
                    log.warning("%s is signed out: using %s for the next %d minutes "
                                "(or until the app says try again)", on, lo, CLAUDE_SIGNIN_PAUSE // 60)
                    e = ClaudeFailed(self.signin_text() + f" ({e})")
                elif _LIMIT.search(str(e)):
                    self.pause_claude("limit", CLAUDE_LIMIT_PAUSE)
                    log.warning("%s usage limit: using %s for the next %d minutes", on, lo,
                                CLAUDE_LIMIT_PAUSE // 60)
                if only_claude:
                    raise AIError(503, "claude_unavailable", str(e)[:300]) from None
                fallback = {"fallback_from": "claude", "fallback_reason": str(e)[:300]}
        try:
            reply = await asyncio.to_thread(call_local, self.cfg, msgs, system, max_tokens)
        except QwenUnavailable as e:
            why = f"{lo} is not available: {e}."
            if only_qwen:
                why += f" You chose {lo}: start it, or switch back to {on}."
            elif fallback:
                why += f" {on} failed too: {fallback['fallback_reason']}"
            elif not self.cfg.claude_cli:
                why += " No online AI is switched on (ONLINE_AI / CLAUDE_CLI=off)."
            else:
                why += f" {on} is not reachable (offline?)."
            raise AIError(503, "ai_not_configured", why) from None
        reply.update(fallback)
        return reply
