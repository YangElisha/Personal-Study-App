"""The AI router behind POST /api/ai (Phase 5). See docs/ARCHITECTURE.md, docs/OFFLINE-AI.md.

Per request (2026-09-29: Claude whenever online, Qwen only offline):
  1. CLAUDE_CLI=on and api.anthropic.com reachable within 2 s -> Claude via `claude -p`,
     text AND pictures (pictures go in as image blocks via --input-format stream-json).
  2. otherwise (offline, or CLAUDE_CLI=off) -> Qwen.
If Claude fails for any reason (e.g. usage limit) the request is retried once on Qwen; the
reply then says model_used "qwen" with fallback_from "claude" and the reason.

Claude is reached ONLY by running the official `claude` program: prompt on stdin, from an
empty temporary folder, no tools, one turn, JSON output. Claude Code's login is never read
here, and ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN are removed from the child's environment
so it always uses the user's own Claude Code sign-in.

Qwen: options.num_ctx from OLLAMA_NUM_CTX on every request, think:false (Qwen3.5 is a
thinking model; the app wants the plain answer), truncate:false and shift:false so Ollama
refuses a prompt that doesn't fit (with its exact token count) instead of silently cutting
it, and ends a reply that runs out of room with done_reason "length" (-> "max_tokens").

Every answer has Anthropic's shape: {content:[{type:"text",text}], stop_reason, ...} plus
model_used "claude"|"qwen". Errors use Anthropic's error shape
{type:"error", error:{type, message}}.
"""
from __future__ import annotations

import asyncio
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
           "CLAUDE_CLI_PATH", "CLAUDE_MODEL", "CLAUDE_TIMEOUT", "CLAUDE_REACH_HOST")
AI_DEFAULTS = {
    "OLLAMA_URL": "http://localhost:11434",
    "OLLAMA_MODEL": "qwen3.5:9b",
    "OLLAMA_NUM_CTX": "8192",
    "OLLAMA_TIMEOUT": "900",          # seconds; an 8000-token transcription takes minutes
    "CLAUDE_CLI": "off",
    "CLAUDE_CLI_PATH": "claude",
    "CLAUDE_MODEL": "",               # empty = Claude Code's own default model
    "CLAUDE_TIMEOUT": "600",
    # host:port the 2-second reachability check connects to. Only change it to simulate
    # being offline (e.g. 127.0.0.1:9) — the real check is api.anthropic.com:443.
    "CLAUDE_REACH_HOST": "api.anthropic.com:443",
}

CLAUDE_SYSTEM = ("You are answering a request from MonoSpace, a personal study app. Reply to the "
                 "user's message directly, following its instructions exactly. You have no "
                 "tools; answer from the message alone.")

REACH_TIMEOUT = 2.0
REACH_CACHE_SECONDS = 15.0
MAX_CLAUDE_AT_ONCE = 2


@dataclass(frozen=True)
class AIConfig:
    ollama_url: str
    ollama_model: str
    num_ctx: int
    ollama_timeout: float
    claude_cli: bool
    claude_cli_path: str
    claude_model: str
    claude_timeout: float
    reach_host: str
    reach_port: int


