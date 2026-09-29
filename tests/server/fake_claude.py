"""Stand-in for the `claude` program in tests/server/test_ai.py. Never contacts anything.

Records argv, working folder (and what is in it), stdin and whether an API key reached it,
then prints a result object shaped like `claude -p --output-format json` (Claude Code 2.1.258).
FAKE_CLAUDE_MODE: ok | max_tokens | no_stop_reason | error | limit | slow
"""
import json
import os
import sys
import time
import uuid

start = time.time()
prompt = sys.stdin.buffer.read().decode("utf-8")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "slow":
    time.sleep(1.0)
res = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1,
       "result": "CLAUDE:" + prompt[-40:], "stop_reason": "end_turn",
       "api_error_status": None, "usage": {"input_tokens": 3, "output_tokens": 4},
       "modelUsage": {"claude-opus-5": {}}}
if mode == "max_tokens":
    res["stop_reason"] = "max_tokens"
elif mode == "no_stop_reason":
    del res["stop_reason"]
elif mode == "error":
    res.update(subtype="error_during_execution", is_error=True, result="API error 529")
elif mode == "limit":
    res.update(subtype="success", is_error=True, api_error_status=429,
               result="Claude AI usage limit reached. Your limit will reset at 5pm.")
log = {"argv": sys.argv[1:], "cwd": os.getcwd(), "cwd_listing": os.listdir("."),
       "stdin": prompt, "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
       "start": start, "end": time.time()}
with open(os.path.join(os.environ["FAKE_CLAUDE_LOG"], f"{start:.6f}-{uuid.uuid4().hex}.json"),
          "w", encoding="utf-8") as f:
    json.dump(log, f)
if "--input-format" in sys.argv:          # stream-json in and out, like the real program
    msg = json.loads(prompt.splitlines()[0])["message"]
    kinds = [b["type"] for b in msg["content"]]
    text = " ".join(b["text"] for b in msg["content"] if b["type"] == "text")
    res["result"] = "CLAUDE-SEES:" + ",".join(kinds) + ":" + text[-40:]
    sys.stdout.write(json.dumps({"type": "system", "subtype": "init"}) + "\n" +
                     json.dumps(res) + "\n")
else:
    sys.stdout.write(json.dumps(res))
