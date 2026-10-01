"""Stand-in for other AIs' command-line programs (codex, gemini, a custom one) in
tests/server/test_connect_ai.py. Never contacts anything. Logs argv, stdin and which image files
existed; answers on stdout, or into the --output-last-message / --out file.
FAKE_CLI_MODE: ok | signedout | limit
"""
import json
import os
import sys
import time
import uuid

argv = sys.argv[1:]
stdin = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.buffer.read().decode("utf-8")
mode = os.environ.get("FAKE_CLI_MODE", "ok")
prompt = stdin
if "--prompt-file" in argv:
    with open(argv[argv.index("--prompt-file") + 1], encoding="utf-8") as f:
        prompt = f.read()
images = [argv[i + 1] for i, a in enumerate(argv) if a in ("--image", "--img")]
log = {"argv": argv, "stdin": stdin, "cwd": os.getcwd(),
       "images_exist": [os.path.exists(p) for p in images]}
with open(os.path.join(os.environ["FAKE_CLI_LOG"], f"{time.time():.6f}-{uuid.uuid4().hex}.json"),
          "w", encoding="utf-8") as f:
    json.dump(log, f)
if mode == "signedout":
    sys.stderr.write("Error: Not logged in. Please run codex login.\n")
    sys.exit(1)
if mode == "limit":
    sys.stderr.write("You have hit your usage limit. Try again later.\n")
    sys.exit(1)
answer = "CLI:" + prompt.strip()[-30:]
out = None
for flag in ("--output-last-message", "--out"):
    if flag in argv:
        out = argv[argv.index(flag) + 1]
if out:
    with open(out, "w", encoding="utf-8") as f:
        f.write(answer)
    print("(progress noise that must not be taken as the answer)")
else:
    print(answer)