def load_ai_config(env_file=None, environ=None) -> AIConfig:
    """.env values; a process environment variable of the same name overrides them."""
    environ = os.environ if environ is None else environ
    v = dict(AI_DEFAULTS)
    v.update({k: x for k, x in read_env_file(ENV_FILE if env_file is None else env_file).items()
              if k in AI_KEYS})
    for k in AI_KEYS:
        if environ.get(k):
            v[k] = environ[k]
    host, _, port = v["CLAUDE_REACH_HOST"].rpartition(":")
    return AIConfig(
        ollama_url=v["OLLAMA_URL"].rstrip("/"),
        ollama_model=v["OLLAMA_MODEL"],
        num_ctx=int(v["OLLAMA_NUM_CTX"]),
        ollama_timeout=float(v["OLLAMA_TIMEOUT"]),
        claude_cli=v["CLAUDE_CLI"].strip().lower() in ("on", "1", "true", "yes"),
        claude_cli_path=v["CLAUDE_CLI_PATH"],
        claude_model=v["CLAUDE_MODEL"].strip(),
        claude_timeout=float(v["CLAUDE_TIMEOUT"]),
        reach_host=host or v["CLAUDE_REACH_HOST"],
        reach_port=int(port) if port else 443,
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


# ---- Claude via `claude -p` -------------------------------------------------------------
def claude_command(cfg: AIConfig, system: str, stream: bool = False) -> list[str]:
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
    if cfg.claude_model:
        cmd += ["--model", cfg.claude_model]
    return cmd


def child_env() -> dict:
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):   # never an API key
        env.pop(k, None)
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


def call_claude(cfg: AIConfig, prompt: str, system: str, stream: bool = False) -> dict:
    """prompt: plain text (stream=False) or one stream-json line (stream=True)."""
    workdir = tempfile.mkdtemp(prefix="monospace-claude-")      # empty: no CLAUDE.md to load
    try:
        try:
            p = subprocess.run(claude_command(cfg, system, stream), input=prompt.encode("utf-8"),
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
        return from_claude(d)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---- routing ------------------------------------------------------------------------------
class Router:
    def __init__(self, cfg: AIConfig):
        self.cfg = cfg
        self._claude_slots = asyncio.Semaphore(MAX_CLAUDE_AT_ONCE)
        self._reach: tuple[float, bool] | None = None

    def _connect(self) -> bool:
        try:
            with socket.create_connection((self.cfg.reach_host, self.cfg.reach_port),
                                          timeout=REACH_TIMEOUT):
                return True
        except OSError:
            return False

    async def claude_reachable(self) -> bool:
        now = time.monotonic()
        if self._reach and now - self._reach[0] < REACH_CACHE_SECONDS:
            return self._reach[1]
        try:   # DNS can hang when offline; the whole check gets 2 seconds
            ok = await asyncio.wait_for(asyncio.to_thread(self._connect), REACH_TIMEOUT + 0.2)
        except asyncio.TimeoutError:
            ok = False
        self._reach = (now, ok)
        return ok

    async def route_for_text(self) -> dict:
        """Which model would answer a text-only request right now, and Qwen's context size,
        so the app can size a prompt for Qwen (GET /api/ai/route)."""
        claude = self.cfg.claude_cli and await self.claude_reachable()
        return {"model": "claude" if claude else "qwen", "num_ctx": self.cfg.num_ctx}

    async def handle(self, body: Any) -> dict:
        msgs, system, max_tokens = parse_request(body)
        _check_blocks(msgs)
        fallback = {}
        if self.cfg.claude_cli and await self.claude_reachable():
            try:
                async with self._claude_slots:
                    if has_image(msgs):
                        return await asyncio.to_thread(call_claude, self.cfg,
                                                       stream_input_for_claude(msgs), system, True)
                    return await asyncio.to_thread(call_claude, self.cfg,
                                                   prompt_for_claude(msgs), system)
            except ClaudeFailed as e:
                log.warning("claude -p failed, retrying on Qwen: %s", e)
                fallback = {"fallback_from": "claude", "fallback_reason": str(e)[:300]}
        try:
            reply = await asyncio.to_thread(call_ollama, self.cfg, msgs, system, max_tokens)
        except QwenUnavailable as e:
            why = f"Qwen is not available: {e}."
            if fallback:
                why += f" Claude failed too: {fallback['fallback_reason']}"
            elif not self.cfg.claude_cli:
                why += " Claude is switched off (CLAUDE_CLI=off)."
            else:
                why += " Claude is not reachable (offline?)."
            raise AIError(503, "ai_not_configured", why) from None
        reply.update(fallback)
        return reply
